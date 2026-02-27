from aia.config import load_settings
from aia.services.real_clients import (
    JiraApiClient,
    OpenAILLMClient,
    QdrantVectorStore,
    TelegramApiClient,
)
from aia.services.stub_clients import (
    StubJiraClient,
    StubLLMClient,
    StubSlackClient,
    StubTelegramClient,
    StubVectorStore,
)


def build_clients():
    settings = load_settings()
    if settings.use_real_services:
        return (
            OpenAILLMClient(settings),
            QdrantVectorStore(settings),
            StubSlackClient(),
            JiraApiClient(settings),
            TelegramApiClient(settings),
        )
    return (StubLLMClient(), StubVectorStore(), StubSlackClient(), StubJiraClient(), StubTelegramClient())
