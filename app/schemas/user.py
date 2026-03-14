"""
User and UserProfile schemas.
"""
import uuid
from datetime import date, datetime
from typing import Any

from pydantic import EmailStr, field_validator

from app.models.user import Gender, MaritalStatus, Religion, SubscriptionTier
from app.schemas.common import BaseSchema, TimestampedSchema


class UserCreate(BaseSchema):
    phone: str
    email: EmailStr | None = None


class UserRead(TimestampedSchema):
    phone: str
    email: str | None
    trust_score: int
    subscription_tier: SubscriptionTier
    is_active: bool
    is_phone_verified: bool
    is_profile_complete: bool
    last_active_at: datetime | None


class ProfileCreate(BaseSchema):
    first_name: str
    last_name: str
    date_of_birth: date | None = None
    gender: Gender | None = None
    marital_status: MaritalStatus = MaritalStatus.NEVER_MARRIED
    city: str | None = None
    state: str | None = None
    country: str = "India"
    religion: Religion | None = None
    caste: str | None = None
    mother_tongue: str | None = None
    languages: list[str] = []
    height_cm: int | None = None
    education_level: str | None = None
    occupation: str | None = None
    annual_income_inr: int | None = None
    bio: str | None = None
    partner_prefs: dict[str, Any] = {}
    family_details: dict[str, Any] = {}
    birth_time: str | None = None
    birth_place: str | None = None


class ProfileUpdate(BaseSchema):
    first_name: str | None = None
    last_name: str | None = None
    date_of_birth: date | None = None
    gender: Gender | None = None
    city: str | None = None
    state: str | None = None
    country: str | None = None
    religion: Religion | None = None
    caste: str | None = None
    sub_caste: str | None = None
    mother_tongue: str | None = None
    languages: list[str] | None = None
    height_cm: int | None = None
    weight_kg: int | None = None
    education_level: str | None = None
    education_field: str | None = None
    college: str | None = None
    occupation: str | None = None
    employer: str | None = None
    annual_income_inr: int | None = None
    bio: str | None = None
    about_family: str | None = None
    partner_prefs: dict[str, Any] | None = None
    family_details: dict[str, Any] | None = None
    birth_time: str | None = None
    birth_place: str | None = None
    is_manglik: bool | None = None
    visa_status: str | None = None
    willing_to_relocate: bool | None = None


class ProfileRead(TimestampedSchema):
    user_id: uuid.UUID
    first_name: str
    last_name: str
    date_of_birth: date | None
    gender: Gender | None
    marital_status: MaritalStatus
    city: str | None
    state: str | None
    country: str
    religion: Religion | None
    caste: str | None
    mother_tongue: str | None
    languages: list[str]
    height_cm: int | None
    education_level: str | None
    occupation: str | None
    annual_income_inr: int | None
    bio: str | None
    photos: list[dict[str, Any]]
    completeness_score: int
    is_manglik: bool | None
    willing_to_relocate: bool


class ProfileCard(BaseSchema):
    """Minimal profile for match cards — respects privacy settings."""

    user_id: uuid.UUID
    first_name: str
    age: int | None
    city: str | None
    state: str | None
    occupation: str | None
    education_level: str | None
    religion: Religion | None
    primary_photo_url: str | None
    trust_score: int
    completeness_score: int
