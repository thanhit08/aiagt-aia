from aia.config import load_settings
from aia.services.cache_store import InMemoryCacheStore, RedisCacheStore
from aia.services.conversation_store import InMemoryConversationStore, MongoConversationStore
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
    conversation_store = _build_conversation_store(settings)
    if settings.use_real_services:
        return (
            OpenAILLMClient(settings),
            QdrantVectorStore(settings),
            StubSlackClient(),
            JiraApiClient(settings),
            TelegramApiClient(settings),
            cache_store,
            conversation_store,
            settings,
        )
    return (
        StubLLMClient(),
        StubVectorStore(),
        StubSlackClient(),
        StubJiraClient(),
        StubTelegramClient(),
        cache_store,
        conversation_store,
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


def _build_conversation_store(settings):
    if settings.mongo_enabled and settings.mongo_url:
        try:
            from pymongo import MongoClient

            client = MongoClient(settings.mongo_url, serverSelectionTimeoutMS=2000)
            client.admin.command("ping")
            db = client[settings.mongo_db_name]
            return MongoConversationStore(db)
        except Exception:
            return InMemoryConversationStore()
    return InMemoryConversationStore()
