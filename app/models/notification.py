"""
Notification model.
Stores in-app notifications for users.
Types: interest_received, interest_accepted, new_message, profile_viewed, system
"""
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    String,
    Text,
    Uuid,
)
from sqlalchemy import JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import TenantModel


class Notification(TenantModel):
    __tablename__ = "notifications"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Notification type — keep as string for flexibility
    type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )
    # Valid types: "interest_received", "interest_accepted",
    #              "new_message", "profile_viewed", "system"

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)

    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)

    # Deep-link URL for the notification, e.g. /interests, /messages/123
    action_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Arbitrary extra data (actor profile, match score, etc.)
    # NOTE: "metadata" is reserved by SQLAlchemy DeclarativeBase, so we use
    # the Python name "extra_data" but keep the DB column as "metadata".
    extra_data: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata", JSON, nullable=True
    )

    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
