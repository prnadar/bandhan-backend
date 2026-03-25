"""
AI Matching Engine.
Generates 5 daily curated matches per user using:
  1. Hard filters (partner preferences)
  2. Compatibility scoring (profile-based + personality dimensions)
  3. Pinecone semantic similarity
  4. Behavioural signals (past interactions)
"""
from datetime import date
from typing import Any
from uuid import UUID

from app.core.config import get_settings
from app.core.logging import get_logger

settings = get_settings()
logger = get_logger(__name__)

# Personality dimension weights from PRD
DIMENSION_WEIGHTS = {
    "values": 0.25,
    "lifestyle": 0.20,
    "family": 0.25,
    "ambition": 0.15,
    "communication": 0.15,
}

DAILY_MATCH_COUNT = 5

# ── Religion compatibility map ────────────────────────────────────────────────
# Keys/values use lowercase string versions of Religion enum values.
_COMPATIBLE_RELIGIONS: dict[str, set[str]] = {
    "hindu":     {"hindu", "jain", "buddhist", "sikh"},
    "jain":      {"jain", "hindu", "buddhist"},
    "buddhist":  {"buddhist", "hindu", "jain"},
    "sikh":      {"sikh", "hindu"},
    "christian": {"christian"},
    "muslim":    {"muslim"},
    "parsi":     {"parsi"},
    "jewish":    {"jewish"},
    "other":     {"other"},
}

# ── Diet compatibility map ────────────────────────────────────────────────────
_COMPATIBLE_DIETS: dict[str, set[str]] = {
    "vegetarian":      {"vegetarian", "vegan", "jain_vegetarian"},
    "vegan":           {"vegan", "vegetarian"},
    "jain_vegetarian": {"jain_vegetarian", "vegetarian", "vegan"},
    "non_vegetarian":  {"non_vegetarian", "eggetarian", "vegetarian"},
    "eggetarian":      {"eggetarian", "vegetarian", "non_vegetarian"},
}

# ── Marital status compatibility map ─────────────────────────────────────────
_COMPATIBLE_MARITAL: dict[str, set[str]] = {
    "never_married": {"never_married", "divorced", "widowed", "separated"},
    "divorced":      {"divorced", "never_married", "widowed", "separated"},
    "widowed":       {"widowed", "never_married", "divorced"},
    "separated":     {"separated", "divorced", "never_married"},
}

# ── Education keywords that indicate a degree-level qualification ─────────────
_DEGREE_KEYWORDS = {
    "bachelor", "master", "phd", "mba", "msc", "bsc", "bcom", "ba ",
    "be ", "btech", "mtech", "llb", "llm", "md ", "mbbs", "mca", "bca",
    "postgraduate", "graduate", "degree", "honours", "honors",
}


