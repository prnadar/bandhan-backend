"""
Notification schemas.
"""
import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from app.schemas.common import BaseSchema, TimestampedSchema

# All recognised notification types
NotificationType = Literal[
    "interest_received",
    "interest_accepted",
    "new_message",
    "profile_viewed",
    "system",
]


class NotificationCreate(BaseSchema):
    """Used internally by services to insert a notification."""

    user_id: uuid.UUID
    tenant_id: uuid.UUID
    type: str
    title: str
    body: str
    action_url: str | None = None
    extra_data: dict[str, Any] | None = None


class NotificationRead(BaseSchema):
    """Returned to the client."""

    id: uuid.UUID
    user_id: uuid.UUID
    type: str
    title: str
    body: str
    is_read: bool
    action_url: str | None
    extra_data: dict[str, Any] | None
    created_at: datetime
    read_at: datetime | None
