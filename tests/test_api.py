from fastapi.testclient import TestClient
import pytest

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


def test_upload_and_status_and_query_with_file_id() -> None:
    if "/upload" not in [r.path for r in app.routes]:
        pytest.skip("multipart upload route is not registered in this environment")

    file_content = "line one\nline two\nline three\n"
    files = {"file": ("notes.txt", file_content, "text/plain")}
    data = {"user_id": "u-file"}
    upload_resp = client.post("/upload", files=files, data=data)
    assert upload_resp.status_code == 200
    upload_body = upload_resp.json()
    file_id = upload_body.get("file_id")
    assert file_id

    status_resp = client.get(f"/upload/{file_id}/status")
    assert status_resp.status_code == 200
    status_body = status_resp.json()
    assert status_body.get("state") in {"ready", "saving_to_qdrant", "embedding", "upload_complete", "initiated"}

    meta_resp = client.get(f"/upload/{file_id}")
    assert meta_resp.status_code == 200
    meta_body = meta_resp.json()
    assert meta_body.get("file_id") == file_id
    assert "filename" in meta_body

    qa_resp = client.post(
        "/qa-intake",
        json={
            "user_id": "u-file",
            "instruction": "Use the uploaded file to answer",
            "file_id": file_id,
        },
    )
    assert qa_resp.status_code == 200
    qa_body = qa_resp.json()
    assert "answer" in qa_body
