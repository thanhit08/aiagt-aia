import json
import os
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


def enrichment_node(state: WorkflowState, deps: NodeDeps) -> WorkflowState:
    sys_prompt = load_prompt("enrichment.system.md")
    current_request = str(state.get("raw_instruction") or _extract_current_request_text(str(state["instruction"])))
    user_prompt = render_template(load_prompt("enrichment.user.md"), instruction=current_request)
    raw = deps.llm.complete_json(system_prompt=sys_prompt, user_prompt=user_prompt)
    if not isinstance(raw, dict):
        raw = {}
    normalized = normalize_enriched_task_raw(raw)
    if state.get("file_id") or _should_force_rag(state):
        normalized["requires_rag"] = True
    try:
        enriched = EnrichedTask.model_validate(normalized).model_dump()
        enriched["action_plans"] = _apply_action_policy(state, enriched.get("action_plans", []))
        return {"enriched_task": enriched}
    except Exception as exc:
        fallback = EnrichedTask(
            task_type="general_query",
            requires_rag=False,
            output_tone="neutral",
            rag_query_seed="",
            action_plans=[],
        ).model_dump()
        errors = list(state.get("errors", []))
        errors.append(f"enrichment_validation_fallback: {exc}")
        return {"enriched_task": fallback, "errors": errors}


def rag_context_node(state: WorkflowState, deps: NodeDeps) -> WorkflowState:
    if not state["enriched_task"].get("requires_rag", False):
        return {"rag_context": {"enabled": False, "hits": []}}

    sys_prompt = load_prompt("rag-query-builder.system.md")
    user_prompt = json.dumps(
        {
            "enriched_task": state["enriched_task"],
        }
    )
    query_spec = deps.llm.complete_json(system_prompt=sys_prompt, user_prompt=user_prompt)
    if not isinstance(query_spec, dict):
        query_spec = {}
    collections = query_spec.get("collections", ["taxonomy", "rules", "examples"])
    if state.get("file_id") and "uploaded_files" not in collections:
        collections = ["uploaded_files"] + collections
    hits = deps.vector_store.search(
        collections=collections,
        query_text=query_spec.get("query_text", state.get("raw_instruction") or _extract_current_request_text(str(state["instruction"]))),
        top_k=int(query_spec.get("top_k", 5)),
        min_score=float(query_spec.get("min_score", 0.72)),
        file_id=state.get("file_id"),
    )
    return {"rag_context": {"enabled": True, "query_spec": query_spec, "hits": hits}}


def answer_node(state: WorkflowState, deps: NodeDeps) -> WorkflowState:
    sys_prompt = (
        "You are AIA. Provide a concise, useful answer to the user's request. "
        "If actions are requested, summarize what will be done."
    )
    user_prompt = json.dumps(
        {
            "instruction": state.get("raw_instruction") or _extract_current_request_text(str(state["instruction"])),
            "conversation_context": state["instruction"],
            "rag_context": state.get("rag_context", {}),
            "enriched_task": state["enriched_task"],
        },
        ensure_ascii=False,
    )
    answer = deps.llm.complete_text(system_prompt=sys_prompt, user_prompt=user_prompt).strip()
    if not answer:
        answer = "Request processed."
    answer = _normalize_answer_to_intent(answer, state)
    return {"answer": answer}


