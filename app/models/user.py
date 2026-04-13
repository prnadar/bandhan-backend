"""
User + UserProfile models.
User = auth identity.
UserProfile = all matrimony-specific details.
Separated so auth data and PII have different access patterns.
"""
import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import JSON, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import TenantModel

import enum


class SubscriptionTier(str, enum.Enum):
    FREE = "free"
    SILVER = "silver"
    GOLD = "gold"
    PLATINUM = "platinum"


class Gender(str, enum.Enum):
    MALE = "male"
    FEMALE = "female"
    OTHER = "other"


class MaritalStatus(str, enum.Enum):
    NEVER_MARRIED = "never_married"
    DIVORCED = "divorced"
    WIDOWED = "widowed"
    SEPARATED = "separated"


class Religion(str, enum.Enum):
    HINDU = "hindu"
    MUSLIM = "muslim"
    CHRISTIAN = "christian"
    SIKH = "sikh"
    JAIN = "jain"
    BUDDHIST = "buddhist"
    PARSI = "parsi"
    JEWISH = "jewish"
    OTHER = "other"


class User(TenantModel):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("tenant_id", "phone", name="uq_users_tenant_phone"),
        UniqueConstraint("tenant_id", "email", name="uq_users_tenant_email"),
        UniqueConstraint("tenant_id", "auth0_sub", name="uq_users_tenant_auth0"),
    )

    # Auth identity
    auth0_sub: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(15), nullable=True, index=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)

    # PII stored as hash for lookup; never store raw Aadhaar
    aadhaar_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    pan_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Trust & subscription
    trust_score: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    subscription_tier: Mapped[SubscriptionTier] = mapped_column(
        Enum(SubscriptionTier), nullable=False, default=SubscriptionTier.FREE
    )
    interests_remaining: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    contact_unlocks_remaining: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Flags
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_phone_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_email_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_profile_complete: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_active_at: Mapped[datetime | None] = mapped_column(nullable=True)

    # Relationships
    profile: Mapped["UserProfile"] = relationship(
        "UserProfile", back_populates="user", uselist=False, lazy="select"
    )
    verifications: Mapped[list["Verification"]] = relationship(
        "Verification", back_populates="user", lazy="select"
    )
    subscriptions: Mapped[list["Subscription"]] = relationship(
        "Subscription", back_populates="user", lazy="select"
    )


class UserProfile(TenantModel):
    __tablename__ = "profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )

    # Basic info
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)
    gender: Mapped[Gender | None] = mapped_column(Enum(Gender), nullable=True)
    marital_status: Mapped[MaritalStatus] = mapped_column(
        Enum(MaritalStatus), nullable=False, default=MaritalStatus.NEVER_MARRIED
    )

    # Location
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    state: Mapped[str | None] = mapped_column(String(100), nullable=True)
    country: Mapped[str] = mapped_column(String(100), nullable=False, default="India")
    pincode: Mapped[str | None] = mapped_column(String(10), nullable=True)

    # Religious / community
    religion: Mapped[Religion | None] = mapped_column(Enum(Religion), nullable=True)
    caste: Mapped[str | None] = mapped_column(String(200), nullable=True)
    sub_caste: Mapped[str | None] = mapped_column(String(200), nullable=True)
    mother_tongue: Mapped[str | None] = mapped_column(String(100), nullable=True)
    languages: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)

    # Physical
    height_cm: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    weight_kg: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    complexion: Mapped[str | None] = mapped_column(String(50), nullable=True)
    body_type: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Education & career
    education_level: Mapped[str | None] = mapped_column(String(100), nullable=True)
    education_field: Mapped[str | None] = mapped_column(String(200), nullable=True)
    college: Mapped[str | None] = mapped_column(String(200), nullable=True)
    occupation: Mapped[str | None] = mapped_column(String(200), nullable=True)
    employer: Mapped[str | None] = mapped_column(String(200), nullable=True)
    annual_income_inr: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # Bio
    bio: Mapped[str | None] = mapped_column(Text, nullable=True)
    about_family: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Media (stored as JSON arrays of S3 keys)
    photos: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )  # [{key, url, is_primary, approved}]
    intro_videos: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    voice_note_key: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Partner preferences (stored as flexible JSON)
    partner_prefs: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    # Family details
    family_details: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    # Kundali / astrology
    birth_time: Mapped[str | None] = mapped_column(String(10), nullable=True)  # HH:MM
    birth_place: Mapped[str | None] = mapped_column(String(200), nullable=True)
    is_manglik: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    kundali_data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    # NRI-specific
    visa_status: Mapped[str | None] = mapped_column(String(100), nullable=True)
    willing_to_relocate: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Profile completeness (0-100)
    completeness_score: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="profile")
