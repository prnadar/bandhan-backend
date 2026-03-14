"""
Trust score computation.
Score breakdown (max 100):
  ID verification  : 40 pts  (Aadhaar=25, PAN=15)
  Photo liveness   : 20 pts
  Profile complete : 20 pts
  Response rate    : 10 pts
  Community standing: 10 pts  (deducted for reports)
"""
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


def compute_trust_score(
    verifications: list,
    completeness_score: int,
    response_rate: float,
    open_reports: int,
) -> int:
    """
    Pure function — computes trust score from component values.
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
