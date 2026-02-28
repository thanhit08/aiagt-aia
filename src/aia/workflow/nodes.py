import json
import os
import re
from dataclasses import dataclass
from uuid import uuid4

from aia.models.contracts import ActionResult, EnrichedTask, FinalResponse, RoutePlan
from aia.services.protocols import JiraClient, LLMClient, SlackClient, TelegramClient, VectorStore
from aia.workflow.enrichment import normalize_enriched_task_raw, normalize_route_plan_raw
from aia.workflow.prompts import load_prompt, render_template
from aia.workflow.state import WorkflowState


@dataclass
class NodeDeps:
    llm: LLMClient
    vector_store: VectorStore
    slack: SlackClient
    jira: JiraClient
    telegram: TelegramClient


def intake_node(state: WorkflowState) -> WorkflowState:
    return {"trace_id": state.get("trace_id", str(uuid4())), "errors": state.get("errors", [])}


def rag_check_node(state: WorkflowState) -> WorkflowState:
    # New workflow rule: only file-linked requests trigger RAG path.
    return {"rag_required": bool(state.get("file_id"))}


def rag_query_enrichment_node(state: WorkflowState, deps: NodeDeps) -> WorkflowState:
    if not state.get("rag_required", False):
        return {"rag_query_spec": {"enabled": False, "query_text": "", "collections": []}}

    sys_prompt = load_prompt("rag-query-builder.system.md")
    user_prompt = json.dumps(
        {
            "instruction": _current_request_text(state),
            "file_id": state.get("file_id"),
            "goal": "Optimize query for vector search over uploaded file content. Do not plan actions.",
        }
    )
    query_spec = deps.llm.complete_json(system_prompt=sys_prompt, user_prompt=user_prompt)
    if not isinstance(query_spec, dict):
        query_spec = {}
    collections = query_spec.get("collections", [])
    if not isinstance(collections, list):
        collections = []
    if "uploaded_files" not in collections:
        collections = ["uploaded_files"] + collections
    query_text = query_spec.get("query_text")
    if not isinstance(query_text, str) or not query_text.strip():
        query_text = _current_request_text(state)
    top_k = query_spec.get("top_k")
    min_score = query_spec.get("min_score")
    return {
        "rag_query_spec": {
            "enabled": True,
            "collections": collections,
            "query_text": query_text,
            "top_k": int(top_k) if isinstance(top_k, int) else 20,
            "min_score": float(min_score) if isinstance(min_score, (int, float)) else 0.0,
        }
    }


def rag_context_node(state: WorkflowState, deps: NodeDeps) -> WorkflowState:
    if not state.get("rag_required", False):
        return {"rag_context": {"enabled": False, "hits": []}, "rag_compiled_context": ""}

    query_spec = state.get("rag_query_spec", {})
    if not isinstance(query_spec, dict):
        query_spec = {}
    collections = query_spec.get("collections", ["taxonomy", "rules", "examples"])
    if not isinstance(collections, list):
        collections = ["uploaded_files"]
    if "uploaded_files" not in collections:
        collections = ["uploaded_files"] + collections
    hits = deps.vector_store.search(
        collections=collections,
        query_text=query_spec.get("query_text", _current_request_text(state)),
        top_k=int(query_spec.get("top_k", 20)),
        min_score=float(query_spec.get("min_score", 0.0)),
        file_id=state.get("file_id"),
    )
    compiled = _compile_rag_hits(hits)
    return {"rag_context": {"enabled": True, "query_spec": query_spec, "hits": hits}, "rag_compiled_context": compiled}


def route_node(state: WorkflowState, deps: NodeDeps) -> WorkflowState:
    # New workflow: route step now performs old enrichment responsibilities.
    sys_prompt = load_prompt("enrichment.system.md")
    user_prompt = render_template(load_prompt("enrichment.user.md"), instruction=_current_request_text(state))
    raw = deps.llm.complete_json(system_prompt=sys_prompt, user_prompt=user_prompt)
    if not isinstance(raw, dict):
        raw = {}
    normalized = normalize_enriched_task_raw(raw)
    try:
        enriched = EnrichedTask.model_validate(normalized).model_dump()
    except Exception:
        enriched = EnrichedTask(
            task_type="general_query",
            requires_rag=bool(state.get("rag_required", False)),
            output_tone="neutral",
            rag_query_seed="",
            action_plans=[],
        ).model_dump()
    # Route must not decide RAG here; preserve upstream rag_check decision.
    enriched["requires_rag"] = bool(state.get("rag_required", False))
    route_raw = normalize_route_plan_raw({}, enriched.get("action_plans", []))
    try:
        route_plan = RoutePlan.model_validate(route_raw).model_dump()
        route_plan = _apply_intent_filters(state, route_plan)
        return {"enriched_task": enriched, "route_plan": route_plan}
    except Exception as exc:
        errors = list(state.get("errors", []))
        errors.append(f"route_plan_validation_fallback: {exc}")
        return {"enriched_task": enriched, "route_plan": {"parallel": True, "action_plans": []}, "errors": errors}


