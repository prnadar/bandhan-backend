"""
Report model — user reports another user for violations.
3 unresolved reports = automatic suspension pending review.
"""
import uuid
from datetime import datetime

import enum

from sqlalchemy import Boolean, Enum, JSON, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import TenantModel


class ReportCategory(str, enum.Enum):
    FAKE_PROFILE = "fake_profile"
    HARASSMENT = "harassment"
    INAPPROPRIATE_CONTENT = "inappropriate_content"
    SPAM = "spam"
    FRAUD = "fraud"
    ABUSIVE_LANGUAGE = "abusive_language"
    UNDERAGE = "underage"
    IMPERSONATION = "impersonation"
    PRIVACY_VIOLATION = "privacy_violation"
    SCAM = "scam"
    UNSOLICITED_CONTACT = "unsolicited_contact"
    OTHER = "other"


class ReportStatus(str, enum.Enum):
    OPEN = "open"
    UNDER_REVIEW = "under_review"
    RESOLVED_ACTION_TAKEN = "resolved_action_taken"
    RESOLVED_NO_ACTION = "resolved_no_action"
    DISMISSED = "dismissed"


class Report(TenantModel):
    __tablename__ = "reports"

    reporter_id: Mapped[uuid.UUID] = mapped_column(Uuid(), nullable=False, index=True)
    reported_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), nullable=False, index=True
    )

    category: Mapped[ReportCategory] = mapped_column(Enum(ReportCategory), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Evidence (message IDs, screenshot S3 keys)
    evidence: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    status: Mapped[ReportStatus] = mapped_column(
        Enum(ReportStatus), nullable=False, default=ReportStatus.OPEN, index=True
    )

    # Admin resolution
    admin_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(), nullable=True)
    admin_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(nullable=True)

    # Action taken
    action_taken: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # warning | temp_suspension | permanent_ban | content_removed | no_action
