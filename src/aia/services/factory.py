from aia.config import load_settings
from aia.services.cache_store import InMemoryCacheStore, RedisCacheStore
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
    cache_store = _build_cache_store(settings)
    if settings.use_real_services:
        return (
            OpenAILLMClient(settings),
            QdrantVectorStore(settings),
            StubSlackClient(),
            JiraApiClient(settings),
            TelegramApiClient(settings),
            cache_store,
            settings,
        )
    return (
        StubLLMClient(),
        StubVectorStore(),
        StubSlackClient(),
        StubJiraClient(),
        StubTelegramClient(),
        cache_store,
        settings,
    )


def _build_cache_store(settings):
    if settings.redis_enabled and settings.redis_url:
        try:
            import redis

            client = redis.Redis.from_url(settings.redis_url, decode_responses=False)
            client.ping()
            return RedisCacheStore(client)
        except Exception:
            return InMemoryCacheStore()
    return InMemoryCacheStore()
