"""
Match, Interest, and Message models.
Match = AI-generated pair suggestion.
Interest = user A expresses interest in user B.
Message = chat message within an unlocked thread.
"""
import uuid
from datetime import datetime
from typing import Any

import enum

from sqlalchemy import Boolean, Enum, Float, Integer, JSON, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import TenantModel


class MatchStatus(str, enum.Enum):
    PENDING = "pending"       # shown in daily feed, no action yet
    INTERESTED = "interested" # one-sided interest sent
    MUTUAL = "mutual"         # both parties interested — chat unlocked
    REJECTED = "rejected"     # one party passed
    EXPIRED = "expired"       # 7 days with no action


class InterestStatus(str, enum.Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    WITHDRAWN = "withdrawn"


class MessageType(str, enum.Enum):
    TEXT = "text"
    VOICE = "voice"
    IMAGE = "image"
    ICEBREAKER = "icebreaker"
    SYSTEM = "system"


class Match(TenantModel):
    __tablename__ = "matches"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_a_id", "user_b_id", name="uq_matches_pair"),
    )

    user_a_id: Mapped[uuid.UUID] = mapped_column(Uuid(), nullable=False, index=True)
    user_b_id: Mapped[uuid.UUID] = mapped_column(Uuid(), nullable=False, index=True)

    # AI-generated compatibility score (0-100)
    compatibility_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    # Breakdown by dimension (weights from PRD)
    compatibility_breakdown: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=lambda: {
            "values": 0.0,         # 25%
            "lifestyle": 0.0,      # 20%
            "family": 0.0,         # 25%
            "ambition": 0.0,       # 15%
            "communication": 0.0,  # 15%
        },
    )

    status: Mapped[MatchStatus] = mapped_column(
        Enum(MatchStatus), nullable=False, default=MatchStatus.PENDING, index=True
    )

    # Which daily batch this match was generated for (YYYY-MM-DD)
    match_date: Mapped[str] = mapped_column(String(10), nullable=False, index=True)

    # Did either party super-like?
    a_super_liked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    b_super_liked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    mutual_at: Mapped[datetime | None] = mapped_column(nullable=True)


class Interest(TenantModel):
    __tablename__ = "interests"
    __table_args__ = (
        UniqueConstraint("tenant_id", "sender_id", "receiver_id", name="uq_interests_pair"),
    )

    sender_id: Mapped[uuid.UUID] = mapped_column(Uuid(), nullable=False, index=True)
    receiver_id: Mapped[uuid.UUID] = mapped_column(Uuid(), nullable=False, index=True)
    match_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(), nullable=True)

    status: Mapped[InterestStatus] = mapped_column(
        Enum(InterestStatus), nullable=False, default=InterestStatus.PENDING, index=True
    )
    is_super_interest: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    message: Mapped[str | None] = mapped_column(String(500), nullable=True)

    responded_at: Mapped[datetime | None] = mapped_column(nullable=True)


class ChatThread(TenantModel):
    __tablename__ = "chat_threads"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_a_id", "user_b_id", name="uq_thread_pair"),
    )

    user_a_id: Mapped[uuid.UUID] = mapped_column(Uuid(), nullable=False, index=True)
    user_b_id: Mapped[uuid.UUID] = mapped_column(Uuid(), nullable=False, index=True)
    match_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(), nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_message_at: Mapped[datetime | None] = mapped_column(nullable=True)
    last_message_preview: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # Family mode: family members added to thread
    family_participants: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list
    )  # [{user_id, role, added_at}]


class Message(TenantModel):
    __tablename__ = "messages"

    thread_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), nullable=False, index=True
    )
    sender_id: Mapped[uuid.UUID] = mapped_column(Uuid(), nullable=False, index=True)

    message_type: Mapped[MessageType] = mapped_column(
        Enum(MessageType), nullable=False, default=MessageType.TEXT
    )

    # Encrypted content — Bandhan cannot read this (Signal Protocol)
    encrypted_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    encryption_key_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # For voice/image messages
    media_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    media_duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Delivery state
    delivered_at: Mapped[datetime | None] = mapped_column(nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(nullable=True)

    is_deleted_for_sender: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_deleted_for_receiver: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # AI moderation
    moderation_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_flagged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    moderation_action: Mapped[str | None] = mapped_column(String(50), nullable=True)
