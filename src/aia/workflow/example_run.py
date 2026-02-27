"""Local scaffold runner with placeholder clients."""

from aia.services.stub_clients import (
    StubJiraClient,
    StubLLMClient,
    StubSlackClient,
    StubTelegramClient,
    StubVectorStore,
)
from aia.workflow.graph import build_graph


def main() -> None:
    graph = build_graph(
        llm=StubLLMClient(),
        vector_store=StubVectorStore(),
        slack=StubSlackClient(),
        jira=StubJiraClient(),
        telegram=StubTelegramClient(),
    )
    result = graph.invoke(
        {
            "request_id": "req-001",
            "instruction": "Find issues assigned to me in Jira and post to Slack.",
            "parsed_issues": [],
        }
    )
    print(result["final_response"])


if __name__ == "__main__":
    main()
