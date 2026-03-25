"""
Detailed health-check router.
GET /api/v1/health/detailed

Probes each backing service and returns per-service status plus an
aggregate overall status.

  "healthy"  — all services responded correctly
  "degraded" — at least one service failed but the API is still running
  "unhealthy" — no backing services are reachable (extreme edge case)
"""
from datetime import datetime, timezone

from fastapi import APIRouter

from app.core.database import engine
from app.core.logging import get_logger
from app.core.redis import get_redis

router = APIRouter(tags=["health"])
logger = get_logger(__name__)


# ── Individual probes ─────────────────────────────────────────────────────────


async def _check_database() -> bool:
    """Run SELECT 1 against the database. Returns True if reachable."""
    try:
        from sqlalchemy import text
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:
        logger.warning("health_db_failed", error=str(exc))
        return False


async def _check_redis() -> bool:
    """PING the Redis/fakeredis instance. Returns True if reachable."""
    try:
        redis = await get_redis()
        response = await redis.ping()
        return bool(response)
    except Exception as exc:
        logger.warning("health_redis_failed", error=str(exc))
        return False


# ── Router ────────────────────────────────────────────────────────────────────


@router.get("/health/detailed")
async def detailed_health():
    """
    Detailed health check.

    Returns:
    ```json
    {
      "status": "healthy" | "degraded" | "unhealthy",
      "services": {
        "database": true,
        "redis": true
      },
      "timestamp": "2025-01-01T00:00:00+00:00"
    }
    ```
    """
    import asyncio

    db_ok, redis_ok = await asyncio.gather(
        _check_database(),
        _check_redis(),
    )

    services = {
        "database": db_ok,
        "redis":    redis_ok,
    }

    all_healthy = all(services.values())
    any_healthy = any(services.values())

    if all_healthy:
        overall = "healthy"
    elif any_healthy:
        overall = "degraded"
    else:
        overall = "unhealthy"

    result = {
        "status":    overall,
        "services":  services,
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
    }

    logger.info("health_check", status=overall, services=services)
    return result
