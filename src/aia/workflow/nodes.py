import json
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
    user_prompt = render_template(load_prompt("enrichment.user.md"), instruction=state["instruction"])
    raw = deps.llm.complete_json(system_prompt=sys_prompt, user_prompt=user_prompt)
    if not isinstance(raw, dict):
        raw = {}
    normalized = normalize_enriched_task_raw(raw)
    if state.get("file_id") or _should_force_rag(state):
        normalized["requires_rag"] = True
    try:
        enriched = EnrichedTask.model_validate(normalized).model_dump()
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
        query_text=query_spec.get("query_text", state["instruction"]),
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
            "instruction": state["instruction"],
            "rag_context": state.get("rag_context", {}),
            "enriched_task": state["enriched_task"],
        },
        ensure_ascii=False,
    )
    answer = deps.llm.complete_text(system_prompt=sys_prompt, user_prompt=user_prompt).strip()
    if not answer:
        answer = "Request processed."
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

    for item in action_plans:
        system = item.get("system")
        action = item.get("action")
        params = item.get("params", {})
        try:
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
        except Exception as exc:
            action_result = ActionResult(
                system=system or "jira",
                action=action or "unknown_action",
                status="failed",
                error=str(exc),
            ).model_dump()
            errors.append(f"{action_result['system']}:{action_result['action']} failed: {exc}")

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
    instruction = _extract_current_request_text(str(state.get("instruction", ""))).lower()
    file_id = state.get("file_id")

    file_scoped_phrases = ("in the file", "from the file", "uploaded file", "this file")
    asks_for_jira = "jira" in instruction
    asks_file_scope = any(p in instruction for p in file_scoped_phrases)
    if file_id and asks_file_scope and not asks_for_jira:
        action_plans = [a for a in action_plans if a.get("system") != "jira"]

    route_plan["action_plans"] = action_plans
    return route_plan


def _should_force_rag(state: WorkflowState) -> bool:
    file_id = state.get("file_id")
    if not file_id:
        return False
    instruction = _extract_current_request_text(str(state.get("instruction", ""))).lower()
    # If a file is attached and request appears file/content-centric, require retrieval.
    file_scoped_phrases = ("in the file", "from the file", "uploaded file", "this file", "file related")
    content_scoped_phrases = ("accuracy", "issues", "find in", "retrieve", "summarize")
    return any(p in instruction for p in file_scoped_phrases) or any(p in instruction for p in content_scoped_phrases)


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
