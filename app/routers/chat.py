"""
Real-time chat — WebSocket + REST endpoints.
WebSocket /ws/chat/{thread_id}   — persistent connection, JWT auth via query param
GET       /api/v1/chats           — list all threads for current user
GET       /api/v1/chats/{id}/messages — paginated message history
POST      /api/v1/chats/{id}/messages — send message (fallback REST)
"""
import json
import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db, AsyncSessionLocal
from app.core.logging import get_logger
from app.core.security import get_current_user, _decode_token
from app.models.match import ChatThread, Message, MessageType
from app.schemas.common import APIResponse, PaginatedResponse
from app.schemas.match import ChatThreadRead, MessageRead, SendMessageRequest

router = APIRouter(tags=["chat"])
logger = get_logger(__name__)

# In-process connection registry — works single-instance.
# Replace with Redis pub/sub for multi-instance (Sprint 3).
_connections: dict[str, list[WebSocket]] = {}  # thread_id → [sockets]


class ConnectionManager:
    def add(self, thread_id: str, ws: WebSocket) -> None:
        _connections.setdefault(thread_id, []).append(ws)

    def remove(self, thread_id: str, ws: WebSocket) -> None:
        if thread_id in _connections:
            _connections[thread_id] = [s for s in _connections[thread_id] if s is not ws]

    async def broadcast(self, thread_id: str, data: dict, exclude: WebSocket | None = None) -> None:
        for ws in _connections.get(thread_id, []):
            if ws is not exclude:
                try:
                    await ws.send_json(data)
                except Exception:
                    pass


manager = ConnectionManager()


@router.websocket("/ws/chat/{thread_id}")
async def websocket_chat(
    websocket: WebSocket,
    thread_id: str,
    token: str = Query(...),
):
    """
    WebSocket endpoint for real-time chat.
    Auth: JWT passed as ?token= query param (headers not supported by browser WS API).
    Protocol:
      Client sends: {"type": "message", "content": "...", "encryption_key_id": "..."}
      Server broadcasts: {"type": "message", "id": "...", "sender_id": "...", ...}
      Client sends: {"type": "read", "message_id": "..."}
    """
    try:
        claims = _decode_token(token)
    except HTTPException:
        await websocket.close(code=4001)
        return

    sender_id = claims.get("sub")
    await websocket.accept()
    manager.add(thread_id, websocket)
    logger.info("ws_connected", user=sender_id, thread=thread_id)

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "detail": "Invalid JSON"})
                continue

            msg_type = data.get("type")

            if msg_type == "message":
                saved = await _persist_message(
                    thread_id=thread_id,
                    sender_id=sender_id,
                    payload=data,
                )
                await manager.broadcast(
                    thread_id,
                    {
                        "type": "message",
                        "id": str(saved.id),
                        "sender_id": sender_id,
                        "encrypted_content": saved.encrypted_content,
                        "encryption_key_id": saved.encryption_key_id,
                        "message_type": saved.message_type,
                        "created_at": saved.created_at.isoformat(),
                    },
                )

            elif msg_type == "read":
                await _mark_read(data.get("message_id"), sender_id)
                await manager.broadcast(
                    thread_id,
                    {"type": "read", "message_id": data.get("message_id"), "reader_id": sender_id},
                    exclude=websocket,
                )

            elif msg_type == "typing":
                await manager.broadcast(
                    thread_id,
                    {"type": "typing", "user_id": sender_id},
                    exclude=websocket,
                )

    except WebSocketDisconnect:
        manager.remove(thread_id, websocket)
        logger.info("ws_disconnected", user=sender_id, thread=thread_id)


async def _persist_message(thread_id: str, sender_id: str, payload: dict) -> Message:
    async with AsyncSessionLocal() as db:
        msg = Message(
            tenant_id=uuid.uuid4(),  # resolved in Sprint 2
            thread_id=uuid.UUID(thread_id),
            sender_id=uuid.UUID(sender_id),
            message_type=MessageType(payload.get("message_type", "text")),
            encrypted_content=payload.get("content"),
            encryption_key_id=payload.get("encryption_key_id"),
        )
        db.add(msg)
        await db.commit()
        await db.refresh(msg)
        return msg


async def _mark_read(message_id: str | None, reader_id: str) -> None:
    if not message_id:
        return
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Message).where(Message.id == uuid.UUID(message_id))
        )
        msg = result.scalar_one_or_none()
        if msg and str(msg.sender_id) != reader_id:
            msg.read_at = datetime.now(timezone.utc)
            await db.commit()


@router.get("/chats", response_model=PaginatedResponse[ChatThreadRead])
async def list_threads(
    page: int = 1,
    limit: int = 20,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user: Annotated[dict, Depends(get_current_user)] = None,
):
    try:
        user_id = uuid.UUID(current_user["sub"])
    except (ValueError, AttributeError):
        from app.schemas.common import PaginatedResponse as PR
        return PR(items=[], total=0, page=page, pages=0)
    offset = (page - 1) * limit

    result = await db.execute(
        select(ChatThread)
        .where(
            or_(ChatThread.user_a_id == user_id, ChatThread.user_b_id == user_id),
            ChatThread.is_active.is_(True),
            ChatThread.deleted_at.is_(None),
        )
        .order_by(ChatThread.last_message_at.desc().nullslast())
        .offset(offset)
        .limit(limit)
    )
    threads = result.scalars().all()
    return PaginatedResponse.create(
        [ChatThreadRead.model_validate(t) for t in threads], len(threads), page, limit
    )


@router.get("/chats/{thread_id}/messages", response_model=PaginatedResponse[MessageRead])
async def get_messages(
    thread_id: uuid.UUID,
    page: int = 1,
    limit: int = 50,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user: Annotated[dict, Depends(get_current_user)] = None,
):
    offset = (page - 1) * limit
    result = await db.execute(
        select(Message)
        .where(Message.thread_id == thread_id, Message.deleted_at.is_(None))
        .order_by(Message.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    messages = result.scalars().all()
    return PaginatedResponse.create(
        [MessageRead.model_validate(m) for m in messages], len(messages), page, limit
    )
