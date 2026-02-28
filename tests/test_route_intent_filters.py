from aia.workflow.nodes import _apply_intent_filters
from aia.workflow.nodes import _compose_telegram_text


def test_file_scoped_request_without_jira_drops_jira_actions() -> None:
    state = {
        "raw_instruction": "Get all issues in the file related to accuracy and send to Telegram channel",
        "instruction": "Current User Request:\nGet all issues in the file related to accuracy and send to Telegram channel",
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


def test_file_scoped_intent_without_file_id_still_drops_jira() -> None:
    state = {
        "raw_instruction": "Get all issues in the file related to accuracy and send to Telegram channel",
        "instruction": "Current User Request:\nGet all issues in the file related to accuracy and send to Telegram channel",
    }
    route_plan = {
        "parallel": True,
        "action_plans": [
            {"system": "jira", "action": "jira_search_issues", "params": {}, "risk_level": "low", "depends_on": []},
            {"system": "telegram", "action": "telegram_send_message", "params": {}, "risk_level": "low", "depends_on": []},
        ],
    }
    result = _apply_intent_filters(state, route_plan)
    systems = [x["system"] for x in result["action_plans"]]
    assert systems == ["telegram"]


def test_file_scoped_raw_instruction_overrides_jira_in_history_context() -> None:
    state = {
        "raw_instruction": "Get all issues in the file related to accuracy and send to Telegram channel",
        "instruction": (
            "Current User Request:\nGet all issues in the file related to accuracy and send to Telegram channel\n\n"
            "Conversation Summary:\nEarlier task asked to find issues assigned to me in Jira"
        ),
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


def test_file_scoped_create_ticket_to_jira_drops_unneeded_jira_search() -> None:
    state = {
        "raw_instruction": "Get all issues in the file related to accuracy and send to Telegram channel and add ticket to Jira",
        "instruction": "Current User Request:\nGet all issues in the file related to accuracy and send to Telegram channel and add ticket to Jira",
        "file_id": "f1",
    }
    route_plan = {
        "parallel": True,
        "action_plans": [
            {
                "system": "jira",
                "action": "jira_search_issues",
                "params": {"jql": "assignee = currentUser()"},
                "risk_level": "low",
                "depends_on": [],
            },
            {
                "system": "telegram",
                "action": "telegram_send_message",
                "params": {},
                "risk_level": "low",
                "depends_on": ["jira_search_issues"],
            },
            {
                "system": "jira",
                "action": "jira_create_issue",
                "params": {},
                "risk_level": "medium",
                "depends_on": ["jira_search_issues"],
            },
            {
                "system": "jira",
                "action": "jira_assign_issue",
                "params": {},
                "risk_level": "medium",
                "depends_on": ["jira_create_issue"],
            },
        ],
    }
    result = _apply_intent_filters(state, route_plan)
    actions = [x["action"] for x in result["action_plans"]]
    assert "jira_search_issues" not in actions
    assert "jira_create_issue" in actions
    assert "jira_assign_issue" not in actions
    # deps should be reconciled after pruning removed actions
    for item in result["action_plans"]:
        assert "jira_search_issues" not in item.get("depends_on", [])


def test_file_scoped_create_tickets_plural_drops_jira_search() -> None:
    state = {
        "raw_instruction": (
            "Retrieve all issues related to accuracy from the file with ID e301dffca98d2f1f1848c079 "
            "for the purpose of optimizing query for vector search. This information will be sent "
            "to a Telegram channel and used to create Jira tickets."
        ),
        "instruction": (
            "Current User Request:\nRetrieve all issues related to accuracy from the file with ID "
            "e301dffca98d2f1f1848c079 for the purpose of optimizing query for vector search. "
            "This information will be sent to a Telegram channel and used to create Jira tickets."
        ),
        "file_id": "e301dffca98d2f1f1848c079",
    }
    route_plan = {
        "parallel": True,
        "action_plans": [
            {
                "system": "jira",
                "action": "jira_search_issues",
                "params": {"jql": "assignee = currentUser() ORDER BY updated DESC", "maxResults": 20},
                "risk_level": "low",
                "depends_on": [],
            },
            {
                "system": "telegram",
                "action": "telegram_send_message",
                "params": {"text": "Jira summary is ready."},
                "risk_level": "low",
                "depends_on": ["jira_search_issues"],
            },
            {
                "system": "jira",
                "action": "jira_create_issue",
                "params": {},
                "risk_level": "medium",
                "depends_on": ["jira_search_issues"],
            },
        ],
    }
    result = _apply_intent_filters(state, route_plan)
    actions = [x["action"] for x in result["action_plans"]]
    assert "jira_search_issues" not in actions
    assert "jira_create_issue" in actions
    for item in result["action_plans"]:
        assert "jira_search_issues" not in item.get("depends_on", [])


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
