from aia.workflow.nodes import _normalize_answer_to_intent


def test_answer_normalization_removes_unrequested_jira_commitment() -> None:
    state = {
        "raw_instruction": "Get all issues in the file related to accuracy and send to Telegram channel.",
        "instruction": "Current User Request:\nGet all issues in the file related to accuracy and send to Telegram channel.",
        "file_id": "f1",
    }
    raw_answer = (
        "I will extract accuracy-related issues from the uploaded file, send the summary to Telegram, "
        "and create Jira ticket(s) according to your request."
    )
    normalized = _normalize_answer_to_intent(raw_answer, state)
    assert "Jira" not in normalized
    assert "Telegram" in normalized
    assert "accuracy-related" in normalized


def test_answer_normalization_keeps_jira_when_explicitly_requested() -> None:
    state = {
        "raw_instruction": "Get all issues in the file related to accuracy, send to Telegram, and create Jira ticket.",
        "instruction": "Current User Request:\nGet all issues in the file related to accuracy, send to Telegram, and create Jira ticket.",
        "file_id": "f1",
    }
    raw_answer = (
        "I need the file and Telegram channel details before proceeding."
    )
    normalized = _normalize_answer_to_intent(raw_answer, state)
    assert "Jira" in normalized
    assert "Telegram" in normalized
