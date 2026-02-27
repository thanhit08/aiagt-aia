from typing import Any, Protocol


class LLMClient(Protocol):
    def complete_json(self, *, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        """Return a JSON object from the model."""

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
        """Return ranked hits with payloads from Qdrant."""


class SlackClient(Protocol):
    def post_markdown(self, *, markdown: str) -> str:
        """Post markdown and return message URL."""


class JiraClient(Protocol):
    def create_ticket(self, payload: dict[str, Any]) -> str:
        """Create ticket and return ticket URL."""

