"""
Redis client — shared across OTP store, session cache, rate limiting, pub/sub.
"""
from redis.asyncio import Redis, from_url

from app.core.config import get_settings

settings = get_settings()

_redis: Redis | None = None


async def get_redis() -> Redis:
    global _redis
    if _redis is None:
        _redis = from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
            max_connections=50,
        )
    return _redis


async def close_redis() -> None:
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None
