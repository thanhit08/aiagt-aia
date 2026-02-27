import json
from typing import Any


class InMemoryCacheStore:
    def __init__(self) -> None:
        self._values: dict[str, dict[str, Any]] = {}
        self._counters: dict[str, int] = {}

    def get_json(self, key: str) -> dict[str, Any] | None:
        return self._values.get(key)

    def set_json(self, key: str, value: dict[str, Any], ttl_seconds: int) -> None:
        self._values[key] = value

    def increment_with_ttl(self, key: str, ttl_seconds: int) -> int:
        current = self._counters.get(key, 0) + 1
        self._counters[key] = current
        return current


class RedisCacheStore:
    def __init__(self, redis_client: Any) -> None:
        self._redis = redis_client

    def get_json(self, key: str) -> dict[str, Any] | None:
        raw = self._redis.get(key)
        if not raw:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return json.loads(raw)

    def set_json(self, key: str, value: dict[str, Any], ttl_seconds: int) -> None:
        self._redis.set(key, json.dumps(value), ex=ttl_seconds)

    def increment_with_ttl(self, key: str, ttl_seconds: int) -> int:
        pipe = self._redis.pipeline()
        pipe.incr(key)
        pipe.ttl(key)
        count, ttl = pipe.execute()
        if ttl == -1:
            self._redis.expire(key, ttl_seconds)
        return int(count)

