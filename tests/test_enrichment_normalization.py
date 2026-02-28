from aia.models.contracts import EnrichedTask
from aia.workflow.enrichment import normalize_enriched_task_raw, normalize_route_plan_raw


def test_normalize_handles_non_schema_llm_output() -> None:
    raw = {
        "task_type": "issue_summary",
        "requires_rag": True,
        "action_plans": [
            {
                "platform": "Jira",
                "action": "jira_search_issues",
                "params": {"jql": "project = APP"},
                "risk_level": "low",
                "depends_on": None,
                "extra_field": "drop-me",
            },
            {
                "system": "Telegram",
                "action": "telegram_send_message",
                "params": {"text": "hello"},
                "depends_on": "jira_search_issues",
            },
        ],
    }
    normalized = normalize_enriched_task_raw(raw)
    model = EnrichedTask.model_validate(normalized)

    assert model.task_type == "summarization"
    assert model.output_tone == "neutral"
    assert len(model.action_plans) == 2
    assert model.action_plans[0].system == "jira"
    assert model.action_plans[0].depends_on == []
    assert model.action_plans[1].system == "telegram"
    assert model.action_plans[1].depends_on == ["jira_search_issues"]


def test_normalize_defaults_when_values_invalid() -> None:
    raw = {
        "task_type": 123,
        "requires_rag": "yes",
        "output_tone": "friendly",
        "rag_query_seed": 99,
        "action_plans": [{"system": "unknown", "action": "x"}],
    }
    normalized = normalize_enriched_task_raw(raw)
    model = EnrichedTask.model_validate(normalized)

    assert model.task_type == "general_query"
    assert model.requires_rag is False
    assert model.output_tone == "neutral"
    assert model.rag_query_seed == ""
    assert model.action_plans == []


def test_normalize_route_plan_handles_platform_and_depends_on_shapes() -> None:
    raw = {
        "parallel": "yes",
        "action_plans": [
            {
                "platform": "Jira",
                "action": "jira_search_issues",
                "depends_on": None,
            },
            {
                "platform": "Telegram",
                "action": "telegram_send_message",
                "depends_on": "jira_search_issues",
            },
        ],
    }
    normalized = normalize_route_plan_raw(raw, fallback_action_plans=[])
    assert normalized["parallel"] is True
    assert normalized["action_plans"][0]["system"] == "jira"
    assert normalized["action_plans"][0]["depends_on"] == []
    assert normalized["action_plans"][1]["system"] == "telegram"
    assert normalized["action_plans"][1]["depends_on"] == ["jira_search_issues"]


def test_normalize_action_aliases_to_supported_catalog() -> None:
    raw = {
        "task_type": "find_and_send_summary",
        "requires_rag": False,
        "action_plans": [
            {
                "platform": "Jira",
                "action": "search_issues",
                "params": {"jql": "assignee = currentUser()"},
                "depends_on": None,
            },
            {
                "platform": "Telegram",
                "action": "send_summary",
                "params": {"text": "summary"},
                "depends_on": "search_issues",
            },
        ],
    }
    model = EnrichedTask.model_validate(normalize_enriched_task_raw(raw))
    assert model.task_type == "tool_orchestration"
    assert model.action_plans[0].action == "jira_search_issues"
    assert model.action_plans[1].action == "telegram_send_message"


def test_normalize_unknown_telegram_action_forces_fixed_catalog() -> None:
    raw = {
        "task_type": "tool_orchestration",
        "requires_rag": False,
        "output_tone": "neutral",
        "action_plans": [
            {
                "system": "telegram",
                "action": "telegram_send_to_telegram",
                "params": {"text": "hello"},
            }
        ],
    }
    model = EnrichedTask.model_validate(normalize_enriched_task_raw(raw))
    assert model.action_plans[0].action == "telegram_send_message"


def test_missing_system_with_telegram_prefixed_action_is_not_forced_to_jira() -> None:
    raw = {
        "task_type": "tool_orchestration",
        "requires_rag": False,
        "output_tone": "neutral",
        "action_plans": [
            {
                "action": "telegram_send_message",
                "params": {"text": "hello"},
            }
        ],
    }
    model = EnrichedTask.model_validate(normalize_enriched_task_raw(raw))
    assert model.action_plans[0].system == "telegram"
    assert model.action_plans[0].action == "telegram_send_message"


def test_normalize_jira_search_params_adds_bounds_and_defaults() -> None:
    raw = {
        "task_type": "tool_orchestration",
        "requires_rag": False,
        "output_tone": "neutral",
        "action_plans": [
            {
                "system": "jira",
                "action": "search_issues",
                "params": {"jql": "status = Open"},
            }
        ],
    }
    model = EnrichedTask.model_validate(normalize_enriched_task_raw(raw))
    params = model.action_plans[0].params
    assert "assignee = currentUser()" in params["jql"]
    assert "ORDER BY updated DESC" in params["jql"]
    assert params["maxResults"] == 20


def test_normalize_telegram_send_message_fills_empty_text() -> None:
    raw = {
        "task_type": "tool_orchestration",
        "requires_rag": False,
        "output_tone": "neutral",
        "action_plans": [
            {
                "system": "telegram",
                "action": "send_summary",
                "params": {"text": "   "},
            }
        ],
    }
    model = EnrichedTask.model_validate(normalize_enriched_task_raw(raw))
    assert model.action_plans[0].params["text"] == "Jira summary is ready."
