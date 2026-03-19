"""
Profile router.
GET  /api/v1/profile/{user_id}
PUT  /api/v1/profile/{user_id}
POST /api/v1/profile/photos
POST /api/v1/profile/voice-note
DELETE /api/v1/profile/photos/{s3_key}
"""
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.logging import get_logger
from app.core.security import get_current_user
from app.core.tenancy import get_current_tenant_slug
from app.models.user import UserProfile
from app.schemas.common import APIResponse
from app.schemas.user import ProfileCard, ProfileCreate, ProfileRead, ProfileUpdate
from app.services.storage import generate_upload_url
from app.services.trust_score import compute_profile_completeness

router = APIRouter(prefix="/profile", tags=["profile"])
logger = get_logger(__name__)


@router.get("/{user_id}", response_model=APIResponse[ProfileRead])
async def get_profile(
    user_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[dict, Depends(get_current_user)],
    tenant_slug: str = Depends(get_current_tenant_slug),
):
    result = await db.execute(
        select(UserProfile).where(
            UserProfile.user_id == user_id,
            UserProfile.deleted_at.is_(None),
        )
    )
    profile = result.scalar_one_or_none()
    if not profile:
        # Auto-create an empty profile for authenticated users fetching their own profile
        # This prevents 404 on first app load before onboarding completes
        from sqlalchemy import text as sa_text
        tenant_result = await db.execute(
            sa_text("SELECT id FROM tenants WHERE slug = :slug LIMIT 1"),
            {"slug": tenant_slug}
        )
        tenant_row = tenant_result.fetchone()
        tenant_uuid = tenant_row[0] if tenant_row else None

        # Only auto-create if the requesting user is fetching their own profile
        requesting_user_id = str(current_user.get("sub", ""))
        if requesting_user_id != str(user_id):
            raise HTTPException(status_code=404, detail="Profile not found")

        profile = UserProfile(
            id=uuid.uuid4(),
            tenant_id=tenant_uuid,
            user_id=user_id,
            first_name="",
            last_name="",
        )
        db.add(profile)
        await db.flush()
        await db.refresh(profile)
        logger.info("profile_auto_created_on_get", user_id=str(user_id))

    return APIResponse(success=True, data=ProfileRead.model_validate(profile, from_attributes=True))


@router.put("/{user_id}", response_model=APIResponse[ProfileRead])
async def update_profile(
    user_id: uuid.UUID,
    payload: ProfileUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[dict, Depends(get_current_user)],
):
    result = await db.execute(
        select(UserProfile).where(
            UserProfile.user_id == user_id,
            UserProfile.deleted_at.is_(None),
        )
    )
    profile = result.scalar_one_or_none()

    if not profile:
        # Auto-create profile for new users (upsert behaviour)
        from sqlalchemy import text as sa_text
        tenant_result = await db.execute(
            sa_text("SELECT id FROM tenants WHERE slug = 'bandhan' LIMIT 1")
        )
        tenant_row = tenant_result.fetchone()
        tenant_uuid = tenant_row[0] if tenant_row else None

        # Ensure user exists in users table (required for FK)
        from sqlalchemy import text as sa_text2
        user_exists = await db.execute(
            sa_text2("SELECT id FROM users WHERE id = :uid LIMIT 1"),
            {"uid": str(user_id)}
        )
        if not user_exists.fetchone():
            # Create user record if missing
            await db.execute(
                sa_text2("""
                    INSERT INTO users (id, tenant_id, is_phone_verified, created_at, updated_at)
                    VALUES (:uid, :tid, true, NOW(), NOW())
                    ON CONFLICT (id) DO NOTHING
                """),
                {"uid": str(user_id), "tid": str(tenant_uuid)}
            )
            await db.flush()

        profile = UserProfile(
            id=uuid.uuid4(),
            tenant_id=tenant_uuid,
            user_id=user_id,
            first_name="",
            last_name="",
        )
        db.add(profile)
        await db.flush()
        logger.info("profile_auto_created", user_id=str(user_id))

    update_data = payload.model_dump(exclude_none=True)
    for key, value in update_data.items():
        setattr(profile, key, value)

    profile.completeness_score = compute_profile_completeness(profile)
    await db.flush()
    await db.refresh(profile)

    logger.info("profile_updated", user_id=str(user_id))
    return APIResponse(success=True, data=ProfileRead.model_validate(profile, from_attributes=True))


@router.post("/photos/upload-url", response_model=APIResponse[dict])
async def get_photo_upload_url(
    content_type: str = Query(..., pattern=r"^image/(jpeg|jpg|png|webp)$"),
    current_user: Annotated[dict, Depends(get_current_user)] = None,
    tenant_slug: str = Depends(get_current_tenant_slug),
):
    """Returns a pre-signed S3 PUT URL for direct browser upload."""
    ext_map = {
        "image/jpeg": "jpg",
        "image/jpg": "jpg",
        "image/png": "png",
        "image/webp": "webp",
    }
    ext = ext_map.get(content_type, "jpg")
    user_id = current_user.get("sub", "unknown")

    result = generate_upload_url(
        tenant_slug=tenant_slug,
        user_id=user_id,
        media_type="photo",
        content_type=content_type,
        file_extension=ext,
    )
    return APIResponse(success=True, data=result)


@router.post("/voice-note/upload-url", response_model=APIResponse[dict])
async def get_voice_upload_url(
    content_type: str = Query(..., pattern=r"^audio/(mpeg|ogg|webm|mp4)$"),
    current_user: Annotated[dict, Depends(get_current_user)] = None,
    tenant_slug: str = Depends(get_current_tenant_slug),
):
    user_id = current_user.get("sub", "unknown")
    ext_map = {"audio/mpeg": "mp3", "audio/ogg": "ogg", "audio/webm": "webm", "audio/mp4": "m4a"}
    result = generate_upload_url(
        tenant_slug=tenant_slug,
        user_id=user_id,
        media_type="voice",
        content_type=content_type,
        file_extension=ext_map.get(content_type, "mp3"),
    )
    return APIResponse(success=True, data=result)
