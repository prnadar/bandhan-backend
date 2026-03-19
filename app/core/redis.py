"""
Redis client — shared across OTP store, session cache, rate limiting, pub/sub.
Falls back to fakeredis when Redis is unavailable (dev/staging without Redis).
"""
from redis.asyncio import Redis, from_url

from app.core.config import get_settings
from app.core.logging import get_logger

settings = get_settings()
logger = get_logger(__name__)

_redis: Redis | None = None


async def get_redis() -> Redis:
    global _redis
    if _redis is None:
        try:
            client = from_url(
                settings.REDIS_URL,
                encoding="utf-8",
                decode_responses=True,
                max_connections=50,
                socket_connect_timeout=2,
            )
            # Test connection
            await client.ping()
            _redis = client
            logger.info("redis_connected", url=settings.REDIS_URL[:30])
        except Exception as exc:
            logger.warning("redis_unavailable_using_fakeredis", error=str(exc))
            import fakeredis.aioredis as fakeredis  # type: ignore[import]
            _redis = fakeredis.FakeRedis(decode_responses=True)  # type: ignore[assignment]
    return _redis


async def close_redis() -> None:
    global _redis
    if _redis is not None:
        try:
            await _redis.aclose()
        except Exception:
            pass
        _redis = None
