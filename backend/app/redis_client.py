from __future__ import annotations

from functools import lru_cache

import redis.asyncio as redis_async

from app.settings import settings


@lru_cache
def get_redis() -> redis_async.Redis:
    return redis_async.from_url(settings.redis_url, decode_responses=True)
