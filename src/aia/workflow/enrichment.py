from __future__ import annotations

from typing import Any


_ALLOWED_TASK_TYPES = {
    "general_query",
    "tool_orchestration",
    "summarization",
    "analysis",
    "triage",
}
_TASK_TYPE_ALIASES = {
    "issue_summary": "summarization",
    "summary": "summarization",
    "qa_summary": "summarization",
    "find_and_send_summary": "tool_orchestration",
    "orchestration": "tool_orchestration",
    "tool_execution": "tool_orchestration",
    "question_answering": "general_query",
}
_ALLOWED_OUTPUT_TONES = {"executive", "neutral", "technical"}
_ALLOWED_SYSTEMS = {"jira", "slack", "telegram"}
_ALLOWED_RISK = {"low", "medium", "high"}
_ACTION_ALIASES: dict[str, dict[str, str]] = {
    "jira": {
        "search_issues": "jira_search_issues",
        "jira_search_issues_in_jira": "jira_search_issues",
        "find_issues": "jira_search_issues",
        "find_issues_assigned_to_user": "jira_search_issues",
        "jira_send_summary_to_telegram": "telegram_send_message",
        "get_issue": "jira_get_issue",
        "create_issue": "jira_create_issue",
        "update_issue": "jira_update_issue",
        "transition_issue": "jira_transition_issue",
        "add_comment": "jira_add_comment",
        "assign_issue": "jira_assign_issue",
        "link_issues": "jira_link_issues",
        "bulk_update": "jira_bulk_update",
    },
    "slack": {
        "post_message": "slack_post_message",
        "update_message": "slack_update_message",
        "reply_in_thread": "slack_reply_in_thread",
        "search_messages": "slack_search_messages",
        "get_channel_history": "slack_get_channel_history",
        "create_channel": "slack_create_channel",
        "archive_channel": "slack_archive_channel",
        "invite_users": "slack_invite_users",
        "add_reaction": "slack_add_reaction",
    },
    "telegram": {
        "send_message": "telegram_send_message",
        "send_summary": "telegram_send_message",
        "telegram_send_to_telegram": "telegram_send_message",
        "post_message": "telegram_send_message",
        "get_updates": "telegram_get_updates",
    },
}
_CANONICAL_ACTIONS: dict[str, set[str]] = {
    "jira": {
        "jira_search_issues",
        "jira_get_issue",
        "jira_create_issue",
        "jira_update_issue",
        "jira_transition_issue",
        "jira_add_comment",
        "jira_assign_issue",
        "jira_link_issues",
        "jira_bulk_update",
    },
    "slack": {
        "slack_post_message",
        "slack_update_message",
        "slack_reply_in_thread",
        "slack_search_messages",
        "slack_get_channel_history",
        "slack_create_channel",
        "slack_archive_channel",
        "slack_invite_users",
        "slack_add_reaction",
    },
    "telegram": {
        "telegram_send_message",
        "telegram_get_updates",
    },
}


def _normalize_task_type(value: Any) -> str:
    if isinstance(value, str):
        normalized = value.strip().lower()
        normalized = _TASK_TYPE_ALIASES.get(normalized, normalized)
        if normalized in _ALLOWED_TASK_TYPES:
            return normalized
    return "general_query"


def _normalize_output_tone(value: Any) -> str:
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in _ALLOWED_OUTPUT_TONES:
            return normalized
    return "neutral"


def _normalize_system(action: dict[str, Any]) -> str:
    for key in ("system", "platform"):
        val = action.get(key)
        if isinstance(val, str):
            normalized = val.strip().lower()
            if normalized in _ALLOWED_SYSTEMS:
                return normalized
    action_name = action.get("action")
    if isinstance(action_name, str):
        lowered = action_name.strip().lower()
        if "telegram" in lowered:
            return "telegram"
        if "slack" in lowered:
            return "slack"
        if "jira" in lowered:
            return "jira"
    return "jira"


