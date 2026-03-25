"""
Notifications router.

GET    /api/v1/notifications                      — paginated list, filter by read/unread
POST   /api/v1/notifications/read-all             — mark all notifications as read
POST   /api/v1/notifications/read/{notification_id} — mark one as read
DELETE /api/v1/notifications/{notification_id}    — soft-delete one
"""
import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.logging import get_logger
from app.core.security import get_current_user
from app.models.notification import Notification
from app.schemas.common import PaginatedResponse
from app.schemas.notification import NotificationRead

router = APIRouter(prefix="/notifications", tags=["notifications"])
logger = get_logger(__name__)


def _current_user_id(current_user: dict) -> uuid.UUID:
    """Extract the UUID from the JWT sub claim."""
    raw = current_user.get("sub") or current_user.get("user_id", "")
    try:
        return uuid.UUID(str(raw))
    except (ValueError, AttributeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid user identity in token",
        )


@router.get("", response_model=PaginatedResponse[NotificationRead])
async def list_notifications(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[dict, Depends(get_current_user)],
    is_read: bool | None = Query(
        default=None,
        description="Filter by read status. Omit to return all notifications.",
    ),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
):
    """Return the caller's notifications, newest first."""
    user_id = _current_user_id(current_user)
    offset = (page - 1) * limit

    base_filter = [
        Notification.user_id == user_id,
        Notification.deleted_at.is_(None),
    ]
    if is_read is not None:
        base_filter.append(Notification.is_read == is_read)

    # Total count
    count_q = select(func.count()).select_from(Notification).where(*base_filter)
    total: int = (await db.execute(count_q)).scalar_one()

    # Paginated rows
    rows_q = (
        select(Notification)
        .where(*base_filter)
        .order_by(Notification.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    rows = (await db.execute(rows_q)).scalars().all()

    items = [NotificationRead.model_validate(n, from_attributes=True) for n in rows]
    return PaginatedResponse.create(items=items, total=total, page=page, limit=limit)


@router.post("/read-all", status_code=status.HTTP_204_NO_CONTENT)
async def mark_all_read(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Mark every unread notification for the caller as read."""
    user_id = _current_user_id(current_user)
    now = datetime.now(tz=timezone.utc)

    await db.execute(
        update(Notification)
        .where(
            Notification.user_id == user_id,
            Notification.is_read == False,  # noqa: E712
            Notification.deleted_at.is_(None),
        )
        .values(is_read=True, read_at=now)
    )
    await db.flush()
    logger.info("notifications_read_all", user_id=str(user_id))


@router.post("/read/{notification_id}", response_model=NotificationRead)
async def mark_one_read(
    notification_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Mark a single notification as read."""
    user_id = _current_user_id(current_user)

    result = await db.execute(
        select(Notification).where(
            Notification.id == notification_id,
            Notification.user_id == user_id,
            Notification.deleted_at.is_(None),
        )
    )
    notification = result.scalar_one_or_none()
    if not notification:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")

    if not notification.is_read:
        notification.is_read = True
        notification.read_at = datetime.now(tz=timezone.utc)
        await db.flush()
        logger.info("notification_read", notification_id=str(notification_id), user_id=str(user_id))

    return NotificationRead.model_validate(notification, from_attributes=True)


@router.delete("/{notification_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_notification(
    notification_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Soft-delete a notification (sets deleted_at)."""
    user_id = _current_user_id(current_user)

    result = await db.execute(
        select(Notification).where(
            Notification.id == notification_id,
            Notification.user_id == user_id,
            Notification.deleted_at.is_(None),
        )
    )
    notification = result.scalar_one_or_none()
    if not notification:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")

    notification.deleted_at = datetime.now(tz=timezone.utc)
    await db.flush()
    logger.info(
        "notification_deleted", notification_id=str(notification_id), user_id=str(user_id)
    )
