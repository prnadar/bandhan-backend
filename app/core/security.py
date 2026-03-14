"""
Auth0 JWT validation + RBAC.
Roles: user | family_member | matchmaker | admin | super_admin
"""
import json
from functools import lru_cache
from typing import Annotated, Any
from urllib.request import urlopen

from authlib.jose import JsonWebKey, JsonWebToken
from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)
settings = get_settings()

bearer_scheme = HTTPBearer()


@lru_cache
def _get_jwks() -> dict[str, Any]:
    url = f"https://{settings.AUTH0_DOMAIN}/.well-known/jwks.json"
    with urlopen(url) as resp:
        return json.loads(resp.read())  # type: ignore[no-any-return]


def _decode_token(token: str) -> dict[str, Any]:
    jwks = _get_jwks()
    key_set = JsonWebKey.import_key_set(jwks)
    jwt = JsonWebToken(["RS256"])
    try:
        claims = jwt.decode(
            token,
            key_set,
            claims_options={
                "iss": {"essential": True, "value": f"https://{settings.AUTH0_DOMAIN}/"},
                "aud": {"essential": True, "value": settings.AUTH0_AUDIENCE},
            },
        )
        claims.validate()
        return dict(claims)
    except Exception as exc:
        logger.warning("jwt_validation_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


async def get_current_user(
    credentials: Annotated[
        HTTPAuthorizationCredentials, Security(bearer_scheme)
    ],
) -> dict[str, Any]:
    return _decode_token(credentials.credentials)


async def require_admin(
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    roles: list[str] = user.get("https://bandhan.in/roles", [])
    if "admin" not in roles and "super_admin" not in roles:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin required")
    return user


async def require_super_admin(
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    roles: list[str] = user.get("https://bandhan.in/roles", [])
    if "super_admin" not in roles:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Super-admin required")
    return user