def _normalize_depends_on(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    if isinstance(value, str):
        cleaned = value.strip()
        return [cleaned] if cleaned else []
    return []


def _normalize_action_name(system: str, value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    if len(normalized) < 3:
        return None
    aliases = _ACTION_ALIASES.get(system, {})
    normalized = aliases.get(normalized, normalized)

    # Cross-system pseudo-action emitted by LLM.
    if normalized == "jira_send_summary_to_telegram":
        return "telegram_send_message"

    # If model returns bare verbs for known systems, prefix canonical namespace.
    if system == "jira" and not normalized.startswith("jira_"):
        prefixed = f"jira_{normalized}"
        normalized = aliases.get(normalized, prefixed)
    elif system == "slack" and not normalized.startswith("slack_"):
        prefixed = f"slack_{normalized}"
        normalized = aliases.get(normalized, prefixed)
    elif system == "telegram" and not normalized.startswith("telegram_"):
        prefixed = f"telegram_{normalized}"
        normalized = aliases.get(normalized, prefixed)

    allowed = _CANONICAL_ACTIONS.get(system, set())
    if normalized in allowed:
        return normalized

    # If still unknown, force a safe default from fixed catalog per system.
    if system == "jira":
        return "jira_search_issues"
    if system == "telegram":
        return "telegram_send_message"
    if system == "slack":
        return "slack_post_message"
    return None


def _normalize_jira_search_params(params: dict[str, Any]) -> dict[str, Any]:
    out = dict(params)
    jql = out.get("jql")
    if not isinstance(jql, str) or not jql.strip():
        out["jql"] = "assignee = currentUser() ORDER BY updated DESC"
    else:
        normalized = jql.strip()
        lower = normalized.lower()
        has_bound = any(token in lower for token in ("assignee", "project", "filter", "issuekey", "id in"))
        if not has_bound:
            normalized = f"({normalized}) AND assignee = currentUser()"
        if "order by" not in lower:
            normalized = f"{normalized} ORDER BY updated DESC"
        out["jql"] = normalized

    max_results = out.get("maxResults")
    if not isinstance(max_results, int) or max_results <= 0:
        out["maxResults"] = 20
    else:
        out["maxResults"] = min(max_results, 100)
    return out


def _normalize_params(system: str, action: str, params: dict[str, Any]) -> dict[str, Any]:
    out = dict(params)
    if system == "jira" and action == "jira_search_issues":
        return _normalize_jira_search_params(out)
    return out


def _normalize_action(action: Any) -> dict[str, Any] | None:
    if not isinstance(action, dict):
        return None

    system = _normalize_system(action)
    name = _normalize_action_name(system, action.get("action"))
    if not name:
        return None
    if name.startswith("telegram_"):
        system = "telegram"
    elif name.startswith("jira_"):
        system = "jira"
    elif name.startswith("slack_"):
        system = "slack"

    params = action.get("params")
    if not isinstance(params, dict):
        params = {}
    params = _normalize_params(system, name, params)

    risk = action.get("risk_level")
    risk_normalized = risk.strip().lower() if isinstance(risk, str) else "low"
    if risk_normalized not in _ALLOWED_RISK:
        risk_normalized = "low"

    return {
        "system": system,
        "action": name.strip(),
        "params": params,
        "risk_level": risk_normalized,
        "depends_on": _normalize_depends_on(action.get("depends_on")),
    }


def normalize_enriched_task_raw(raw: dict[str, Any]) -> dict[str, Any]:
    action_plans = raw.get("action_plans")
    normalized_plans: list[dict[str, Any]] = []
    if isinstance(action_plans, list):
        for item in action_plans:
            normalized = _normalize_action(item)
            if normalized:
                normalized_plans.append(normalized)

    requires_rag = raw.get("requires_rag")
    if not isinstance(requires_rag, bool):
        requires_rag = False

    rag_seed = raw.get("rag_query_seed")
    if not isinstance(rag_seed, str):
        rag_seed = ""
    rag_seed = rag_seed[:1000]

    return {
        "task_type": _normalize_task_type(raw.get("task_type")),
        "requires_rag": requires_rag,
        "output_tone": _normalize_output_tone(raw.get("output_tone")),
        "rag_query_seed": rag_seed,
        "action_plans": normalized_plans,
    }


def normalize_route_plan_raw(raw: dict[str, Any], fallback_action_plans: list[dict[str, Any]]) -> dict[str, Any]:
    action_plans = raw.get("action_plans")
    source = action_plans if isinstance(action_plans, list) else fallback_action_plans
    normalized_plans: list[dict[str, Any]] = []
    for item in source:
        normalized = _normalize_action(item)
        if normalized:
            normalized_plans.append(normalized)

    parallel = raw.get("parallel")
    if not isinstance(parallel, bool):
        parallel = True

    return {
        "parallel": parallel,
        "action_plans": normalized_plans,
    }
