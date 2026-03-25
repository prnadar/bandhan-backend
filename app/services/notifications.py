"""
Notification service helpers.
Use create_notification() anywhere in the codebase to fan-out a notification.
"""
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.notification import Notification

logger = get_logger(__name__)


async def create_notification(
    *,
    user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    type: str,
    title: str,
    body: str,
    db: AsyncSession,
    action_url: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> Notification:
    """
    Insert a single notification row for a user.

    Parameters
    ----------
    user_id     : Recipient's user UUID.
    tenant_id   : Tenant isolation key.
    type        : One of the recognised notification type strings.
    title       : Short headline shown in the notification bell.
    body        : Full description / body text.
    action_url  : Optional deep-link path (e.g. "/interests", "/messages/abc").
    metadata    : Optional arbitrary JSON payload for the client.
    db          : Active async SQLAlchemy session (caller owns the transaction).

    Returns the newly created (unflushed) Notification ORM instance.
    Call ``await db.flush()`` / ``await db.commit()`` from the caller if needed.
    """
    notification = Notification(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        user_id=user_id,
        type=type,
        title=title,
        body=body,
        action_url=action_url,
        metadata=metadata,
        is_read=False,
        read_at=None,
    )
    db.add(notification)
    await db.flush()

    logger.info(
        "notification_created",
        notification_id=str(notification.id),
        user_id=str(user_id),
        type=type,
    )
    return notification
