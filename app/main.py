"""
Bandhan API — FastAPI entrypoint.
All router registration, middleware, and lifespan events here.
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.core.config import get_settings
from app.core.database import engine
from app.core.logging import configure_logging, get_logger
from app.core.rate_limit import limiter  # shared Redis-backed Limiter
from app.core.redis import close_redis
from app.core.tenancy import TenantMiddleware
from app.models import *  # noqa: F401,F403 — register all models with Alembic
from app.routers import auth, chat, health, matches, notifications, profile, reports, subscriptions

settings = get_settings()
configure_logging(debug=settings.DEBUG)
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("startup", environment=settings.ENVIRONMENT, version=settings.APP_VERSION)
    yield
    await close_redis()
    await engine.dispose()
    logger.info("shutdown")


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    docs_url="/docs" if not settings.is_production else None,
    redoc_url="/redoc" if not settings.is_production else None,
    openapi_url="/openapi.json" if not settings.is_production else None,
    lifespan=lifespan,
)

# ── Middleware (order matters — outermost first) ──────────────────────────────
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(TenantMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ── Routers ───────────────────────────────────────────────────────────────────
PREFIX = settings.API_PREFIX

app.include_router(auth.router, prefix=PREFIX)
app.include_router(profile.router, prefix=PREFIX)
app.include_router(matches.router, prefix=PREFIX)
app.include_router(chat.router, prefix=PREFIX)
app.include_router(subscriptions.router, prefix=PREFIX)
app.include_router(reports.router, prefix=PREFIX)
app.include_router(notifications.router, prefix=PREFIX)
app.include_router(health.router, prefix=PREFIX)


# ── Health + meta ─────────────────────────────────────────────────────────────
@app.get("/health")
async def health_simple():
    return {"status": "ok", "version": settings.APP_VERSION}


@app.get("/")
async def root():
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "docs": "/docs",
    }
