import json
from dataclasses import dataclass
from uuid import uuid4

from aia.models.contracts import ActionResult, EnrichedTask, FinalResponse, RoutePlan
from aia.services.protocols import JiraClient, LLMClient, SlackClient, TelegramClient, VectorStore
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
    enriched = EnrichedTask.model_validate(raw).model_dump()
    return {"enriched_task": enriched}


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
    if isinstance(raw, dict) and raw.get("action_plans") is not None:
        route_raw = raw
    else:
        route_raw = {"parallel": True, "action_plans": state["enriched_task"].get("action_plans", [])}
    route_plan = RoutePlan.model_validate(route_raw).model_dump()
    return {"route_plan": route_plan}


def execute_actions_node(state: WorkflowState, deps: NodeDeps) -> WorkflowState:
    results: list[dict] = []
    errors = list(state.get("errors", []))
    action_plans = state.get("route_plan", {}).get("action_plans", [])

    for item in action_plans:
        system = item.get("system")
        action = item.get("action")
        params = item.get("params", {})
        try:
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