def route_node(state: WorkflowState, deps: NodeDeps) -> WorkflowState:
    sys_prompt = load_prompt("orchestrator-routing.system.md")
    user_prompt = render_template(
        load_prompt("orchestrator-routing.user.md"),
        enriched_task_json=json.dumps(state["enriched_task"], ensure_ascii=False),
        accuracy_context=json.dumps(state.get("rag_context", {}), ensure_ascii=False),
        answer_text=state.get("answer", ""),
    )
    raw = deps.llm.complete_json(system_prompt=sys_prompt, user_prompt=user_prompt)
    if not isinstance(raw, dict):
        raw = {}
    route_raw = normalize_route_plan_raw(raw, state.get("enriched_task", {}).get("action_plans", []))
    try:
        route_plan = RoutePlan.model_validate(route_raw).model_dump()
        route_plan = _apply_intent_filters(state, route_plan)
        return {"route_plan": route_plan}
    except Exception as exc:
        errors = list(state.get("errors", []))
        errors.append(f"route_plan_validation_fallback: {exc}")
        return {"route_plan": {"parallel": True, "action_plans": []}, "errors": errors}


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
    final = FinalResponse(
        request_id=state["request_id"],
        answer=state.get("answer", "Request processed."),
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


def _should_force_rag(state: WorkflowState) -> bool:
    file_id = state.get("file_id")
    if not file_id:
        return False
    instruction = _current_request_text(state).lower()
    # If a file is attached and request appears file/content-centric, require retrieval.
    file_scoped_phrases = ("in the file", "from the file", "uploaded file", "this file", "file related")
    content_scoped_phrases = ("accuracy", "issues", "find in", "retrieve", "summarize")
    return any(p in instruction for p in file_scoped_phrases) or any(p in instruction for p in content_scoped_phrases)


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
    create_phrases = ("add ticket", "create ticket", "create issue", "open ticket", "file ticket")
    asks_file_scope = any(p in instruction for p in file_scoped_phrases)
    asks_create = any(p in instruction for p in create_phrases)
    asks_jira = "jira" in instruction
    return asks_file_scope and asks_create and asks_jira


def _drop_unneeded_jira_search_for_create_intent(state: WorkflowState, action_plans: list[dict]) -> list[dict]:
    instruction = _current_request_text(state).lower()
    # Keep jira search only when user explicitly asks to search/list/find in Jira.
    explicit_search_markers = ("search jira", "find in jira", "list jira")
    explicit_assign_markers = ("assign to", "assign ticket", "assign issue")
    keep_search = any(marker in instruction for marker in explicit_search_markers)
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


def _looks_like_missing_input_prompt(answer: str, state: WorkflowState) -> bool:
    lower = answer.lower()
    asks_for_file = "provide the file" in lower or "please provide" in lower and "file" in lower
    asks_for_channel = "telegram channel" in lower and "provide" in lower
    has_file = bool(state.get("file_id"))
    asked_telegram = "telegram" in _current_request_text(state).lower()
    return has_file and asked_telegram and (asks_for_file or asks_for_channel)


def _normalize_answer_to_intent(answer: str, state: WorkflowState) -> str:
    req = _current_request_text(state).lower()
    asks_jira = "jira" in req
    asks_telegram = "telegram" in req
    asks_file = any(p in req for p in ("in the file", "from the file", "uploaded file", "this file", "file related"))
    asks_accuracy = "accuracy" in req

    lower_ans = answer.lower()
    if _looks_like_missing_input_prompt(answer, state):
        if asks_file and asks_telegram and not asks_jira:
            return "I will extract accuracy-related issues from the uploaded file and send the summary to Telegram."
        if asks_file and asks_telegram and asks_jira:
            return (
                "I will extract accuracy-related issues from the uploaded file, send the summary to Telegram, "
                "and create Jira ticket(s) as requested."
            )

    # Prevent accidental Jira-hallucinated commitments when user did not ask Jira.
    if not asks_jira and ("jira" in lower_ans or "ticket" in lower_ans):
        if asks_file and asks_telegram:
            if asks_accuracy:
                return "I will extract all accuracy-related issues from the uploaded file and send them to Telegram."
            return "I will extract the requested issues from the uploaded file and send them to Telegram."
        return "I will process your request and return the result."

    return answer


def _prepare_action_params(
    *,
    state: WorkflowState,
    action: str,
    system: str,
    params: dict,
    action_data: dict[str, dict],
) -> tuple[dict, str | None]:
    out = dict(params)
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

    project_key = (
        os.getenv("JIRA_DEFAULT_PROJECT_KEY", "").strip()
        or os.getenv("JIRA_PROJECT_KEY", "").strip()
    )
    issue_type = os.getenv("JIRA_DEFAULT_ISSUE_TYPE", "Bug").strip() or "Bug"
    summary, description = _derive_issue_content_from_state(state)

    if "project" not in fields:
        if not project_key:
            return params, "jira_create_issue requires project key. Set JIRA_DEFAULT_PROJECT_KEY or provide fields.project."
        fields["project"] = {"key": project_key}
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
