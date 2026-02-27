import json
from dataclasses import dataclass
from uuid import uuid4

from aia.models.contracts import (
    ClassificationOutput,
    EnrichedTask,
    FinalResponse,
    RoutePlan,
)
from aia.services.protocols import JiraClient, LLMClient, SlackClient, VectorStore
from aia.workflow.prompts import load_prompt, render_template
from aia.workflow.state import WorkflowState


@dataclass
class NodeDeps:
    llm: LLMClient
    vector_store: VectorStore
    slack: SlackClient
    jira: JiraClient


def intake_node(state: WorkflowState) -> WorkflowState:
    return {
        "trace_id": state.get("trace_id", str(uuid4())),
        "errors": state.get("errors", []),
    }


def enrichment_node(state: WorkflowState, deps: NodeDeps) -> WorkflowState:
    sys_prompt = load_prompt("enrichment.system.md")
    user_prompt = render_template(
        load_prompt("enrichment.user.md"),
        instruction=state["instruction"],
    )
    raw = deps.llm.complete_json(system_prompt=sys_prompt, user_prompt=user_prompt)
    enriched = EnrichedTask.model_validate(raw).model_dump()
    return {"enriched_task": enriched}


def rag_context_node(state: WorkflowState, deps: NodeDeps) -> WorkflowState:
    sys_prompt = load_prompt("rag-query-builder.system.md")
    user_prompt = json.dumps(
        {
            "enriched_task": state["enriched_task"],
            "issue_batch": state.get("parsed_issues", []),
        }
    )
    query_spec = deps.llm.complete_json(system_prompt=sys_prompt, user_prompt=user_prompt)
    hits = deps.vector_store.search(
        collections=query_spec.get("collections", ["taxonomy", "rules", "examples"]),
        query_text=query_spec["query_text"],
        top_k=int(query_spec.get("top_k", 5)),
        min_score=float(query_spec.get("min_score", 0.72)),
    )
    rag_context = {"query_spec": query_spec, "hits": hits}
    return {"rag_context": rag_context}


def classify_node(state: WorkflowState, deps: NodeDeps) -> WorkflowState:
    sys_prompt = load_prompt("classification.system.md")
    user_prompt = render_template(
        load_prompt("classification.user.md"),
        accuracy_context=json.dumps(state["rag_context"], ensure_ascii=False),
        confidence_threshold=str(state["enriched_task"]["confidence_threshold"]),
        issues_json=json.dumps(state.get("parsed_issues", []), ensure_ascii=False),
    )
    raw = deps.llm.complete_json(system_prompt=sys_prompt, user_prompt=user_prompt)
    if isinstance(raw, dict) and "items" in raw:
        raw_items = raw["items"]
    else:
        raw_items = raw
    classified = [ClassificationOutput.model_validate(i).model_dump() for i in raw_items]
    return {"classified_issues": classified}


def filter_node(state: WorkflowState) -> WorkflowState:
    threshold = state["enriched_task"]["confidence_threshold"]
    accuracy_issues = [
        issue
        for issue in state.get("classified_issues", [])
        if issue["accuracy_related"] and issue["confidence"] >= threshold
    ]
    return {"accuracy_issues": accuracy_issues}


def route_node(state: WorkflowState, deps: NodeDeps) -> WorkflowState:
    sys_prompt = load_prompt("orchestrator-routing.system.md")
    user_prompt = render_template(
        load_prompt("orchestrator-routing.user.md"),
        enriched_task_json=json.dumps(state["enriched_task"], ensure_ascii=False),
        accuracy_context=json.dumps(state["rag_context"], ensure_ascii=False),
        accuracy_issues_json=json.dumps(state.get("accuracy_issues", []), ensure_ascii=False),
    )
    raw = deps.llm.complete_json(system_prompt=sys_prompt, user_prompt=user_prompt)
    route_plan = RoutePlan.model_validate(raw).model_dump()
    return {"route_plan": route_plan}


def slack_node(state: WorkflowState, deps: NodeDeps) -> WorkflowState:
    if not state["route_plan"]["run_slack"]:
        return {"slack_result": {"summary_posted": False, "slack_url": ""}}

    sys_prompt = load_prompt("slack-summary.system.md")
    user_prompt = render_template(
        load_prompt("slack-summary.user.md"),
        output_tone=state["enriched_task"]["output_tone"],
        accuracy_issues_json=json.dumps(state.get("accuracy_issues", []), ensure_ascii=False),
        accuracy_context=json.dumps(state["rag_context"], ensure_ascii=False),
    )
    markdown = deps.llm.complete_text(system_prompt=sys_prompt, user_prompt=user_prompt)
    slack_url = deps.slack.post_markdown(markdown=markdown)
    return {
        "slack_result": {
            "summary_posted": True,
            "slack_url": slack_url,
            "summary_markdown": markdown,
        }
    }


def jira_node(state: WorkflowState, deps: NodeDeps) -> WorkflowState:
    if not state["route_plan"]["run_jira"]:
        return {"jira_result": {"tickets_created": 0, "duplicates_skipped": 0, "jira_urls": []}}

    sys_prompt = load_prompt("jira-ticket.system.md")
    user_prompt = render_template(
        load_prompt("jira-ticket.user.md"),
        accuracy_issues_json=json.dumps(state.get("accuracy_issues", []), ensure_ascii=False),
        routing_hints=json.dumps(state["enriched_task"].get("routing_hints", []), ensure_ascii=False),
    )
    tickets_payload = deps.llm.complete_json(system_prompt=sys_prompt, user_prompt=user_prompt)
    tickets = tickets_payload.get("tickets", [])

    created_urls: list[str] = []
    for payload in tickets:
        created_urls.append(deps.jira.create_ticket(payload))

    return {
        "jira_result": {
            "tickets_created": len(created_urls),
            "duplicates_skipped": 0,
            "jira_urls": created_urls,
        }
    }


def aggregate_node(state: WorkflowState) -> WorkflowState:
    final = FinalResponse(
        request_id=state["request_id"],
        summary_posted=state.get("slack_result", {}).get("summary_posted", False),
        tickets_created=state.get("jira_result", {}).get("tickets_created", 0),
        duplicates_skipped=state.get("jira_result", {}).get("duplicates_skipped", 0),
        slack_url=state.get("slack_result", {}).get("slack_url", ""),
        jira_urls=state.get("jira_result", {}).get("jira_urls", []),
        trace_id=state["trace_id"],
        errors=state.get("errors", []),
    ).model_dump()
    return {"final_response": final}
