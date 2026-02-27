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
