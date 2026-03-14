"""
Tenant model — one row per white-label client.
Each client gets their own branding, feature flags, and billing config.
"""
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, JSON, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), primary_key=True, default=uuid.uuid4
    )
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    domain: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)

    # White-label branding (stored as JSON for flexibility)
    branding: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=lambda: {
            "primary_color": "#8B1A1A",
            "accent_color": "#C9952A",
            "logo_url": None,
            "app_name": "Bandhan",
            "tagline": "The Sacred Bond",
        },
    )

    # Feature flags per tenant (e.g. disable kundali for secular bureaus)
    features: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=lambda: {
            "kundali_matching": True,
            "video_calls": True,
            "whatsapp_integration": True,
            "ai_matching": True,
            "bharat_mode": True,
            "family_mode": True,
            "nri_hub": True,
        },
    )

    # Billing
    plan: Mapped[str] = mapped_column(
        String(50), nullable=False, default="starter"
    )  # starter | growth | enterprise
    max_users: Mapped[int] = mapped_column(nullable=False, default=10_000)
    razorpay_account_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    stripe_account_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
