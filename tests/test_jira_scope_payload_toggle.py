from aia.services.real_clients import _toggle_jira_issue_scope_payload


def test_toggle_project_to_space() -> None:
    payload = {"fields": {"project": {"key": "AIA"}, "summary": "x"}}
    out = _toggle_jira_issue_scope_payload(payload)
    assert out is not None
    assert "space" in out["fields"]
    assert "project" not in out["fields"]
    assert out["fields"]["space"]["key"] == "AIA"


def test_toggle_space_to_project() -> None:
    payload = {"fields": {"space": {"key": "AIA"}, "summary": "x"}}
    out = _toggle_jira_issue_scope_payload(payload)
    assert out is not None
    assert "project" in out["fields"]
    assert "space" not in out["fields"]
    assert out["fields"]["project"]["key"] == "AIA"
