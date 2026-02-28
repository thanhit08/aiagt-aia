from aia.workflow.nodes import _prepare_jira_create_issue_params


def test_jira_create_issue_accepts_project_key_alias(monkeypatch) -> None:
    monkeypatch.delenv("JIRA_DEFAULT_SPACE_KEY", raising=False)
    monkeypatch.delenv("JIRA_SPACE_KEY", raising=False)
    monkeypatch.delenv("SPACE_KEY", raising=False)
    monkeypatch.setenv("JIRA_SCOPE_MODE", "project")
    monkeypatch.delenv("JIRA_DEFAULT_PROJECT_KEY", raising=False)
    monkeypatch.delenv("JIRA_PROJECT_KEY", raising=False)
    monkeypatch.setenv("PROJECT_KEY", "AIA")
    monkeypatch.setenv("JIRA_DEFAULT_ISSUE_TYPE", "Bug")

    payload, err = _prepare_jira_create_issue_params(
        {"instruction": "Current User Request:\nCreate Jira ticket from file issue"},
        {},
    )
    assert err is None
    assert payload["fields"]["project"]["key"] == "AIA"


def test_jira_create_issue_rejects_placeholder_project_key(monkeypatch) -> None:
    monkeypatch.delenv("JIRA_DEFAULT_SPACE_KEY", raising=False)
    monkeypatch.delenv("JIRA_SPACE_KEY", raising=False)
    monkeypatch.delenv("SPACE_KEY", raising=False)
    monkeypatch.setenv("JIRA_SCOPE_MODE", "project")
    monkeypatch.delenv("JIRA_DEFAULT_PROJECT_KEY", raising=False)
    monkeypatch.delenv("JIRA_PROJECT_KEY", raising=False)
    monkeypatch.setenv("PROJECT_KEY", "PROJ")

    payload, err = _prepare_jira_create_issue_params(
        {"instruction": "Current User Request:\nCreate Jira ticket"},
        {},
    )
    assert payload == {}
    assert err is not None
    assert "scope key" in err


def test_jira_create_issue_prefers_space_key_when_available(monkeypatch) -> None:
    monkeypatch.setenv("JIRA_SCOPE_MODE", "auto")
    monkeypatch.setenv("JIRA_DEFAULT_SPACE_KEY", "AIASPACE")
    monkeypatch.setenv("JIRA_DEFAULT_PROJECT_KEY", "AIA")

    payload, err = _prepare_jira_create_issue_params(
        {"instruction": "Current User Request:\nCreate Jira ticket from file issue"},
        {},
    )
    assert err is None
    assert payload["fields"]["space"]["key"] == "AIASPACE"
