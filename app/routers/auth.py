"""
Auth router — registration, OTP, profile bootstrap, email verification.
POST /api/v1/auth/register
POST /api/v1/auth/verify-otp
POST /api/v1/auth/resend-otp
POST /api/v1/auth/send-verification-email
GET  /api/v1/auth/verify-email
"""
import random
import secrets
import string
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.core.logging import get_logger
from app.core.redis import get_redis
from app.core.security import get_current_user
from app.core.tenancy import get_current_tenant_slug

settings = get_settings()
from app.models.user import User
from app.schemas.auth import OTPVerifyRequest, RegisterRequest, TokenResponse
from app.schemas.common import APIResponse
from app.services.email import send_verification_email, send_welcome_email
from app.services.otp import send_otp, verify_otp

router = APIRouter(prefix="/auth", tags=["auth"])
logger = get_logger(__name__)

# ── Token constants ───────────────────────────────────────────────────────────
_EMAIL_TOKEN_LEN     = 6
_EMAIL_TOKEN_TTL_SEC = 600   # 10 minutes
_EMAIL_TOKEN_PREFIX  = "email_verify:"


def _generate_email_token() -> str:
    """Generate a 6-character uppercase alphanumeric token."""
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(_EMAIL_TOKEN_LEN))


# ── Existing endpoints ────────────────────────────────────────────────────────


@router.post("/register", response_model=APIResponse[dict])
async def register(
    payload: RegisterRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_slug: str = Depends(get_current_tenant_slug),
):
    """
    Start registration with phone OTP.
    Creates user record if new. Sends OTP via Twilio.
    Rate limited to 10/minute per phone number.
    """
    sent = await send_otp(payload.phone, payload.country_code, tenant_slug)
    if not sent:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not send OTP. Try again in a moment.",
        )
    return APIResponse(
        success=True,
        data={"phone": payload.phone[-4:].rjust(len(payload.phone), "*")},
        message="OTP sent successfully",
    )


@router.post("/verify-otp", response_model=APIResponse[TokenResponse])
async def verify_otp_endpoint(
    payload: OTPVerifyRequest,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_slug: str = Depends(get_current_tenant_slug),
):
    """
    Verify OTP → issue Auth0 token.
    Creates user record if first-time login.
    """
    is_valid = await verify_otp(payload.phone, payload.otp, tenant_slug)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired OTP",
        )

    # Upsert user
    result = await db.execute(
        select(User).where(
            User.phone == payload.phone,
            User.deleted_at.is_(None),
        )
    )
    user = result.scalar_one_or_none()
    is_new = user is None

    if is_new:
        from sqlalchemy import text
        tenant_result = await db.execute(
            text("SELECT id FROM tenants WHERE slug = :slug LIMIT 1"),
            {"slug": tenant_slug}
        )
        tenant_row = tenant_result.fetchone()
        tenant_uuid = tenant_row[0] if tenant_row else None

        user = User(
            tenant_id=tenant_uuid,
            phone=payload.phone,
            is_phone_verified=True,
        )
        db.add(user)
        await db.flush()
        logger.info("new_user_created", user_id=str(user.id), tenant=tenant_slug)
    else:
        user.is_phone_verified = True

    # In demo mode (no Auth0), issue a demo token accepted by security middleware
    # In production, replace with real Auth0 M2M token exchange
    if not settings.AUTH0_DOMAIN:
        access_token = f"demo:{str(user.id)}"
    else:
        access_token = "__placeholder_implement_auth0_exchange__"

    token_data = TokenResponse(
        access_token=access_token,
        expires_in=86400,
        user_id=str(user.id),
        is_new_user=is_new,
    )

    return APIResponse(success=True, data=token_data)


@router.post("/resend-otp", response_model=APIResponse[None])
async def resend_otp(
    payload: RegisterRequest,
    tenant_slug: str = Depends(get_current_tenant_slug),
):
    sent = await send_otp(payload.phone, payload.country_code, tenant_slug)
    if not sent:
        raise HTTPException(status_code=503, detail="Could not resend OTP")
    return APIResponse(success=True, message="OTP resent")


# ── Email verification endpoints ──────────────────────────────────────────────


