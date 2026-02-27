from typing import Any

from aia.services.protocols import JiraClient, LLMClient, SlackClient, VectorStore
from aia.workflow.nodes import (
    NodeDeps,
    aggregate_node,
    classify_node,
    enrichment_node,
    filter_node,
    intake_node,
    jira_node,
    rag_context_node,
    route_node,
    slack_node,
)
from aia.workflow.state import WorkflowState


def build_graph(
    *,
    llm: LLMClient,
    vector_store: VectorStore,
    slack: SlackClient,
    jira: JiraClient,
) -> Any:
    """Build LangGraph workflow with parallel Slack/Jira branches."""
    deps = NodeDeps(llm=llm, vector_store=vector_store, slack=slack, jira=jira)

    try:
        from langgraph.graph import END, StateGraph
    except ImportError as exc:
        return _fallback_graph(deps)

    graph = StateGraph(WorkflowState)

    graph.add_node("intake", intake_node)
    graph.add_node("enrichment", lambda s: enrichment_node(s, deps))
    graph.add_node("rag_context", lambda s: rag_context_node(s, deps))
    graph.add_node("classify", lambda s: classify_node(s, deps))
    graph.add_node("filter", filter_node)
    graph.add_node("route", lambda s: route_node(s, deps))
    graph.add_node("slack", lambda s: slack_node(s, deps))
    graph.add_node("jira", lambda s: jira_node(s, deps))
    graph.add_node("aggregate", aggregate_node)

    graph.set_entry_point("intake")
    graph.add_edge("intake", "enrichment")
    graph.add_edge("enrichment", "rag_context")
    graph.add_edge("rag_context", "classify")
    graph.add_edge("classify", "filter")
    graph.add_edge("filter", "route")
    graph.add_edge("route", "slack")
    graph.add_edge("route", "jira")
    graph.add_edge("slack", "aggregate")
    graph.add_edge("jira", "aggregate")
    graph.add_edge("aggregate", END)

    return graph.compile()


def _fallback_graph(deps: NodeDeps) -> Any:
    """Fallback executor used when LangGraph is not installed."""

    class _SimpleGraph:
        def invoke(self, state: dict) -> dict:
            current = dict(state)
            current.update(intake_node(current))
            current.update(enrichment_node(current, deps))
            current.update(rag_context_node(current, deps))
            current.update(classify_node(current, deps))
            current.update(filter_node(current))
            current.update(route_node(current, deps))
            current.update(slack_node(current, deps))
            current.update(jira_node(current, deps))
            current.update(aggregate_node(current))
            return current

    return _SimpleGraph()
