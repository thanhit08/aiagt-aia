from typing import Any

from aia.services.protocols import JiraClient, LLMClient, SlackClient, VectorStore
from aia.workflow.nodes import (
    NodeDeps,
    aggregate_node,
    answer_node,
    enrichment_node,
    execute_actions_node,
    intake_node,
    rag_context_node,
    route_node,
)
from aia.workflow.state import WorkflowState


def build_graph(
    *,
    llm: LLMClient,
    vector_store: VectorStore,
    slack: SlackClient,
    jira: JiraClient,
) -> Any:
    deps = NodeDeps(llm=llm, vector_store=vector_store, slack=slack, jira=jira)
    try:
        from langgraph.graph import END, StateGraph
    except ImportError:
        return _fallback_graph(deps)

    graph = StateGraph(WorkflowState)
    graph.add_node("intake", intake_node)
    graph.add_node("enrichment", lambda s: enrichment_node(s, deps))
    graph.add_node("rag", lambda s: rag_context_node(s, deps))
    graph.add_node("answer", lambda s: answer_node(s, deps))
    graph.add_node("route", lambda s: route_node(s, deps))
    graph.add_node("execute_actions", lambda s: execute_actions_node(s, deps))
    graph.add_node("aggregate", aggregate_node)

    graph.set_entry_point("intake")
    graph.add_edge("intake", "enrichment")
    graph.add_edge("enrichment", "rag")
    graph.add_edge("rag", "answer")
    graph.add_edge("answer", "route")
    graph.add_edge("route", "execute_actions")
    graph.add_edge("execute_actions", "aggregate")
    graph.add_edge("aggregate", END)
    return graph.compile()


def _fallback_graph(deps: NodeDeps) -> Any:
    class _SimpleGraph:
        def invoke(self, state: dict) -> dict:
            current = dict(state)
            current.update(intake_node(current))
            current.update(enrichment_node(current, deps))
            current.update(rag_context_node(current, deps))
            current.update(answer_node(current, deps))
            current.update(route_node(current, deps))
            current.update(execute_actions_node(current, deps))
            current.update(aggregate_node(current))
            return current

    return _SimpleGraph()

