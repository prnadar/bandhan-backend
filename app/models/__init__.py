"""
Import all models here so Alembic auto-detects them.
"""
from app.models.base import TenantModel
from app.models.tenant import Tenant
from app.models.user import User, UserProfile, Gender, MaritalStatus, Religion, SubscriptionTier
from app.models.personality import PersonalityScore
from app.models.match import Match, Interest, ChatThread, Message, MatchStatus, InterestStatus, MessageType
from app.models.subscription import Subscription, CreditTransaction, SubscriptionStatus, PaymentGateway
from app.models.verification import Verification, VerificationType, VerificationStatus
from app.models.notification import Notification
from app.models.report import Report, ReportCategory, ReportStatus

__all__ = [
    "TenantModel",
    "Tenant",
    "User",
    "UserProfile",
    "Gender",
    "MaritalStatus",
    "Religion",
    "SubscriptionTier",
    "PersonalityScore",
    "Match",
    "Interest",
    "ChatThread",
    "Message",
    "MatchStatus",
    "InterestStatus",
    "MessageType",
    "Subscription",
    "CreditTransaction",
    "SubscriptionStatus",
    "PaymentGateway",
    "Verification",
    "VerificationType",
    "VerificationStatus",
    "Notification",
    "Report",
    "ReportCategory",
    "ReportStatus",
]