def execute_actions_node(state: WorkflowState, deps: NodeDeps) -> WorkflowState:
    results: list[dict] = []
    errors = list(state.get("errors", []))
    action_plans = state.get("route_plan", {}).get("action_plans", [])
    action_status: dict[str, str] = {}
    action_data: dict[str, dict] = {}

    for item in action_plans:
        system = item.get("system")
        action = item.get("action")
        params = item.get("params", {}) if isinstance(item.get("params"), dict) else {}
        depends_on = item.get("depends_on", []) if isinstance(item.get("depends_on"), list) else []

        blocked_dep = next((dep for dep in depends_on if action_status.get(dep) != "success"), None)
        if blocked_dep:
            skipped = ActionResult(
                system=system or "jira",
                action=action or "unknown_action",
                status="skipped",
                error=f"Skipped because dependency '{blocked_dep}' did not succeed.",
            ).model_dump()
            results.append(skipped)
            action_status[action or "unknown_action"] = "skipped"
            continue

        try:
            params = _enrich_action_params_with_context(
                deps=deps,
                state=state,
                action=action or "",
                system=system or "",
                params=params,
            )
            params, precheck_error = _prepare_action_params(
                state=state,
                action=action or "",
                system=system or "",
                params=params,
                action_data=action_data,
            )
            if precheck_error:
                failed = ActionResult(
                    system=system or "jira",
                    action=action or "unknown_action",
                    status="failed",
                    error=precheck_error,
                ).model_dump()
                results.append(failed)
                action_status[action or "unknown_action"] = "failed"
                errors.append(f"{failed['system']}:{failed['action']} failed: {precheck_error}")
                continue

            if system == "telegram" and action == "telegram_send_message":
                text = params.get("text") if isinstance(params, dict) else None
                if not isinstance(text, str) or not text.strip():
                    params = dict(params) if isinstance(params, dict) else {}
                    params["text"] = _compose_telegram_text(state)

            if system == "jira":
                result = deps.jira.execute_action(action=action, params=params)
            elif system == "slack":
                result = {
                    "system": "slack",
                    "action": action or "slack_unknown",
                    "status": "failed",
                    "error": "Slack integration is not supported yet in this environment. Please use Telegram actions (telegram_send_message).",
                }
            elif system == "telegram":
                result = deps.telegram.execute_action(action=action, params=params)
            else:
                result = {
                    "system": system or "unknown",
                    "action": action or "unknown",
                    "status": "failed",
                    "error": f"Unsupported system: {system}",
                }
            action_result = ActionResult.model_validate(result).model_dump()
            if action_result.get("status") == "failed" and action_result.get("error"):
                errors.append(f"{action_result['system']}:{action_result['action']} failed: {action_result['error']}")
            key = action or "unknown_action"
            action_status[key] = action_result.get("status", "failed")
            if action_result.get("status") == "success":
                data_payload = action_result.get("data")
                if isinstance(data_payload, dict):
                    action_data[key] = data_payload
        except Exception as exc:
            action_result = ActionResult(
                system=system or "jira",
                action=action or "unknown_action",
                status="failed",
                error=str(exc),
            ).model_dump()
            errors.append(f"{action_result['system']}:{action_result['action']} failed: {exc}")
            action_status[action or "unknown_action"] = "failed"

        results.append(action_result)

    return {"action_results": results, "errors": errors}


def aggregate_node(state: WorkflowState) -> WorkflowState:
    answer = state.get("answer")
    if not isinstance(answer, str) or not answer.strip():
        answer = _build_final_answer(state)
    final = FinalResponse(
        request_id=state["request_id"],
        answer=answer,
        trace_id=state["trace_id"],
        action_results=state.get("action_results", []),
        errors=state.get("errors", []),
    ).model_dump()
    return {"final_response": final}


def _apply_intent_filters(state: WorkflowState, route_plan: dict) -> dict:
    action_plans = list(route_plan.get("action_plans", []))
    action_plans = _apply_action_policy(state, action_plans)

    route_plan["action_plans"] = action_plans
    return route_plan


