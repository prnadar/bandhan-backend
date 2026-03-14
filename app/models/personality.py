"""
Personality scores — Big Five + Kundali quiz responses.
Stored separately so they can be updated independently of profile.
"""
import uuid
from typing import Any

from sqlalchemy import Float, JSON, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import TenantModel


class PersonalityScore(TenantModel):
    __tablename__ = "personality_scores"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), nullable=False, unique=True, index=True
    )

    # Big Five dimensions (0.0 – 1.0)
    openness: Mapped[float | None] = mapped_column(Float, nullable=True)
    conscientiousness: Mapped[float | None] = mapped_column(Float, nullable=True)
    extraversion: Mapped[float | None] = mapped_column(Float, nullable=True)
    agreeableness: Mapped[float | None] = mapped_column(Float, nullable=True)
    neuroticism: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Compatibility dimensions used in matching (0.0 – 1.0)
    values_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    lifestyle_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    family_expectations_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    ambition_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    communication_style_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Raw quiz responses (60 questions, stored for re-scoring if algorithm changes)
    quiz_responses: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )

    # Pinecone vector ID (for semantic similarity lookup)
    pinecone_vector_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    quiz_version: Mapped[str] = mapped_column(String(10), nullable=False, default="v1")