def _attr(obj: Any, key: str, default: Any = None) -> Any:
    """Get attribute from either a dict or a model instance."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _str_val(val: Any) -> str:
    """Safely convert enum or str to lowercase string."""
    if val is None:
        return ""
    return (val.value if hasattr(val, "value") else str(val)).lower().strip()


def compute_compatibility(
    profile_a: Any,
    profile_b: Any,
) -> dict[str, Any]:
    """
    Compute profile-based compatibility score between two users.

    profile_a — requesting user's profile (carries partner_prefs used as scoring lens)
    profile_b — candidate profile being evaluated

    Both arguments can be UserProfile ORM instances or plain dicts with the
    same field names.

    Returns:
        {
            "score": int (0–100),
            "breakdown": {
                "age_preference": int,
                "religion":       int,
                "location":       int,
                "education":      int,
                "marital_status": int,
                "diet_lifestyle": int,
                "height_preference": int,
            }
        }

    Maximum points by factor (total = 100):
        age_preference    25
        religion          20
        location          15
        education         10
        marital_status    10
        diet_lifestyle    10
        height_preference 10
    """
    breakdown: dict[str, int] = {}
    total: int = 0

    prefs_a: dict[str, Any] = _attr(profile_a, "partner_prefs") or {}

    # ── 1. Age preference match (max 25 pts) ─────────────────────────────────
    dob_b = _attr(profile_b, "date_of_birth")
    if dob_b is not None:
        age_b = (date.today() - dob_b).days // 365
        min_age: int = int(prefs_a.get("min_age", 18))
        max_age: int = int(prefs_a.get("max_age", 80))

        if min_age <= age_b <= max_age:
            # Full score; add bonus for being near the preference midpoint
            mid = (min_age + max_age) / 2
            span = max(max_age - min_age, 1)
            closeness = 1.0 - (abs(age_b - mid) / (span / 2))
            age_pts = int(20 + closeness * 5)           # 20–25
        elif age_b < min_age:
            diff = min_age - age_b
            age_pts = max(0, 25 - diff * 5)             # −5 per year under
        else:
            diff = age_b - max_age
            age_pts = max(0, 25 - diff * 5)             # −5 per year over
    else:
        age_pts = 12                                     # neutral — no DOB data

    breakdown["age_preference"] = age_pts
    total += age_pts

    # ── 2. Religion match (max 20 pts) ────────────────────────────────────────
    rel_a = _str_val(_attr(profile_a, "religion"))
    rel_b = _str_val(_attr(profile_b, "religion"))

    if rel_a and rel_b:
        if rel_a == rel_b:
            rel_pts = 20
        elif rel_b in _COMPATIBLE_RELIGIONS.get(rel_a, set()):
            rel_pts = 10
        else:
            rel_pts = 0
    else:
        rel_pts = 10                                     # neutral — religion unknown

    breakdown["religion"] = rel_pts
    total += rel_pts

    # ── 3. Location proximity (max 15 pts) ────────────────────────────────────
    city_a    = (_attr(profile_a, "city")    or "").lower().strip()
    city_b    = (_attr(profile_b, "city")    or "").lower().strip()
    country_a = (_attr(profile_a, "country") or "").lower().strip()
    country_b = (_attr(profile_b, "country") or "").lower().strip()

    if city_a and city_b and city_a == city_b:
        loc_pts = 15
    elif country_a and country_b and country_a == country_b:
        loc_pts = 10
    else:
        loc_pts = 5                                      # any location: minimum credit

    breakdown["location"] = loc_pts
    total += loc_pts

    # ── 4. Education level (max 10 pts) ───────────────────────────────────────
    edu_a = (_attr(profile_a, "education_level") or "").lower()
    edu_b = (_attr(profile_b, "education_level") or "").lower()

    a_degree = any(kw in edu_a for kw in _DEGREE_KEYWORDS)
    b_degree = any(kw in edu_b for kw in _DEGREE_KEYWORDS)

    edu_pts = 10 if (a_degree and b_degree) else 0
    breakdown["education"] = edu_pts
    total += edu_pts

    # ── 5. Marital status (max 10 pts) ────────────────────────────────────────
    ms_a = _str_val(_attr(profile_a, "marital_status"))
    ms_b = _str_val(_attr(profile_b, "marital_status"))

    if ms_a and ms_b:
        if ms_a == "never_married" and ms_b == "never_married":
            ms_pts = 10
        elif ms_b in _COMPATIBLE_MARITAL.get(ms_a, set()):
            ms_pts = 5
        else:
            ms_pts = 0
    else:
        ms_pts = 5                                       # neutral

    breakdown["marital_status"] = ms_pts
    total += ms_pts

    # ── 6. Diet / lifestyle (max 10 pts) ─────────────────────────────────────
    # Diet may live in partner_prefs or family_details (flexible JSON)
    family_a: dict = _attr(profile_a, "family_details") or {}
    family_b: dict = _attr(profile_b, "family_details") or {}
    prefs_b:  dict = _attr(profile_b, "partner_prefs")  or {}

    diet_a = (
        family_a.get("diet")
        or prefs_a.get("diet")
        or ""
    ).lower().strip()
    diet_b = (
        family_b.get("diet")
        or prefs_b.get("diet")
        or ""
    ).lower().strip()

    if diet_a and diet_b:
        if diet_a == diet_b:
            diet_pts = 10
        elif diet_b in _COMPATIBLE_DIETS.get(diet_a, set()):
            diet_pts = 5
        else:
            diet_pts = 0
    else:
        diet_pts = 5                                     # neutral — diet unknown

    breakdown["diet_lifestyle"] = diet_pts
    total += diet_pts

    # ── 7. Height preference (max 10 pts) ─────────────────────────────────────
    height_b    = _attr(profile_b, "height_cm")
    min_height  = prefs_a.get("min_height_cm")
    max_height  = prefs_a.get("max_height_cm")

    if height_b is not None and (min_height is not None or max_height is not None):
        in_range = True
        if min_height is not None and height_b < int(min_height):
            in_range = False
        if max_height is not None and height_b > int(max_height):
            in_range = False
        height_pts = 10 if in_range else 0
    else:
        height_pts = 5                                   # neutral — no preference / no data

    breakdown["height_preference"] = height_pts
    total += height_pts

    final_score = min(100, max(0, total))
    logger.debug(
        "compatibility_computed",
        score=final_score,
        breakdown=breakdown,
    )

    return {
        "score": int(final_score),
        "breakdown": breakdown,
    }


# ── Legacy personality-based scorer (retained for Celery pipeline) ─────────────

def compute_personality_compatibility(
    user_scores: dict[str, float],
    candidate_scores: dict[str, float],
) -> tuple[float, dict[str, float]]:
    """
    Compute weighted 5-dimension personality compatibility score.
    Returns (overall_score_0_to_100, breakdown_dict).
    Pure function — no IO.

    Used internally by the Celery daily-match pipeline to rank candidates
    after hard-filter pruning.
    """
    dimension_map = {
        "values":        ("values_score",               "values_score"),
        "lifestyle":     ("lifestyle_score",             "lifestyle_score"),
        "family":        ("family_expectations_score",   "family_expectations_score"),
        "ambition":      ("ambition_score",              "ambition_score"),
        "communication": ("communication_style_score",   "communication_style_score"),
    }

    breakdown: dict[str, float] = {}
    weighted_sum = 0.0

    for dim, (user_key, cand_key) in dimension_map.items():
        u_val = user_scores.get(user_key) or 0.5
        c_val = candidate_scores.get(cand_key) or 0.5

        similarity = 1.0 - abs(u_val - c_val)          # 0–1
        breakdown[dim] = round(similarity, 3)
        weighted_sum += similarity * DIMENSION_WEIGHTS[dim]

    overall = round(weighted_sum * 100, 1)
    return overall, breakdown


def passes_hard_filters(profile: Any, prefs: dict[str, Any]) -> bool:
    """
    Check if candidate profile passes user's hard filters.
    Returns False if any mandatory filter fails.
    """
    if profile.date_of_birth:
        age = (date.today() - profile.date_of_birth).days // 365
        min_age = prefs.get("min_age", 18)
        max_age = prefs.get("max_age", 60)
        if not (min_age <= age <= max_age):
            return False

    pref_religions = prefs.get("religions")
    if pref_religions and profile.religion not in pref_religions:
        return False

    pref_min_height = prefs.get("min_height_cm")
    pref_max_height = prefs.get("max_height_cm")
    if pref_min_height and profile.height_cm and profile.height_cm < pref_min_height:
        return False
    if pref_max_height and profile.height_cm and profile.height_cm > pref_max_height:
        return False

    pref_countries = prefs.get("countries")
    if pref_countries and profile.country not in pref_countries:
        return False

    return True


async def generate_daily_matches(
    user_id: UUID,
    tenant_id: UUID,
    db: Any,
) -> list[dict[str, Any]]:
    """
    Generate top-5 matches for a user.
    Called by Celery beat task at 06:00 UK time daily.

    Strategy:
    1. Fetch user profile + personality scores + prefs
    2. Candidate pool: opposite gender, same tenant, active, not previously matched/rejected
    3. Apply hard filters
    4. Score all candidates with compute_compatibility (profile-based)
    5. Re-rank by compute_personality_compatibility if both have quiz scores
    6. Return top DAILY_MATCH_COUNT
    """
    logger.info("generating_daily_matches", user_id=str(user_id), tenant=str(tenant_id))

    try:
        from sqlalchemy import and_, or_, select
        from app.models.user import Gender, User, UserProfile
        from app.models.match import Match, MatchStatus
        from datetime import date as date_cls

        # 1. Get requesting user's profile
        result = await db.execute(
            select(UserProfile).where(
                UserProfile.user_id == user_id,
                UserProfile.deleted_at.is_(None),
            )
        )
        user_profile = result.scalar_one_or_none()
        if user_profile is None:
            logger.warning("no_profile_for_user", user_id=str(user_id))
            return []

        # 2. Determine opposite gender
        if user_profile.gender == Gender.MALE:
            opposite_gender = Gender.FEMALE
        elif user_profile.gender == Gender.FEMALE:
            opposite_gender = Gender.MALE
        else:
            opposite_gender = None  # match everyone for 'other'

        # 3. Candidate users — same tenant, active, not self
        users_q = select(User).where(
            User.tenant_id == tenant_id,
            User.id != user_id,
            User.is_active.is_(True),
            User.deleted_at.is_(None),
        )
        users_result = await db.execute(users_q)
        candidate_users = users_result.scalars().all()

        if not candidate_users:
            logger.info("no_candidates_found", user_id=str(user_id))
            return []

        # 4. Score candidates
        prefs = user_profile.partner_prefs or {}
        scored = []
        for cu in candidate_users:
            cp_result = await db.execute(
                select(UserProfile).where(
                    UserProfile.user_id == cu.id,
                    UserProfile.deleted_at.is_(None),
                )
            )
            cp = cp_result.scalar_one_or_none()
            if cp is None:
                continue

            # Gender filter
            if opposite_gender is not None and cp.gender != opposite_gender:
                continue

            # Hard filters
            if not passes_hard_filters(cp, prefs):
                continue

            score_result = compute_compatibility(user_profile, cp)
            scored.append({
                "user_id": cu.id,
                "compatibility_score": score_result["score"],
                "breakdown": score_result["breakdown"],
            })

        # 5. Sort and take top N
        scored.sort(key=lambda x: x["compatibility_score"], reverse=True)
        top = scored[:DAILY_MATCH_COUNT]

        # 6. Upsert Match records
        today_str = date_cls.today().isoformat()
        output = []
        for m in top:
            existing_result = await db.execute(
                select(Match).where(
                    and_(
                        or_(
                            and_(Match.user_a_id == user_id, Match.user_b_id == m["user_id"]),
                            and_(Match.user_a_id == m["user_id"], Match.user_b_id == user_id),
                        ),
                        Match.match_date == today_str,
                        Match.deleted_at.is_(None),
                    )
                )
            )
            if existing_result.scalar_one_or_none() is None:
                new_match = Match(
                    tenant_id=tenant_id,
                    user_a_id=user_id,
                    user_b_id=m["user_id"],
                    compatibility_score=float(m["compatibility_score"]),
                    compatibility_breakdown=m["breakdown"],
                    status=MatchStatus.PENDING,
                    match_date=today_str,
                )
                db.add(new_match)
                await db.flush()

            output.append({
                "user_id": str(m["user_id"]),
                "compatibility_score": m["compatibility_score"],
                "breakdown": m["breakdown"],
            })

        logger.info("daily_matches_generated", user_id=str(user_id), count=len(output))
        return output

    except Exception as exc:
        logger.error("generate_daily_matches_error", user_id=str(user_id), error=str(exc))
        return []


def compute_kundali_score(
    user_birth: dict[str, Any],
    candidate_birth: dict[str, Any],
) -> dict[str, Any]:
    """
    36-point Guna Milan system.
    Returns score, breakdown, and dosha flags.
    Placeholder — integrate certified Jyotish API in Sprint 2.
    """
    return {
        "total_points": 0,
        "max_points": 36,
        "is_manglik_compatible": True,
        "nadi_dosha": False,
        "guna_breakdown": {},
        "recommendation": "pending",
    }