def _apply_action_policy(state: WorkflowState, action_plans: list[dict]) -> list[dict]:
    filtered = list(action_plans)
    if _is_file_delivery_without_explicit_jira(state):
        filtered = [a for a in filtered if a.get("system") != "jira"]
        # For file -> telegram flows, keep telegram action even if planner over-produces systems.
        telegram_only = [a for a in filtered if a.get("system") == "telegram"]
        if telegram_only:
            filtered = telegram_only
    if _is_file_to_jira_create_intent(state):
        filtered = _drop_unneeded_jira_search_for_create_intent(state, filtered)
    filtered = _reconcile_action_dependencies(filtered)
    return filtered


def _is_file_delivery_without_explicit_jira(state: WorkflowState) -> bool:
    instruction = _current_request_text(state).lower()
    file_scoped_phrases = ("in the file", "from the file", "uploaded file", "this file", "file related")
    asks_file_scope = any(p in instruction for p in file_scoped_phrases)
    asks_telegram = "telegram" in instruction
    asks_for_jira = "jira" in instruction
    return asks_file_scope and asks_telegram and not asks_for_jira


def _is_file_to_jira_create_intent(state: WorkflowState) -> bool:
    instruction = _current_request_text(state).lower()
    file_scoped_phrases = ("in the file", "from the file", "uploaded file", "this file", "file related")
    create_phrases = (
        "add ticket",
        "add tickets",
        "create ticket",
        "create tickets",
        "create issue",
        "create issues",
        "open ticket",
        "open tickets",
        "file ticket",
        "file tickets",
        "raise ticket",
        "raise tickets",
        "log ticket",
        "log tickets",
    )
    asks_file_scope = any(p in instruction for p in file_scoped_phrases)
    asks_create_phrase = any(p in instruction for p in create_phrases)
    asks_create_pattern = bool(
        re.search(
            r"\b(create|add|open|file|raise|log)\b[\w\s]{0,30}\b(ticket|tickets|issue|issues|bug|bugs)\b",
            instruction,
        )
    )
    asks_create = asks_create_phrase or asks_create_pattern
    asks_jira = "jira" in instruction
    return asks_file_scope and asks_create and asks_jira


def _drop_unneeded_jira_search_for_create_intent(state: WorkflowState, action_plans: list[dict]) -> list[dict]:
    instruction = _current_request_text(state).lower()
    # Keep jira search only when user explicitly asks to search/list/find in Jira.
    explicit_search_markers = (
        "search jira",
        "search in jira",
        "find in jira",
        "list jira",
        "list issues in jira",
        "issues assigned to me in jira",
        "find issues assigned",
        "search issues assigned",
    )
    explicit_assign_markers = ("assign to", "assign ticket", "assign issue")
    asks_jira = "jira" in instruction
    asks_search_verb = any(v in instruction for v in ("search", "find", "list", "query", "look up"))
    asks_jira_source = any(s in instruction for s in ("in jira", "from jira", "on jira", "jira issues", "issues in jira"))
    keep_search = any(marker in instruction for marker in explicit_search_markers) or (
        asks_jira and asks_search_verb and asks_jira_source
    )
    keep_assign = any(marker in instruction for marker in explicit_assign_markers)
    filtered = list(action_plans)
    if not keep_search:
        filtered = [
            a
            for a in filtered
            if not (a.get("system") == "jira" and a.get("action") == "jira_search_issues")
        ]
    if not keep_assign:
        filtered = [
            a
            for a in filtered
            if not (a.get("system") == "jira" and a.get("action") == "jira_assign_issue")
        ]
    return filtered


def _reconcile_action_dependencies(action_plans: list[dict]) -> list[dict]:
    names = {str(a.get("action")) for a in action_plans if a.get("action")}
    out: list[dict] = []
    for action in action_plans:
        copied = dict(action)
        deps = copied.get("depends_on", [])
        if isinstance(deps, list):
            copied["depends_on"] = [d for d in deps if isinstance(d, str) and d in names]
        else:
            copied["depends_on"] = []
        out.append(copied)
    return out


def _current_request_text(state: WorkflowState) -> str:
    raw = state.get("raw_instruction")
    if isinstance(raw, str) and raw.strip():
        return raw
    return _extract_current_request_text(str(state.get("instruction", "")))


def _extract_current_request_text(instruction: str) -> str:
    marker = "Current User Request:\n"
    if not instruction.startswith(marker):
        return instruction
    body = instruction[len(marker):]
    split = body.split("\n\n", 1)
    return split[0]


