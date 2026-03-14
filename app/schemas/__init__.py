from app.schemas.common import APIResponse, PaginatedResponse, BaseSchema, TimestampedSchema
from app.schemas.auth import RegisterRequest, OTPVerifyRequest, TokenResponse
from app.schemas.user import UserCreate, UserRead, ProfileCreate, ProfileUpdate, ProfileRead, ProfileCard
from app.schemas.match import (
    MatchRead, DailyMatchFeed, SendInterestRequest, InterestRead,
    ChatThreadRead, SendMessageRequest, MessageRead, QuizSubmitRequest, CompatibilityScoreRead,
)
from app.schemas.subscription import (
    CreateSubscriptionRequest, SubscriptionRead,
    RazorpayOrderResponse, StripeCheckoutResponse, FeatureLimits,
)
