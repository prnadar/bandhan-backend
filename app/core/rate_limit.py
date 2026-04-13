"""
Rate limiting configuration using SlowAPI (slowapi).

Provides a single shared Limiter instance backed by Redis.
Import `limiter` in routers and apply @limiter.limit("N/minute") decorators.

Usage in a router:
    from app.core.rate_limit import limiter
    from slowapi import _rate_limit_exceeded_handler
    from slowapi.errors import RateLimitExceeded

    @router.post("/register")
    @limiter.limit("3/minute")
    async def register(request: Request, ...):
        ...

Note: the `request: Request` parameter MUST be present in the endpoint
signature for SlowAPI to identify the client (it reads request.client.host).
"""
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import get_settings

settings = get_settings()

# ── Single Limiter instance (Redis-backed in production) ─────────────────────
# slowapi accepts any limits-compliant storage string.
# Falls back to in-memory when Redis is unavailable.
_storage = settings.REDIS_URL
try:
    import redis as _sync_redis
    _r = _sync_redis.from_url(settings.REDIS_URL, socket_connect_timeout=2)
    _r.ping()
    _r.close()
except Exception:
    _storage = "memory://"

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[settings.RATE_LIMIT_DEFAULT],
    storage_uri=_storage,
)

# ── Named rate limit strings ──────────────────────────────────────────────────
# These are convenience constants — use them as decorator arguments to keep
# limits consistent and easy to change from one place.

# Applies to auth registration endpoints (prevent phone-number spam)
AUTH_LIMIT = "3/minute"

# Applies to OTP verification endpoints (prevent brute-force)
OTP_LIMIT = "10/minute"

# Applies to profile browsing / discovery feeds (prevent scraping)
BROWSE_LIMIT = "60/minute"

# Default fallback — mirrors settings.RATE_LIMIT_DEFAULT
DEFAULT_LIMIT = settings.RATE_LIMIT_DEFAULT  # "100/minute"
