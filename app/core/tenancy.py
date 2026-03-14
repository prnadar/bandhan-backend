"""
Multi-tenancy middleware and context.

Each white-label client (marriage bureau, regional brand) is a Tenant.
tenant_id is injected into every request context and stamped on all DB rows.
Lookup order: X-Tenant-ID header → subdomain → default tenant.
"""
import contextvars
from uuid import UUID

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)
settings = get_settings()

# Request-scoped tenant context
_current_tenant_id: contextvars.ContextVar[UUID | None] = contextvars.ContextVar(
    "current_tenant_id", default=None
)
_current_tenant_slug: contextvars.ContextVar[str] = contextvars.ContextVar(
    "current_tenant_slug", default=settings.DEFAULT_TENANT_SLUG
)


def get_current_tenant_id() -> UUID | None:
    return _current_tenant_id.get()


def get_current_tenant_slug() -> str:
    return _current_tenant_slug.get()


class TenantMiddleware(BaseHTTPMiddleware):
    """
    Resolves tenant from request and injects into context vars.
    Health/docs endpoints bypass tenant resolution.
    """

    BYPASS_PATHS = {"/health", "/docs", "/redoc", "/openapi.json"}

    async def dispatch(self, request: Request, call_next):
        if request.url.path in self.BYPASS_PATHS:
            return await call_next(request)

        tenant_slug = await self._resolve_tenant_slug(request)
        if not tenant_slug:
            return JSONResponse(
                {"detail": "Tenant not found", "code": "TENANT_NOT_FOUND"},
                status_code=404,
            )

        token_slug = _current_tenant_slug.set(tenant_slug)
        try:
            # Tenant UUID is resolved lazily by DB queries needing it
            response = await call_next(request)
            return response
        finally:
            _current_tenant_slug.reset(token_slug)

    async def _resolve_tenant_slug(self, request: Request) -> str | None:
        # 1. Explicit header (for API clients / mobile apps)
        if header_val := request.headers.get(settings.TENANT_HEADER):
            return header_val.lower()

        # 2. Subdomain: bandhan.in → default, bureau-xyz.bandhan.in → bureau-xyz
        host = request.headers.get("host", "").split(":")[0]
        parts = host.split(".")
        if len(parts) >= 3:
            subdomain = parts[0].lower()
            if subdomain not in ("www", "api"):
                return subdomain

        # 3. Fall back to default tenant
        return settings.DEFAULT_TENANT_SLUG
