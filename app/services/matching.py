"""
AI Matching Engine.
Generates 5 daily curated matches per user using:
  1. Hard filters (partner preferences)
  2. Compatibility scoring (5 weighted dimensions)
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

# Dimension weights from PRD
DIMENSION_WEIGHTS = {
    "values": 0.25,
    "lifestyle": 0.20,
    "family": 0.25,
    "ambition": 0.15,
    "communication": 0.15,
}

DAILY_MATCH_COUNT = 5


def compute_compatibility(
    user_scores: dict[str, float],
    candidate_scores: dict[str, float],
) -> tuple[float, dict[str, float]]:
    """
    Compute weighted 5-dimension compatibility score.
    Returns (overall_score_0_to_100, breakdown_dict).
    Pure function — no IO.
    """
    dimension_map = {
        "values": ("values_score", "values_score"),
        "lifestyle": ("lifestyle_score", "lifestyle_score"),
        "family": ("family_expectations_score", "family_expectations_score"),
        "ambition": ("ambition_score", "ambition_score"),
        "communication": ("communication_style_score", "communication_style_score"),
    }

    breakdown: dict[str, float] = {}
    weighted_sum = 0.0

    for dim, (user_key, cand_key) in dimension_map.items():
        u_val = user_scores.get(user_key) or 0.5
        c_val = candidate_scores.get(cand_key) or 0.5

        # Similarity: 1 - |u - c| mapped to 0-1
        similarity = 1.0 - abs(u_val - c_val)
        breakdown[dim] = round(similarity, 3)
        weighted_sum += similarity * DIMENSION_WEIGHTS[dim]

    overall = round(weighted_sum * 100, 1)
    return overall, breakdown


def passes_hard_filters(profile: Any, prefs: dict[str, Any]) -> bool:
    """
    Check if candidate profile passes user's hard filters.
    Returns False if any mandatory filter fails.
    """
    # Age range
    if profile.date_of_birth:
        age = (date.today() - profile.date_of_birth).days // 365
        min_age = prefs.get("min_age", 18)
        max_age = prefs.get("max_age", 60)
        if not (min_age <= age <= max_age):
            return False

    # Religion filter
    pref_religions = prefs.get("religions")
    if pref_religions and profile.religion not in pref_religions:
        return False

    # Height filter
    pref_min_height = prefs.get("min_height_cm")
    pref_max_height = prefs.get("max_height_cm")
    if pref_min_height and profile.height_cm and profile.height_cm < pref_min_height:
        return False
    if pref_max_height and profile.height_cm and profile.height_cm > pref_max_height:
        return False

    # Location — country match for NRI users
    pref_countries = prefs.get("countries")
    if pref_countries and profile.country not in pref_countries:
        return False

    return True


async def generate_daily_matches(
    user_id: UUID,
    tenant_id: UUID,
    db,
) -> list[dict[str, Any]]:
    """
    Generate top-5 matches for a user.
    Called by Celery beat task at 05:30 IST daily.

    Strategy:
    1. Fetch user profile + personality scores + prefs
    2. Candidate pool: opposite gender, same tenant, active, not previously matched/rejected
    3. Apply hard filters
    4. Score all candidates
    5. Boost by Pinecone semantic similarity
    6. Return top DAILY_MATCH_COUNT
    """
    # NOTE: Full implementation queries the DB and Pinecone.
    # Stubbed here so the router compiles; Sprint 2 fills this in.
    logger.info("generating_daily_matches", user_id=str(user_id), tenant=str(tenant_id))
    return []


def compute_kundali_score(
    user_birth: dict[str, Any],
    candidate_birth: dict[str, Any],
) -> dict[str, Any]:
    """
    36-point Guna Milan system.
    Returns score, breakdown, and dosha flags.
    This is a placeholder — integrate certified Jyotish API in Sprint 2.
    """
    return {
        "total_points": 0,
        "max_points": 36,
        "is_manglik_compatible": True,
        "nadi_dosha": False,
        "guna_breakdown": {},
        "recommendation": "pending",
    }