def _compose_telegram_text(state: WorkflowState) -> str:
    rag = state.get("rag_context", {})
    hits = rag.get("hits", []) if isinstance(rag, dict) else []
    if isinstance(hits, list) and hits:
        request_text = _extract_current_request_text(str(state.get("instruction", ""))).lower()
        keyword = "accuracy" if "accuracy" in request_text else None
        lines: list[str] = []
        for hit in hits:
            payload = hit.get("payload", {}) if isinstance(hit, dict) else {}
            text = payload.get("text") if isinstance(payload, dict) else None
            if not isinstance(text, str):
                continue
            clean = text.strip()
            if not clean:
                continue
            if keyword and keyword not in clean.lower():
                continue
            lines.append(clean)
            if len(lines) >= 10:
                break
        if not lines:
            # fallback to first hit texts if keyword filter produced nothing
            for hit in hits[:10]:
                payload = hit.get("payload", {}) if isinstance(hit, dict) else {}
                text = payload.get("text") if isinstance(payload, dict) else None
                if isinstance(text, str) and text.strip():
                    lines.append(text.strip())
        if lines:
            return "Issues from uploaded file:\n- " + "\n- ".join(lines[:10])
    return str(state.get("answer", "Request processed."))


def _enrich_action_params_with_context(
    *,
    deps: NodeDeps,
    state: WorkflowState,
    action: str,
    system: str,
    params: dict,
) -> dict:
    base = dict(params)
    if system == "telegram" and action == "telegram_send_message":
        base = _sanitize_telegram_chat_params(state, base)
    sys_prompt = (
        "You enrich tool action parameters for an orchestrator. "
        "Return JSON object only with params keys/values. Do not include explanations."
    )
    user_prompt = json.dumps(
        {
            "system": system,
            "action": action,
            "current_request": _current_request_text(state),
            "rag_context_text": state.get("rag_compiled_context", ""),
            "existing_params": base,
        },
        ensure_ascii=False,
    )
    try:
        raw = deps.llm.complete_json(system_prompt=sys_prompt, user_prompt=user_prompt)
        if isinstance(raw, dict):
            merged = dict(base)
            for k, v in raw.items():
                merged[k] = v
            if system == "telegram" and action == "telegram_send_message":
                merged = _sanitize_telegram_chat_params(state, merged)
            return merged
    except Exception:
        return base
    return base


def _compile_rag_hits(hits: list[dict]) -> str:
    lines: list[str] = []
    seen: set[str] = set()
    for hit in hits[:50]:
        payload = hit.get("payload", {}) if isinstance(hit, dict) else {}
        text = payload.get("text") if isinstance(payload, dict) else None
        if not isinstance(text, str):
            continue
        clean = text.strip()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        lines.append(clean)
        if len(lines) >= 20:
            break
    return "\n".join(lines)


def _build_final_answer(state: WorkflowState) -> str:
    request = _current_request_text(state)
    results = state.get("action_results", [])
    success = [r for r in results if isinstance(r, dict) and r.get("status") == "success"]
    failed = [r for r in results if isinstance(r, dict) and r.get("status") == "failed"]
    skipped = [r for r in results if isinstance(r, dict) and r.get("status") == "skipped"]
    rag = state.get("rag_context", {})
    hit_count = len(rag.get("hits", [])) if isinstance(rag, dict) and isinstance(rag.get("hits"), list) else 0
    return (
        f"Processed request: {request}\n"
        f"RAG hits: {hit_count}\n"
        f"Actions: {len(success)} succeeded, {len(failed)} failed, {len(skipped)} skipped."
    )


def _prepare_action_params(
    *,
    state: WorkflowState,
    action: str,
    system: str,
    params: dict,
    action_data: dict[str, dict],
) -> tuple[dict, str | None]:
    out = dict(params)
    if system == "telegram" and action == "telegram_send_message":
        out = _sanitize_telegram_chat_params(state, out)
    if system == "jira" and action == "jira_create_issue":
        return _prepare_jira_create_issue_params(state, out)
    if system == "jira" and action == "jira_assign_issue":
        return _prepare_jira_assign_issue_params(out, action_data)
    return out, None


