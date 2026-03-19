"""
Subscription + CreditPack models.
Supports Razorpay (India) and Stripe (diaspora).
"""
import uuid
from datetime import datetime

import enum

from sqlalchemy import BigInteger, Boolean, Enum, ForeignKey, Integer, JSON, Numeric, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import TenantModel


class SubscriptionStatus(str, enum.Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    PAST_DUE = "past_due"


class PaymentGateway(str, enum.Enum):
    RAZORPAY = "razorpay"
    STRIPE = "stripe"
    UPI = "upi"


class Subscription(TenantModel):
    __tablename__ = "subscriptions"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    plan: Mapped[str] = mapped_column(String(50), nullable=False)  # silver | gold | platinum
    status: Mapped[SubscriptionStatus] = mapped_column(
        Enum(SubscriptionStatus), nullable=False, default=SubscriptionStatus.ACTIVE
    )

    gateway: Mapped[PaymentGateway] = mapped_column(
        Enum(PaymentGateway), nullable=False, default=PaymentGateway.RAZORPAY
    )
    gateway_subscription_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    gateway_customer_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    amount_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")

    current_period_start: Mapped[datetime] = mapped_column(nullable=False)
    current_period_end: Mapped[datetime] = mapped_column(nullable=False)
    cancelled_at: Mapped[datetime | None] = mapped_column(nullable=True)

    # Feature limits for this subscription period
    monthly_interests: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    monthly_contacts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    monthly_video_calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    raw_webhook_data: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    user: Mapped["User"] = relationship("User", back_populates="subscriptions")


class CreditTransaction(TenantModel):
    """Audit trail for credit purchases and deductions."""

    __tablename__ = "credit_transactions"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(), nullable=False, index=True)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)  # positive=credit, negative=debit
    balance_after: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    reference_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    gateway: Mapped[str | None] = mapped_column(String(50), nullable=True)
