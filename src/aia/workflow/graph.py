from typing import Any

from aia.services.protocols import JiraClient, LLMClient, SlackClient, TelegramClient, VectorStore
from aia.workflow.nodes import (
    NodeDeps,
    aggregate_node,
    execute_actions_node,
    intake_node,
    rag_check_node,
    rag_context_node,
    rag_query_enrichment_node,
    route_node,
)
from aia.workflow.state import WorkflowState


def build_graph(
    *,
    llm: LLMClient,
    vector_store: VectorStore,
    slack: SlackClient,
    jira: JiraClient,
    telegram: TelegramClient,
) -> Any:
    deps = NodeDeps(llm=llm, vector_store=vector_store, slack=slack, jira=jira, telegram=telegram)
    try:
        from langgraph.graph import END, StateGraph
    except ImportError:
        return _fallback_graph(deps)

    graph = StateGraph(WorkflowState)
    graph.add_node("intake", intake_node)
    graph.add_node("rag_check", rag_check_node)
    graph.add_node("rag_query_enrichment", lambda s: rag_query_enrichment_node(s, deps))
    graph.add_node("rag", lambda s: rag_context_node(s, deps))
    graph.add_node("route", lambda s: route_node(s, deps))
    graph.add_node("execute_actions", lambda s: execute_actions_node(s, deps))
    graph.add_node("aggregate", aggregate_node)

    graph.set_entry_point("intake")
    graph.add_edge("intake", "rag_check")
    graph.add_conditional_edges(
        "rag_check",
        lambda s: "rag_query_enrichment" if s.get("rag_required") else "route",
        {"rag_query_enrichment": "rag_query_enrichment", "route": "route"},
    )
    graph.add_edge("rag_query_enrichment", "rag")
    graph.add_edge("rag", "route")
    graph.add_edge("route", "execute_actions")
    graph.add_edge("execute_actions", "aggregate")
    graph.add_edge("aggregate", END)
    return graph.compile()


def _fallback_graph(deps: NodeDeps) -> Any:
    class _SimpleGraph:
        def invoke(self, state: dict) -> dict:
            current = dict(state)
            current.update(intake_node(current))
            current.update(rag_check_node(current))
            if current.get("rag_required"):
                current.update(rag_query_enrichment_node(current, deps))
                current.update(rag_context_node(current, deps))
            current.update(route_node(current, deps))
            current.update(execute_actions_node(current, deps))
            current.update(aggregate_node(current))
            return current

    return _SimpleGraph()
