from __future__ import annotations

import time

from fastapi import HTTPException, status

from app.redis_client import get_redis


async def hit(key: str, *, limit: int, window_seconds: int) -> int:
    """Sliding-window counter via sorted set. Returns current count after increment."""
    r = get_redis()
    now = time.time()
    pipe = r.pipeline()
    pipe.zremrangebyscore(key, 0, now - window_seconds)
    pipe.zadd(key, {f"{now}:{id(object())}": now})
    pipe.zcard(key)
    pipe.expire(key, window_seconds + 5)
    _, _, count, _ = await pipe.execute()
    return int(count)


async def enforce(key: str, *, limit: int, window_seconds: int) -> None:
    count = await hit(key, limit=limit, window_seconds=window_seconds)
    if count > limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="rate_limited"
        )