@router.post("/send-verification-email", response_model=APIResponse[dict])
async def send_verification_email_endpoint(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """
    Send a 6-character email verification token to the authenticated user's
    registered email address.

    Rate: honours the global rate-limit middleware (10/min per IP by default).
    The token is stored in Redis with a 10-minute TTL.
    """
    import uuid

    # Resolve user from JWT sub
    try:
        user_uuid = uuid.UUID(current_user.get("sub", ""))
    except (ValueError, AttributeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid user session",
        )

    result = await db.execute(
        select(User).where(User.id == user_uuid, User.deleted_at.is_(None))
    )
    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if user.is_email_verified:
        return APIResponse(
            success=True,
            data={"email_verified": True},
            message="Email is already verified",
        )

    if not user.email:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No email address on file. Please update your profile first.",
        )

    token = _generate_email_token()

    # Store token in Redis: key → user_id
    redis = await get_redis()
    redis_key = f"{_EMAIL_TOKEN_PREFIX}{token}"
    await redis.setex(redis_key, _EMAIL_TOKEN_TTL_SEC, str(user_uuid))

    # Derive display name
    display_name = user.email.split("@")[0]
    try:
        profile_result = await db.execute(
            select(User.id).where(User.id == user_uuid)      # lightweight check
        )
    except Exception:
        pass

    # Try to get first_name from profile
    try:
        from app.models.user import UserProfile
        profile_result = await db.execute(
            select(UserProfile).where(UserProfile.user_id == user_uuid)
        )
        profile = profile_result.scalar_one_or_none()
        if profile and profile.first_name:
            display_name = profile.first_name
    except Exception:
        pass

    sent = await send_verification_email(
        email=user.email,
        token=token,
        user_name=display_name,
    )

    if not sent:
        logger.error("email_send_failed", user_id=str(user_uuid))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not send verification email. Please try again shortly.",
        )

    logger.info("verification_email_sent", user_id=str(user_uuid), email=user.email[:6] + "***")
    return APIResponse(
        success=True,
        data={"email": user.email[:3] + "***" + user.email[user.email.index("@"):]},
        message="Verification email sent. Please check your inbox.",
    )


@router.get("/verify-email", response_model=APIResponse[dict])
async def verify_email_endpoint(
    token: str = Query(..., min_length=6, max_length=6, description="6-character verification token"),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
):
    """
    Verify an email address using the 6-character token from the verification email.

    On success:
    - Sets User.is_email_verified = True
    - Increments trust_score by +5
    - Deletes the token from Redis (single-use)
    - Sends a welcome email
    """
    import uuid

    redis = await get_redis()
    redis_key = f"{_EMAIL_TOKEN_PREFIX}{token.upper()}"

    user_id_str: str | None = await redis.get(redis_key)

    if not user_id_str:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired verification token",
        )

    try:
        user_uuid = uuid.UUID(user_id_str)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Token data corrupted — please request a new verification email",
        )

    result = await db.execute(
        select(User).where(User.id == user_uuid, User.deleted_at.is_(None))
    )
    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if user.is_email_verified:
        # Token was already used — delete it and return success
        await redis.delete(redis_key)
        return APIResponse(
            success=True,
            data={"email_verified": True},
            message="Email already verified",
        )

    # Mark as verified
    user.is_email_verified = True
    user.trust_score = (user.trust_score or 0) + 5     # email verification trust boost
    await db.flush()

    # Consume token — single-use
    await redis.delete(redis_key)

    logger.info("email_verified", user_id=str(user_uuid))

    # Derive display name for welcome email
    display_name = (user.email or "").split("@")[0]
    try:
        from app.models.user import UserProfile
        profile_result = await db.execute(
            select(UserProfile).where(UserProfile.user_id == user_uuid)
        )
        profile = profile_result.scalar_one_or_none()
        if profile and profile.first_name:
            display_name = profile.first_name
    except Exception:
        pass

    if user.email:
        await send_welcome_email(email=user.email, user_name=display_name)

    return APIResponse(
        success=True,
        data={"email_verified": True, "user_id": str(user_uuid)},
        message="Email verified successfully! Welcome to Match4Marriage.",
    )
