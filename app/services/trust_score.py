"""
Trust score computation.

Legacy score breakdown (max 100):
  ID verification  : 40 pts  (Aadhaar=25, PAN=15)
  Photo liveness   : 20 pts
  Profile complete : 20 pts
  Response rate    : 10 pts
  Community standing: 10 pts  (deducted for reports)

API trust score (max 100) — simple per-signal model for /profile/trust-score:
  email_verified        : +20 pts
  phone_verified        : +20 pts
  id_document_verified  : +30 pts
  profile_complete      : +20 pts
  linkedin_verified     : +10 pts
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.verification import VerificationStatus, VerificationType

TRUST_WEIGHTS: dict[str, int] = {
    VerificationType.AADHAAR: 25,
    VerificationType.PAN: 15,
    VerificationType.PHOTO_LIVENESS: 20,
    VerificationType.DIGILOCKER_EDUCATION: 5,
    VerificationType.LINKEDIN: 5,
    VerificationType.EMPLOYMENT: 5,
}

MAX_PROFILE_COMPLETENESS_POINTS = 20
MAX_RESPONSE_RATE_POINTS = 10
MAX_COMMUNITY_POINTS = 10


def compute_trust_score_legacy(
    verifications: list,
    completeness_score: int,
    response_rate: float,
    open_reports: int,
) -> int:
    """
    Legacy pure function — computes trust score from component values.
    Returns clamped int 0-100.
    """
    verification_pts = sum(
        TRUST_WEIGHTS.get(v.verification_type, 0)
        for v in verifications
        if v.status == VerificationStatus.VERIFIED
    )

    profile_pts = int((completeness_score / 100) * MAX_PROFILE_COMPLETENESS_POINTS)

    response_pts = int(min(response_rate, 1.0) * MAX_RESPONSE_RATE_POINTS)

    # -3 pts per open unresolved report, minimum 0
    community_pts = max(0, MAX_COMMUNITY_POINTS - (open_reports * 3))

    total = verification_pts + profile_pts + response_pts + community_pts
    return max(0, min(100, total))


async def compute_trust_score(user, db: AsyncSession) -> dict:
    """
    API trust score for /profile/trust-score endpoint.

    Signal breakdown (max 100):
      email_verified        : +20 pts
      phone_verified        : +20 pts
      id_document_verified  : +30 pts  (Aadhaar or PAN verified)
      profile_complete      : +20 pts  (completeness_score >= 80)
      linkedin_verified     : +10 pts

    Returns:
        {
            "score": int,
            "breakdown": {
                "email": bool,
                "mobile": bool,
                "id": bool,
                "profile": bool,
                "linkedin": bool,
            }
        }
    """
    from app.models.user import User, UserProfile
    from app.models.verification import Verification

    # ── Fetch User row ────────────────────────────────────────────────────
    import uuid as _uuid
    try:
        user_uuid = _uuid.UUID(user.get("sub", "")) if isinstance(user, dict) else user.id
    except (ValueError, AttributeError):
        return {"score": 0, "breakdown": {"email": False, "mobile": False, "id": False, "profile": False, "linkedin": False}}

    user_result = await db.execute(
        select(User).where(User.id == user_uuid, User.deleted_at.is_(None))
    )
    user_row = user_result.scalar_one_or_none()

    if not user_row:
        return {"score": 0, "breakdown": {"email": False, "mobile": False, "id": False, "profile": False, "linkedin": False}}

    # ── Fetch verifications ───────────────────────────────────────────────
    verif_result = await db.execute(
        select(Verification).where(
            Verification.user_id == user_uuid,
            Verification.status == VerificationStatus.VERIFIED,
            Verification.deleted_at.is_(None),
        )
    )
    verified_types = {v.verification_type for v in verif_result.scalars().all()}

    # ── Fetch profile completeness ────────────────────────────────────────
    profile_result = await db.execute(
        select(UserProfile).where(
            UserProfile.user_id == user_uuid,
            UserProfile.deleted_at.is_(None),
        )
    )
    profile_row = profile_result.scalar_one_or_none()
    completeness = profile_row.completeness_score if profile_row else 0

    # ── Compute signals ───────────────────────────────────────────────────
    email_verified = bool(user_row.is_email_verified)
    phone_verified = bool(user_row.is_phone_verified)
    id_verified = (
        VerificationType.AADHAAR in verified_types
        or VerificationType.PAN in verified_types
    )
    profile_complete = completeness >= 80
    linkedin_verified = VerificationType.LINKEDIN in verified_types

    score = (
        (20 if email_verified else 0)
        + (20 if phone_verified else 0)
        + (30 if id_verified else 0)
        + (20 if profile_complete else 0)
        + (10 if linkedin_verified else 0)
    )

    return {
        "score": score,
        "breakdown": {
            "email": email_verified,
            "mobile": phone_verified,
            "id": id_verified,
            "profile": profile_complete,
            "linkedin": linkedin_verified,
        },
    }


def compute_profile_completeness(profile) -> int:
    """
    Compute % completeness of a UserProfile.
    Returns 0-100.
    """
    fields = [
        profile.first_name,
        profile.last_name,
        profile.date_of_birth,
        profile.gender,
        profile.city,
        profile.state,
        profile.religion,
        profile.mother_tongue,
        profile.height_cm,
        profile.education_level,
        profile.occupation,
        profile.bio,
        bool(profile.photos),
    ]
    filled = sum(1 for f in fields if f is not None and f != "" and f != [])
    return int((filled / len(fields)) * 100)
