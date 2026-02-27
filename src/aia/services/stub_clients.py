from typing import Any


class StubLLMClient:
    def complete_json(self, *, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        if "enriched_task.schema.json" in user_prompt:
            return {
                "task_type": "accuracy_filter",
                "requires_slack": True,
                "requires_jira": True,
                "confidence_threshold": 0.6,
                "output_tone": "executive",
                "routing_hints": ["high_severity_first", "dedupe_before_create"],
                "rag_query_seed": "Definition and classification rules for accuracy-related defects.",
            }
        if "route_plan.schema.json" in user_prompt:
            return {
                "run_slack": True,
                "run_jira": True,
                "slack_prompt": "Generate executive summary for Slack.",
                "jira_prompt": "Create Jira ticket payloads.",
                "parallel": True,
            }
        if "tickets" in system_prompt.lower():
            return {"tickets": []}
        if "classify whether each qa issue" in system_prompt.lower():
            return []
        return {
            "collections": ["taxonomy", "rules", "examples"],
            "query_text": "accuracy-related qa issue rules and examples",
            "top_k": 5,
            "min_score": 0.72,
        }

    def complete_text(self, *, system_prompt: str, user_prompt: str) -> str:
        return "AIA Summary: no high-confidence accuracy issues found."


class StubVectorStore:
    def search(
        self, *, collections: list[str], query_text: str, top_k: int, min_score: float
    ) -> list[dict[str, Any]]:
        return [{"text": "Accuracy context", "score": 0.9, "source": "stub"}]


class StubSlackClient:
    def post_markdown(self, *, markdown: str) -> str:
        return "https://slack.example.local/message/1"


class StubJiraClient:
    def create_ticket(self, payload: dict[str, Any]) -> str:
        return "https://jira.example.local/browse/AIA-1"

