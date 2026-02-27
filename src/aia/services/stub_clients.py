from typing import Any


class StubLLMClient:
    def complete_json(self, *, system_prompt: str, user_prompt: str) -> dict[str, Any] | list[Any]:
        text = f"{system_prompt}\n{user_prompt}".lower()
        action_plans = []
        if "jira" in text:
            action_plans.append(
                {
                    "system": "jira",
                    "action": "jira_search_issues",
                    "params": {"jql": "assignee = currentUser()"},
                    "risk_level": "low",
                    "depends_on": [],
                }
            )
        if "slack" in text:
            action_plans.append(
                {
                    "system": "slack",
                    "action": "slack_post_message",
                    "params": {"channel": "#general", "text": "Stub result"},
                    "risk_level": "low",
                    "depends_on": [],
                }
            )
        if "telegram" in text:
            action_plans.append(
                {
                    "system": "telegram",
                    "action": "telegram_send_message",
                    "params": {"text": "Stub telegram result"},
                    "risk_level": "low",
                    "depends_on": [],
                }
            )

        if "enriched_task.schema.json" in text:
            return {
                "task_type": "tool_orchestration" if action_plans else "general_query",
                "requires_rag": False,
                "output_tone": "neutral",
                "rag_query_seed": "",
                "action_plans": action_plans,
            }
        if "route_plan.schema.json" in text:
            return {"parallel": True, "action_plans": action_plans}
        if "query_text" in text:
            return {
                "collections": ["taxonomy", "rules", "examples"],
                "query_text": "general retrieval context",
                "top_k": 5,
                "min_score": 0.72,
            }
        return {}

    def complete_text(self, *, system_prompt: str, user_prompt: str) -> str:
        return "Stub answer: request processed successfully."


class StubVectorStore:
    def __init__(self) -> None:
        self._chunks: list[dict[str, Any]] = []

    def upsert_chunks(self, *, file_id: str, chunks: list[str]) -> dict[str, Any]:
        for idx, chunk in enumerate(chunks):
            self._chunks.append({"file_id": file_id, "chunk_index": idx, "text": chunk})
        return {"status": "ok", "stored_chunks": len(chunks), "file_id": file_id}

    def search(
        self,
        *,
        collections: list[str],
        query_text: str,
        top_k: int,
        min_score: float,
        file_id: str | None = None,
    ) -> list[dict[str, Any]]:
        rows = self._chunks
        if file_id:
            rows = [r for r in rows if r["file_id"] == file_id]
        rows = rows[:top_k]
        if not rows:
            return [{"text": "Stub context", "score": 0.9, "collection": collections[0] if collections else ""}]
        return [
            {
                "text": r["text"],
                "score": 1.0,
                "collection": collections[0] if collections else "uploaded_files",
                "payload": {"file_id": r["file_id"], "chunk_index": r["chunk_index"]},
            }
            for r in rows
        ]


class StubSlackClient:
    def execute_action(self, *, action: str, params: dict[str, Any]) -> dict[str, Any]:
        return {
            "system": "slack",
            "action": action,
            "status": "failed",
            "error": "Slack integration is not supported yet in this environment. Please use Telegram.",
        }


class StubJiraClient:
    def execute_action(self, *, action: str, params: dict[str, Any]) -> dict[str, Any]:
        return {
            "system": "jira",
            "action": action,
            "status": "success",
            "data": {"url": "https://jira.example.local/browse/AIA-1", "params": params},
        }


class StubTelegramClient:
    def execute_action(self, *, action: str, params: dict[str, Any]) -> dict[str, Any]:
        return {
            "system": "telegram",
            "action": action,
            "status": "success",
            "data": {"message_id": 1, "chat_id": params.get("chat_id", "stub"), "params": params},
        }
