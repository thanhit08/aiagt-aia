from aia.workflow.nodes import _apply_intent_filters
from aia.workflow.nodes import _compose_telegram_text


def test_file_scoped_request_without_jira_drops_jira_actions() -> None:
    state = {
        "instruction": "Current User Request:\nGet all issues in the file related to accuracy and send to Telegram channel",
        "file_id": "f1",
    }
    route_plan = {
        "parallel": True,
        "action_plans": [
            {"system": "jira", "action": "jira_search_issues", "params": {}, "risk_level": "low", "depends_on": []},
            {
                "system": "telegram",
                "action": "telegram_send_message",
                "params": {"text": "summary"},
                "risk_level": "low",
                "depends_on": [],
            },
        ],
    }
    result = _apply_intent_filters(state, route_plan)
    systems = [x["system"] for x in result["action_plans"]]
    assert systems == ["telegram"]


def test_file_scoped_request_with_jira_keeps_jira_actions() -> None:
    state = {
        "instruction": "Current User Request:\nUse the uploaded file and create Jira tickets for accuracy issues",
        "file_id": "f1",
    }
    route_plan = {
        "parallel": True,
        "action_plans": [
            {"system": "jira", "action": "jira_create_issue", "params": {}, "risk_level": "medium", "depends_on": []}
        ],
    }
    result = _apply_intent_filters(state, route_plan)
    systems = [x["system"] for x in result["action_plans"]]
    assert systems == ["jira"]


def test_compose_telegram_text_prefers_rag_hits() -> None:
    state = {
        "instruction": "Current User Request:\nGet issues related to accuracy in the file and send to Telegram",
        "answer": "generic answer",
        "rag_context": {
            "hits": [
                {"payload": {"text": "accuracy problem on weekly report"}},
                {"payload": {"text": "latency issue in dashboard"}},
            ]
        },
    }
    text = _compose_telegram_text(state)
    assert "Issues from uploaded file" in text
    assert "accuracy problem" in text
    assert "generic answer" not in text
