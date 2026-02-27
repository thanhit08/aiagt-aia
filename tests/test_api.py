from fastapi.testclient import TestClient

from aia.api.main import app

client = TestClient(app)


def test_health() -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_qa_intake_csv() -> None:
    payload = {
        "user_id": "u1",
        "instruction": "Find accuracy issues and route.",
        "issues": [
            {
                "issue_id": "1",
                "title": "Calc mismatch",
                "description": "Wrong numeric output",
                "steps": "Run scenario",
                "severity": "critical",
            }
        ],
    }
    resp = client.post("/qa-intake", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert "request_id" in body
    assert "trace_id" in body
    assert "answer" in body
    assert "action_results" in body


def test_slack_request_returns_not_supported_message() -> None:
    payload = {
        "user_id": "u1",
        "instruction": "Post this update to Slack",
        "issues": [],
    }
    resp = client.post("/qa-intake", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    slack_results = [r for r in body.get("action_results", []) if r.get("system") == "slack"]
    if slack_results:
        assert slack_results[0]["status"] == "failed"
        assert "Telegram" in (slack_results[0].get("error") or "")


def test_get_conversation() -> None:
    create_payload = {
        "user_id": "u-conv",
        "instruction": "Create a conversation record.",
        "issues": [],
    }
    create_resp = client.post("/qa-intake", json=create_payload)
    assert create_resp.status_code == 200
    conversation_id = create_resp.json().get("conversation_id")
    assert conversation_id

    fetch_resp = client.get(f"/conversation/{conversation_id}")
    assert fetch_resp.status_code == 200
    data = fetch_resp.json()
    assert data.get("conversation_id") == conversation_id
    assert isinstance(data.get("messages"), list)
