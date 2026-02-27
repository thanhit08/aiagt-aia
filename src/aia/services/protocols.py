from typing import Any, Protocol


class LLMClient(Protocol):
    def complete_json(self, *, system_prompt: str, user_prompt: str) -> dict[str, Any] | list[Any]:
        """Return JSON-like output from the model."""

    def complete_text(self, *, system_prompt: str, user_prompt: str) -> str:
        """Return plain text output from the model."""


class VectorStore(Protocol):
    def search(
        self,
        *,
        collections: list[str],
        query_text: str,
        top_k: int,
        min_score: float,
    ) -> list[dict[str, Any]]:
        """Return ranked hits from Qdrant."""


class SlackClient(Protocol):
    def execute_action(self, *, action: str, params: dict[str, Any]) -> dict[str, Any]:
        """Execute one Slack action and return structured output."""


class JiraClient(Protocol):
    def execute_action(self, *, action: str, params: dict[str, Any]) -> dict[str, Any]:
        """Execute one Jira action and return structured output."""


class TelegramClient(Protocol):
    def execute_action(self, *, action: str, params: dict[str, Any]) -> dict[str, Any]:
        """Execute one Telegram action and return structured output."""


class CacheStore(Protocol):
    def get_json(self, key: str) -> dict[str, Any] | None:
        """Fetch a JSON object from cache."""

    def set_json(self, key: str, value: dict[str, Any], ttl_seconds: int) -> None:
        """Store a JSON object in cache."""

    def increment_with_ttl(self, key: str, ttl_seconds: int) -> int:
        """Increment counter and set TTL when key is first seen."""


class ConversationStore(Protocol):
    def get_conversation(self, conversation_id: str) -> dict[str, Any] | None:
        """Return full conversation document for inspection."""

    def get_context(self, conversation_id: str, recent_limit: int) -> dict[str, Any]:
        """Return summary + recent messages for conversation."""

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
        """Append one message to conversation."""

    def log_request_response(self, payload: dict[str, Any]) -> None:
        """Persist request/response entry."""

    def maybe_compact(
        self,
        *,
        conversation_id: str,
        max_messages: int,
        keep_recent: int,
        summarize_fn,
    ) -> None:
        """Compact history using rolling summary strategy."""
