"""Local scaffold runner with placeholder clients.

Replace these placeholder implementations with real clients.
"""

from typing import Any

from aia.workflow.graph import build_graph


class DummyLLM:
    def complete_json(self, *, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        if "enriched_task.schema.json" in user_prompt:
            return {
                "task_type": "accuracy_filter",
                "requires_slack": True,
                "requires_jira": True,
                "confidence_threshold": 0.6,
                "output_tone": "executive",
                "routing_hints": ["high_severity_first", "dedupe_before_create"],
                "rag_query_seed": "Definition and rules for classifying accuracy-related QA defects.",
            }
        if "route_plan.schema.json" in user_prompt:
            return {
                "run_slack": True,
                "run_jira": True,
                "slack_prompt": "Summarize the issues for Slack.",
                "jira_prompt": "Create Jira payloads.",
                "parallel": True,
            }
        if "tickets" in system_prompt.lower():
            return {"tickets": []}
        if "classification" in system_prompt.lower():
            return []
        return {
            "collections": ["taxonomy", "rules", "examples"],
            "query_text": "accuracy-related issue classification rules",
            "top_k": 5,
            "min_score": 0.72,
        }

    def complete_text(self, *, system_prompt: str, user_prompt: str) -> str:
        return "No critical accuracy issues found."


class DummyVectorStore:
    def search(self, *, collections: list[str], query_text: str, top_k: int, min_score: float) -> list[dict]:
        return [{"text": "Accuracy issue definition context", "score": 0.9}]


class DummySlack:
    def post_markdown(self, *, markdown: str) -> str:
        return "https://slack.example.local/message/1"


class DummyJira:
    def create_ticket(self, payload: dict[str, Any]) -> str:
        return "https://jira.example.local/browse/PROJ-1"


def main() -> None:
    graph = build_graph(
        llm=DummyLLM(),
        vector_store=DummyVectorStore(),
        slack=DummySlack(),
        jira=DummyJira(),
    )
    result = graph.invoke(
        {
            "request_id": "req-001",
            "instruction": "Summarize and create tickets for accuracy issues.",
            "parsed_issues": [],
        }
    )
    print(result["final_response"])


if __name__ == "__main__":
    main()

