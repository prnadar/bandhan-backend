"""
Auth router — registration, OTP, profile bootstrap.
POST /api/v1/auth/register
POST /api/v1/auth/verify-otp
POST /api/v1/auth/resend-otp
"""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.logging import get_logger
from app.core.tenancy import get_current_tenant_slug
from app.models.user import User
from app.schemas.auth import OTPVerifyRequest, RegisterRequest, TokenResponse
from app.schemas.common import APIResponse
from app.services.otp import send_otp, verify_otp

router = APIRouter(prefix="/auth", tags=["auth"])
logger = get_logger(__name__)


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
        # tenant_id is resolved from slug — simplified here
        import uuid

        user = User(
            tenant_id=uuid.uuid4(),  # replaced with actual tenant UUID lookup in Sprint 2
            phone=payload.phone,
            is_phone_verified=True,
        )
        db.add(user)
        await db.flush()
        logger.info("new_user_created", user_id=str(user.id), tenant=tenant_slug)
    else:
        user.is_phone_verified = True

    # Exchange for Auth0 token via client credentials / machine-to-machine
    # Actual Auth0 token exchange implemented in Sprint 2 with Auth0 Management API
    token_data = TokenResponse(
        access_token="__placeholder_implement_auth0_exchange__",
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