def _prepare_jira_create_issue_params(state: WorkflowState, params: dict) -> tuple[dict, str | None]:
    # If user already provides full Jira payload, keep it.
    if isinstance(params.get("fields"), dict):
        fields = dict(params["fields"])
    else:
        fields = {}

    scope_field, scope_key = _resolve_jira_scope_field_and_key()
    issue_type = os.getenv("JIRA_DEFAULT_ISSUE_TYPE", "Bug").strip() or "Bug"
    summary, description = _derive_issue_content_from_state(state)

    if "project" not in fields and "space" not in fields:
        if not scope_key:
            return (
                params,
                "jira_create_issue requires scope key. Set JIRA_DEFAULT_SPACE_KEY (preferred) or JIRA_DEFAULT_PROJECT_KEY (legacy), or provide fields.space/fields.project.",
            )
        fields[scope_field] = {"key": scope_key}
    if "issuetype" not in fields:
        fields["issuetype"] = {"name": issue_type}
    if "summary" not in fields:
        fields["summary"] = summary
    if "description" not in fields:
        fields["description"] = _to_jira_adf(description)

    return {"fields": fields}, None


def _prepare_jira_assign_issue_params(params: dict, action_data: dict[str, dict]) -> tuple[dict, str | None]:
    out = dict(params)
    if not out.get("issue_key"):
        created = action_data.get("jira_create_issue", {})
        if isinstance(created, dict):
            issue_key = created.get("key")
            if isinstance(issue_key, str) and issue_key.strip():
                out["issue_key"] = issue_key.strip()
    if not out.get("issue_key"):
        return out, "jira_assign_issue requires issue_key; could not derive from previous create action."
    if "accountId" not in out:
        account_id = os.getenv("JIRA_DEFAULT_ASSIGNEE_ACCOUNT_ID", "").strip()
        if account_id:
            out["accountId"] = account_id
    if "accountId" not in out:
        return out, "jira_assign_issue requires accountId or JIRA_DEFAULT_ASSIGNEE_ACCOUNT_ID."
    return out, None


def _derive_issue_content_from_state(state: WorkflowState) -> tuple[str, str]:
    request_text = _current_request_text(state).strip()
    rag = state.get("rag_context", {})
    hits = rag.get("hits", []) if isinstance(rag, dict) else []
    extracted: list[str] = []
    if isinstance(hits, list):
        for hit in hits[:5]:
            payload = hit.get("payload", {}) if isinstance(hit, dict) else {}
            text = payload.get("text") if isinstance(payload, dict) else None
            if isinstance(text, str) and text.strip():
                extracted.append(text.strip())
    if extracted:
        summary = extracted[0][:120]
        return summary, "Source lines from uploaded file:\n- " + "\n- ".join(extracted)
    return request_text[:120] or "Issue from uploaded file", request_text or "Issue extracted from user request."


def _to_jira_adf(text: str) -> dict:
    return {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": text}],
            }
        ],
    }


def _resolve_jira_project_key() -> str:
    key = (
        os.getenv("JIRA_DEFAULT_PROJECT_KEY", "").strip()
        or os.getenv("JIRA_PROJECT_KEY", "").strip()
        or os.getenv("PROJECT_KEY", "").strip()
    )
    # Common placeholder values copied from examples. These are not real Jira project keys.
    if key.upper() in {"PROJ", "PROJECT_KEY", "YOUR_PROJECT_KEY"}:
        return ""
    return key


def _resolve_jira_space_key() -> str:
    key = (
        os.getenv("JIRA_DEFAULT_SPACE_KEY", "").strip()
        or os.getenv("JIRA_SPACE_KEY", "").strip()
        or os.getenv("SPACE_KEY", "").strip()
    )
    # Common placeholder values copied from examples. These are not real Jira space keys.
    if key.upper() in {"SPACE", "SPACE_KEY", "YOUR_SPACE_KEY"}:
        return ""
    return key


def _resolve_jira_scope_field_and_key() -> tuple[str, str]:
    mode = os.getenv("JIRA_SCOPE_MODE", "auto").strip().lower()
    space_key = _resolve_jira_space_key()
    project_key = _resolve_jira_project_key()
    if mode == "space":
        return "space", (space_key or project_key)
    if mode == "project":
        return "project", (project_key or space_key)
    # auto mode: prefer space when available, then fallback to project.
    if space_key:
        return "space", space_key
    return "project", project_key


def _sanitize_telegram_chat_params(state: WorkflowState, params: dict) -> dict:
    out = dict(params)
    trusted = state.get("telegram_chat_id")
    if isinstance(trusted, str) and trusted.strip():
        out["chat_id"] = trusted.strip()
        return out
    # Never trust model/planner-generated chat_id by default. Let Telegram client
    # fall back to TELEGRAM_DEFAULT_CHAT_ID from environment configuration.
    out.pop("chat_id", None)
    return out
