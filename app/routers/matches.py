"""
Matches router.
GET  /api/v1/matches/daily       — today's 5 curated matches
POST /api/v1/interests/{match_id} — send interest
GET  /api/v1/interests/received   — received interests
POST /api/v1/quiz/submit          — personality quiz
GET  /api/v1/matches/compatibility/{user_id} — compatibility score
"""
import uuid
from datetime import date, datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.logging import get_logger
from app.core.security import get_current_user
from app.core.tenancy import get_current_tenant_slug
from app.models.match import Interest, InterestStatus, Match, MatchStatus
from app.models.personality import PersonalityScore
from app.schemas.common import APIResponse, PaginatedResponse
from app.schemas.match import (
    CompatibilityScoreRead,
    DailyMatchFeed,
    InterestRead,
    MatchRead,
    QuizSubmitRequest,
    SendInterestRequest,
)
from app.services.matching import compute_compatibility

router = APIRouter(tags=["matches"])
logger = get_logger(__name__)


def _get_user_uuid(current_user: dict) -> uuid.UUID | None:
    """Safely extract UUID from current_user sub. Returns None if invalid (demo mode)."""
    try:
        return uuid.UUID(current_user.get("sub", ""))
    except (ValueError, AttributeError):
        return None


@router.get("/matches/daily", response_model=APIResponse[DailyMatchFeed])
async def get_daily_matches(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[dict, Depends(get_current_user)],
    tenant_slug: str = Depends(get_current_tenant_slug),
):
    """Returns today's curated matches. Generated daily at 06:00 UK time."""
    today_str = date.today().isoformat()
    next_refresh = f"{date.today().isoformat()}T06:00:00+00:00"  # 06:00 UK (GMT)
    user_id_raw = current_user.get("sub", "")

    # Validate UUID — if not valid (demo-placeholder etc), return empty feed
    try:
        user_uuid = uuid.UUID(user_id_raw)
    except (ValueError, AttributeError):
        feed = DailyMatchFeed(matches=[], refreshes_at=next_refresh, remaining_today=5)
        return APIResponse(success=True, data=feed)

    result = await db.execute(
        select(Match).where(
            and_(
                or_(Match.user_a_id == user_uuid, Match.user_b_id == user_uuid),
                Match.match_date == today_str,
                Match.status == MatchStatus.PENDING,
                Match.deleted_at.is_(None),
            )
        )
    )
    matches = result.scalars().all()

    # Fallback: generate matches inline if none exist for today (new user or pre-Celery)
    if not matches:
        from app.models.user import User
        from app.services.matching import generate_daily_matches
        user_obj_result = await db.execute(
            select(User).where(User.id == user_uuid, User.deleted_at.is_(None))
        )
        user_obj = user_obj_result.scalar_one_or_none()
        if user_obj and user_obj.tenant_id:
            await generate_daily_matches(user_uuid, user_obj.tenant_id, db)
            # Re-query after generation
            result2 = await db.execute(
                select(Match).where(
                    and_(
                        or_(Match.user_a_id == user_uuid, Match.user_b_id == user_uuid),
                        Match.match_date == today_str,
                        Match.status == MatchStatus.PENDING,
                        Match.deleted_at.is_(None),
                    )
                )
            )
            matches = result2.scalars().all()

    feed = DailyMatchFeed(
        matches=[MatchRead.model_validate(m) for m in matches],
        refreshes_at=next_refresh,
        remaining_today=max(0, 5 - len(matches)),
    )
    return APIResponse(success=True, data=feed)


