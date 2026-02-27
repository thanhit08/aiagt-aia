import os
from dataclasses import dataclass


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    use_real_services: bool = _env_bool("AIA_USE_REAL_SERVICES", False)

    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    openai_base_url: str = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")

    qdrant_url: str = os.getenv("QDRANT_URL", "http://localhost:6333")
    qdrant_api_key: str = os.getenv("QDRANT_API_KEY", "")
    qdrant_collections: str = os.getenv("QDRANT_COLLECTIONS", "taxonomy,rules,examples")

    jira_base_url: str = os.getenv("JIRA_BASE_URL", "")
    jira_email: str = os.getenv("JIRA_EMAIL", "")
    jira_api_token: str = os.getenv("JIRA_API_TOKEN", "")

    slack_bot_token: str = os.getenv("SLACK_BOT_TOKEN", "")

    telegram_bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    telegram_default_chat_id: str = os.getenv("TELEGRAM_DEFAULT_CHAT_ID", "")

    langsmith_api_key: str = os.getenv("LANGSMITH_API_KEY", "")
    langfuse_public_key: str = os.getenv("LANGFUSE_PUBLIC_KEY", "")
    langfuse_secret_key: str = os.getenv("LANGFUSE_SECRET_KEY", "")

    redis_url: str = os.getenv("REDIS_URL", "")
    redis_enabled: bool = _env_bool("REDIS_ENABLED", False)
    redis_response_ttl_seconds: int = int(os.getenv("REDIS_RESPONSE_TTL_SECONDS", "300"))
    redis_rate_limit_per_minute: int = int(os.getenv("REDIS_RATE_LIMIT_PER_MINUTE", "60"))

    mongo_enabled: bool = _env_bool("MONGO_ENABLED", False)
    mongo_url: str = os.getenv("MONGO_URL", "")
    mongo_db_name: str = os.getenv("MONGO_DB_NAME", "aia")

    context_recent_messages: int = int(os.getenv("CONTEXT_RECENT_MESSAGES", "8"))
    context_max_messages: int = int(os.getenv("CONTEXT_MAX_MESSAGES", "20"))


def load_settings() -> Settings:
    return Settings()
