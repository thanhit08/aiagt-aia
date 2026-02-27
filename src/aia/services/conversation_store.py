from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable


class InMemoryConversationStore:
    def __init__(self) -> None:
        self._conversations: dict[str, dict[str, Any]] = {}
        self._request_logs: list[dict[str, Any]] = []

    def get_conversation(self, conversation_id: str) -> dict[str, Any] | None:
        doc = self._conversations.get(conversation_id)
        if not doc:
            return None
        return dict(doc)

    def get_context(self, conversation_id: str, recent_limit: int) -> dict[str, Any]:
        doc = self._conversations.get(conversation_id, {"summary": "", "messages": []})
        messages = doc.get("messages", [])
        return {
            "conversation_id": conversation_id,
            "summary": doc.get("summary", ""),
            "messages": messages[-recent_limit:],
        }

    def append_message(
        self,
        *,
        conversation_id: str,
        user_id: str,
        role: str,
        content: str,
        tools_used: list[str] | None = None,
        meta: dict[str, Any] | None = None,
    ) -> None:
        doc = self._conversations.setdefault(
            conversation_id,
            {
                "conversation_id": conversation_id,
                "user_id": user_id,
                "summary": "",
                "messages": [],
                "created_at": _utc_now_iso(),
                "updated_at": _utc_now_iso(),
            },
        )
        doc["messages"].append(
            {
                "ts": _utc_now_iso(),
                "role": role,
                "content": content,
                "tools_used": tools_used or [],
                "meta": meta or {},
            }
        )
        doc["updated_at"] = _utc_now_iso()

    def log_request_response(self, payload: dict[str, Any]) -> None:
        self._request_logs.append(payload)

    def maybe_compact(
        self,
        *,
        conversation_id: str,
        max_messages: int,
        keep_recent: int,
        summarize_fn: Callable[[str, str], str],
    ) -> None:
        doc = self._conversations.get(conversation_id)
        if not doc:
            return
        messages = doc.get("messages", [])
        if len(messages) <= max_messages:
            return
        old_messages = messages[:-keep_recent]
        recent = messages[-keep_recent:]
        old_text = _messages_to_text(old_messages)
        new_summary = summarize_fn(doc.get("summary", ""), old_text)
        doc["summary"] = new_summary
        doc["messages"] = recent
        doc["updated_at"] = _utc_now_iso()


class MongoConversationStore:
    def __init__(self, mongo_db: Any) -> None:
        self._conversations = mongo_db["conversations"]
        self._request_logs = mongo_db["request_logs"]

    def get_conversation(self, conversation_id: str) -> dict[str, Any] | None:
        doc = self._conversations.find_one({"_id": conversation_id})
        if not doc:
            return None
        # normalize ObjectId-free response shape
        doc["id"] = str(doc.pop("_id"))
        return doc

    def get_context(self, conversation_id: str, recent_limit: int) -> dict[str, Any]:
        doc = self._conversations.find_one({"_id": conversation_id}) or {}
        messages = doc.get("messages", [])
        return {
            "conversation_id": conversation_id,
            "summary": doc.get("summary", ""),
            "messages": messages[-recent_limit:],
        }

    def append_message(
        self,
        *,
        conversation_id: str,
        user_id: str,
        role: str,
        content: str,
        tools_used: list[str] | None = None,
        meta: dict[str, Any] | None = None,
    ) -> None:
        message = {
            "ts": _utc_now_iso(),
            "role": role,
            "content": content,
            "tools_used": tools_used or [],
            "meta": meta or {},
        }
        self._conversations.update_one(
            {"_id": conversation_id},
            {
                "$setOnInsert": {
                    "_id": conversation_id,
                    "conversation_id": conversation_id,
                    "user_id": user_id,
                    "summary": "",
                    "created_at": _utc_now_iso(),
                },
                "$push": {"messages": message},
                "$set": {"updated_at": _utc_now_iso()},
            },
            upsert=True,
        )

    def log_request_response(self, payload: dict[str, Any]) -> None:
        self._request_logs.insert_one(payload)

    def maybe_compact(
        self,
        *,
        conversation_id: str,
        max_messages: int,
        keep_recent: int,
        summarize_fn: Callable[[str, str], str],
    ) -> None:
        doc = self._conversations.find_one({"_id": conversation_id})
        if not doc:
            return
        messages = doc.get("messages", [])
        if len(messages) <= max_messages:
            return
        old_messages = messages[:-keep_recent]
        recent = messages[-keep_recent:]
        old_text = _messages_to_text(old_messages)
        new_summary = summarize_fn(doc.get("summary", ""), old_text)
        self._conversations.update_one(
            {"_id": conversation_id},
            {
                "$set": {
                    "summary": new_summary,
                    "messages": recent,
                    "updated_at": _utc_now_iso(),
                }
            },
        )


def _messages_to_text(messages: list[dict[str, Any]]) -> str:
    lines = []
    for m in messages:
        role = m.get("role", "unknown")
        content = str(m.get("content", ""))
        lines.append(f"{role}: {content}")
    return "\n".join(lines)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