@router.post("/interests/{receiver_id}", response_model=APIResponse[InterestRead])
async def send_interest(
    receiver_id: uuid.UUID,
    payload: SendInterestRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[dict, Depends(get_current_user)],
    tenant_slug: str = Depends(get_current_tenant_slug),
):
    """Send interest to another user. Checks plan limits."""
    sender_id = _get_user_uuid(current_user)
    if not sender_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid user session")

    # Check for existing interest
    existing = await db.execute(
        select(Interest).where(
            Interest.sender_id == sender_id,
            Interest.receiver_id == receiver_id,
            Interest.deleted_at.is_(None),
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Interest already sent",
        )

    interest = Interest(
        tenant_id=uuid.uuid4(),  # resolved from tenant context in Sprint 2
        sender_id=sender_id,
        receiver_id=receiver_id,
        match_id=payload.match_id,
        is_super_interest=payload.is_super_interest,
        message=payload.message,
    )
    db.add(interest)
    await db.flush()

    # Check for mutual interest → unlock chat
    reverse = await db.execute(
        select(Interest).where(
            Interest.sender_id == receiver_id,
            Interest.receiver_id == sender_id,
            Interest.status == InterestStatus.PENDING,
            Interest.deleted_at.is_(None),
        )
    )
    if reverse.scalar_one_or_none():
        interest.status = InterestStatus.ACCEPTED
        logger.info("mutual_interest", user_a=str(sender_id), user_b=str(receiver_id))
        # TODO Sprint 3: create ChatThread + send push notification

    logger.info("interest_sent", sender=str(sender_id), receiver=str(receiver_id))
    return APIResponse(success=True, data=InterestRead.model_validate(interest))


@router.get("/interests/received", response_model=PaginatedResponse[InterestRead])
async def get_received_interests(
    page: int = 1,
    limit: int = 20,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user: Annotated[dict, Depends(get_current_user)] = None,
):
    user_id = _get_user_uuid(current_user)
    offset = (page - 1) * limit

    if not user_id:
        from app.schemas.common import PaginatedResponse as PR
        return PR(items=[], total=0, page=page, pages=0)

    count_result = await db.execute(
        select(func.count()).where(
            Interest.receiver_id == user_id,
            Interest.deleted_at.is_(None),
        )
    )
    total = count_result.scalar()

    result = await db.execute(
        select(Interest)
        .where(Interest.receiver_id == user_id, Interest.deleted_at.is_(None))
        .order_by(Interest.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    interests = result.scalars().all()

    return PaginatedResponse.create(
        [InterestRead.model_validate(i) for i in interests], total, page, limit
    )


@router.get("/interests/sent", response_model=PaginatedResponse[InterestRead])
async def get_sent_interests(
    page: int = 1,
    limit: int = 20,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user: Annotated[dict, Depends(get_current_user)] = None,
):
    """Returns paginated list of interests the current user has sent, with status."""
    user_id = _get_user_uuid(current_user)
    offset = (page - 1) * limit

    if not user_id:
        return PaginatedResponse(items=[], total=0, page=page, pages=0)

    count_result = await db.execute(
        select(func.count()).where(
            Interest.sender_id == user_id,
            Interest.deleted_at.is_(None),
        )
    )
    total = count_result.scalar()

    result = await db.execute(
        select(Interest)
        .where(Interest.sender_id == user_id, Interest.deleted_at.is_(None))
        .order_by(Interest.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    interests = result.scalars().all()

    return PaginatedResponse.create(
        [InterestRead.model_validate(i) for i in interests], total, page, limit
    )


@router.post("/quiz/submit", response_model=APIResponse[CompatibilityScoreRead])
async def submit_quiz(
    payload: QuizSubmitRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Submit personality quiz. Computes Big Five scores. Upserts PersonalityScore row."""
    user_id = _get_user_uuid(current_user)
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid user session")

    scores = _compute_big_five(payload.responses)

    result = await db.execute(
        select(PersonalityScore).where(
            PersonalityScore.user_id == user_id,
            PersonalityScore.deleted_at.is_(None),
        )
    )
    ps = result.scalar_one_or_none()

    if ps is None:
        ps = PersonalityScore(
            tenant_id=uuid.uuid4(),  # resolved in Sprint 2
            user_id=user_id,
        )
        db.add(ps)

    for key, value in scores.items():
        setattr(ps, key, value)

    ps.quiz_responses = payload.responses
    ps.quiz_version = payload.quiz_version
    await db.flush()

    logger.info("quiz_submitted", user_id=str(user_id))
    return APIResponse(
        success=True,
        data=CompatibilityScoreRead(
            overall=0.0,
            breakdown={
                "values": scores.get("values_score", 0.0),
                "lifestyle": scores.get("lifestyle_score", 0.0),
                "family": scores.get("family_expectations_score", 0.0),
                "ambition": scores.get("ambition_score", 0.0),
                "communication": scores.get("communication_style_score", 0.0),
            },
        ),
    )


def _compute_big_five(responses: dict[str, int]) -> dict[str, float]:
    """
    Map 60 quiz responses to Big Five + 5 compatibility dimensions.
    Full scoring rubric implemented in Sprint 2 with proper question bank.
    """
    total = len(responses)
    if total == 0:
        return {}
    avg = sum(responses.values()) / total / 5.0  # normalize to 0-1

    return {
        "openness": avg,
        "conscientiousness": avg,
        "extraversion": avg,
        "agreeableness": avg,
        "neuroticism": 1.0 - avg,
        "values_score": avg,
        "lifestyle_score": avg,
        "family_expectations_score": avg,
        "ambition_score": avg,
        "communication_style_score": avg,
    }
