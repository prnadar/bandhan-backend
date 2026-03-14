"""
Match, Interest, and Chat schemas.
"""
import uuid
from datetime import datetime
from typing import Any

from app.models.match import InterestStatus, MatchStatus, MessageType
from app.schemas.common import BaseSchema, TimestampedSchema
from app.schemas.user import ProfileCard


class MatchRead(TimestampedSchema):
    user_a_id: uuid.UUID
    user_b_id: uuid.UUID
    compatibility_score: float
    compatibility_breakdown: dict[str, float]
    status: MatchStatus
    match_date: str
    a_super_liked: bool
    b_super_liked: bool
    mutual_at: datetime | None
    # Profile card of the other user (populated by service layer)
    other_profile: ProfileCard | None = None


class DailyMatchFeed(BaseSchema):
    matches: list[MatchRead]
    refreshes_at: str  # ISO datetime of next refresh
    remaining_today: int


class SendInterestRequest(BaseSchema):
    match_id: uuid.UUID | None = None
    receiver_id: uuid.UUID
    is_super_interest: bool = False
    message: str | None = None


class InterestRead(TimestampedSchema):
    sender_id: uuid.UUID
    receiver_id: uuid.UUID
    status: InterestStatus
    is_super_interest: bool
    message: str | None
    responded_at: datetime | None
    sender_profile: ProfileCard | None = None


class ChatThreadRead(TimestampedSchema):
    user_a_id: uuid.UUID
    user_b_id: uuid.UUID
    is_active: bool
    last_message_at: datetime | None
    last_message_preview: str | None
    other_profile: ProfileCard | None = None
    unread_count: int = 0


class SendMessageRequest(BaseSchema):
    message_type: MessageType = MessageType.TEXT
    encrypted_content: str | None = None
    encryption_key_id: str | None = None
    media_key: str | None = None
    media_duration_seconds: int | None = None


class MessageRead(TimestampedSchema):
    thread_id: uuid.UUID
    sender_id: uuid.UUID
    message_type: MessageType
    encrypted_content: str | None
    encryption_key_id: str | None
    media_key: str | None
    delivered_at: datetime | None
    read_at: datetime | None
    is_flagged: bool


class QuizSubmitRequest(BaseSchema):
    responses: dict[str, int]  # question_id -> 1-5 Likert scale
    quiz_version: str = "v1"


class CompatibilityScoreRead(BaseSchema):
    overall: float
    breakdown: dict[str, float]
    kundali_score: int | None = None
