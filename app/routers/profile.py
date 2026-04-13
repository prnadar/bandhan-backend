"""
Profile router.
GET  /api/v1/profile/browse         — search/browse profiles
GET  /api/v1/profile/{user_id}
PUT  /api/v1/profile/{user_id}
POST /api/v1/profile/photos
POST /api/v1/profile/voice-note
DELETE /api/v1/profile/photos/{s3_key}
"""
import uuid
from datetime import date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.logging import get_logger
from app.core.rate_limit import BROWSE_LIMIT, limiter
from app.core.security import get_current_user
from app.core.tenancy import get_current_tenant_slug
from app.models.user import MaritalStatus, Religion, User, UserProfile
from app.schemas.common import APIResponse, PaginatedResponse
from app.schemas.user import ProfileCard, ProfileCreate, ProfileRead, ProfileUpdate
from app.services.storage import generate_photo_upload_signature, generate_upload_url
from app.services.trust_score import compute_profile_completeness, compute_trust_score

router = APIRouter(prefix="/profile", tags=["profile"])
logger = get_logger(__name__)


@router.get("/trust-score", response_model=APIResponse[dict])
async def get_trust_score(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """
    Returns the current user's trust score (0-100) and a per-signal breakdown.

    Breakdown signals:
      - email:   email verified (+20 pts)
      - mobile:  phone verified (+20 pts)
      - id:      Aadhaar or PAN verified (+30 pts)
      - profile: profile ≥80% complete (+20 pts)
      - linkedin: LinkedIn verified (+10 pts)
    """
    result = await compute_trust_score(current_user, db)
    return APIResponse(success=True, data=result)


@router.get("/browse", response_model=PaginatedResponse[ProfileCard])
@limiter.limit(BROWSE_LIMIT)
async def browse_profiles(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[dict, Depends(get_current_user)],
    tenant_slug: str = Depends(get_current_tenant_slug),
    # Age range
    min_age: int | None = Query(default=None, ge=18, le=100),
    max_age: int | None = Query(default=None, ge=18, le=100),
    # Filters
    religion: Religion | None = Query(default=None),
    location: str | None = Query(default=None, description="City or state (case-insensitive)"),
    education: str | None = Query(default=None, description="Partial match on education_level"),
    marital_status: MaritalStatus | None = Query(default=None),
    has_photo: bool | None = Query(default=None, description="If true, return only profiles with at least one photo"),
    # Pagination
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
):
    """
    Browse / search active profiles.

    - Filtered by caller's tenant.
    - Excludes caller's own profile.
    - Excludes soft-deleted profiles.
    - Ordered by created_at DESC (newest first).
    - Returns a minimal ProfileCard per result.
    """
    from sqlalchemy import text as sa_text

    # Resolve tenant UUID from slug
    tenant_result = await db.execute(
        sa_text("SELECT id FROM tenants WHERE slug = :slug LIMIT 1"),
        {"slug": tenant_slug},
    )
    tenant_row = tenant_result.fetchone()
    if not tenant_row:
        raise HTTPException(status_code=404, detail="Tenant not found")
    tenant_uuid = tenant_row[0]

    # Resolve calling user's UUID
    raw_sub = current_user.get("sub") or current_user.get("user_id", "")
    try:
        caller_id = uuid.UUID(str(raw_sub))
    except (ValueError, AttributeError):
        raise HTTPException(status_code=401, detail="Invalid user identity in token")

    offset = (page - 1) * limit

    # Build base query — join UserProfile → User to get trust_score
    base_q = (
        select(UserProfile, User)
        .join(User, User.id == UserProfile.user_id)
        .where(
            UserProfile.tenant_id == tenant_uuid,
            UserProfile.deleted_at.is_(None),
            User.deleted_at.is_(None),
            User.is_active == True,  # noqa: E712
            UserProfile.user_id != caller_id,
        )
    )

    # Age range — computed from date_of_birth
    today = date.today()
    if min_age is not None:
        max_dob = date(today.year - min_age, today.month, today.day)
        base_q = base_q.where(UserProfile.date_of_birth <= max_dob)
    if max_age is not None:
        min_dob = date(today.year - max_age - 1, today.month, today.day)
        base_q = base_q.where(UserProfile.date_of_birth >= min_dob)

    # Enum filters
    if religion is not None:
        base_q = base_q.where(UserProfile.religion == religion)
    if marital_status is not None:
        base_q = base_q.where(UserProfile.marital_status == marital_status)

    # Text filters (case-insensitive partial match)
    if location:
        loc_lower = f"%{location.lower()}%"
        from sqlalchemy import or_, func as sqlfunc
        base_q = base_q.where(
            or_(
                sqlfunc.lower(UserProfile.city).like(loc_lower),
                sqlfunc.lower(UserProfile.state).like(loc_lower),
            )
        )
    if education:
        from sqlalchemy import func as sqlfunc
        base_q = base_q.where(
            sqlfunc.lower(UserProfile.education_level).like(f"%{education.lower()}%")
        )

    # Photo filter — photos is a JSON array; non-empty means has_photo
    if has_photo is True:
        # JSON array length > 0 — works in PostgreSQL
        from sqlalchemy import cast, Integer, text as sa_text2
        base_q = base_q.where(
            sa_text2("jsonb_array_length(profiles.photos::jsonb) > 0")
        )
    elif has_photo is False:
        from sqlalchemy import text as sa_text3
        base_q = base_q.where(
            sa_text3("jsonb_array_length(profiles.photos::jsonb) = 0")
        )

    # Total count
    count_q = select(func.count()).select_from(base_q.subquery())
    total: int = (await db.execute(count_q)).scalar_one()

    # Paginated rows
    rows_q = base_q.order_by(UserProfile.created_at.desc()).offset(offset).limit(limit)
    rows = (await db.execute(rows_q)).all()

    def _age(dob: date | None) -> int | None:
        if dob is None:
            return None
        today_ = date.today()
        return today_.year - dob.year - ((today_.month, today_.day) < (dob.month, dob.day))

    def _primary_photo(photos: list[dict]) -> str | None:
        for p in photos:
            if p.get("is_primary"):
                return p.get("url")
        return photos[0].get("url") if photos else None

    cards: list[ProfileCard] = []
    for profile_row, user_row in rows:
        cards.append(
            ProfileCard(
                user_id=profile_row.user_id,
                first_name=profile_row.first_name,
                age=_age(profile_row.date_of_birth),
                city=profile_row.city,
                state=profile_row.state,
                occupation=profile_row.occupation,
                education_level=profile_row.education_level,
                religion=profile_row.religion,
                primary_photo_url=_primary_photo(profile_row.photos or []),
                trust_score=user_row.trust_score,
                completeness_score=profile_row.completeness_score,
            )
        )

    logger.info(
        "profiles_browsed",
        caller_id=str(caller_id),
        tenant=tenant_slug,
        total=total,
        page=page,
    )
    return PaginatedResponse.create(items=cards, total=total, page=page, limit=limit)


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
    """Returns signed Cloudinary upload params for direct client photo upload."""
    ext_map = {
        "image/jpeg": "jpg",
        "image/jpg": "jpg",
        "image/png": "png",
        "image/webp": "webp",
    }
    ext = ext_map.get(content_type, "jpg")
    user_id = current_user.get("sub", "unknown")

    result = generate_photo_upload_signature(
        tenant_slug=tenant_slug,
        user_id=user_id,
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
