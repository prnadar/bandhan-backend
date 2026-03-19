"""
Identity verification records.
Each verification type is a separate row.
Trust score is recomputed on save.
"""
import uuid
from datetime import datetime

import enum

from sqlalchemy import Enum, ForeignKey, JSON, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import TenantModel


class VerificationType(str, enum.Enum):
    MOBILE_OTP = "mobile_otp"
    EMAIL = "email"
    AADHAAR = "aadhaar"
    PAN = "pan"
    PHOTO_LIVENESS = "photo_liveness"
    DIGILOCKER_EDUCATION = "digilocker_education"
    LINKEDIN = "linkedin"
    EMPLOYMENT = "employment"


class VerificationStatus(str, enum.Enum):
    PENDING = "pending"
    IN_REVIEW = "in_review"
    VERIFIED = "verified"
    FAILED = "failed"
    EXPIRED = "expired"


class Verification(TenantModel):
    __tablename__ = "verifications"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "user_id", "verification_type", name="uq_verification_user_type"
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    verification_type: Mapped[VerificationType] = mapped_column(
        Enum(VerificationType), nullable=False
    )
    status: Mapped[VerificationStatus] = mapped_column(
        Enum(VerificationStatus), nullable=False, default=VerificationStatus.PENDING
    )

    # External system reference (DigiYatra ref, Twilio SID, etc.)
    external_ref_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    verified_at: Mapped[datetime | None] = mapped_column(nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(nullable=True)

    # Raw provider response (redacted of PII before storage)
    provider_response: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    # Trust score contribution for this verification type
    trust_points: Mapped[int] = mapped_column(nullable=False, default=0)

    user: Mapped["User"] = relationship("User", back_populates="verifications")
