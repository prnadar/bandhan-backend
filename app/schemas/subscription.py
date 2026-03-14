"""
Subscription and payment schemas.
"""
import uuid
from datetime import datetime

from app.models.subscription import PaymentGateway, SubscriptionStatus
from app.schemas.common import BaseSchema, TimestampedSchema


class CreateSubscriptionRequest(BaseSchema):
    plan: str  # silver | gold | platinum
    gateway: PaymentGateway = PaymentGateway.RAZORPAY
    currency: str = "INR"


class SubscriptionRead(TimestampedSchema):
    user_id: uuid.UUID
    plan: str
    status: SubscriptionStatus
    gateway: PaymentGateway
    amount_paise: int
    currency: str
    current_period_start: datetime
    current_period_end: datetime
    monthly_interests: int
    monthly_contacts: int
    monthly_video_calls: int


class RazorpayOrderResponse(BaseSchema):
    order_id: str
    amount: int
    currency: str
    key_id: str


class StripeCheckoutResponse(BaseSchema):
    session_id: str
    checkout_url: str


class CreditPackRequest(BaseSchema):
    pack_size: int  # 5 | 10 | 25 contacts


class FeatureLimits(BaseSchema):
    """Current user's plan limits and usage."""

    plan: str
    interests_remaining: int
    contacts_remaining: int
    video_calls_remaining: int
    can_video_call: bool
    can_view_contact: bool
    can_incognito_browse: bool
    can_send_voice_note: bool
