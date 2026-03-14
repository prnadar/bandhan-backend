"""
Subscription + Payments router.
POST /api/v1/subscriptions/create        — create Razorpay order / Stripe checkout
POST /api/v1/webhooks/razorpay           — Razorpay payment webhook
POST /api/v1/webhooks/stripe             — Stripe webhook
GET  /api/v1/subscriptions/limits        — current user's plan limits
"""
import hashlib
import hmac
import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.core.logging import get_logger
from app.core.security import get_current_user
from app.models.subscription import PaymentGateway, Subscription, SubscriptionStatus
from app.models.user import SubscriptionTier, User
from app.schemas.common import APIResponse
from app.schemas.subscription import (
    CreateSubscriptionRequest,
    FeatureLimits,
    RazorpayOrderResponse,
    StripeCheckoutResponse,
    SubscriptionRead,
)

router = APIRouter(tags=["subscriptions"])
settings = get_settings()
logger = get_logger(__name__)

PLAN_FEATURE_MAP = {
    "free": {"interests": 10, "contacts": 0, "video_calls": 0},
    "silver": {"interests": -1, "contacts": 5, "video_calls": 10},
    "gold": {"interests": -1, "contacts": -1, "video_calls": -1},
    "platinum": {"interests": -1, "contacts": -1, "video_calls": -1},
}


@router.post("/subscriptions/create", response_model=APIResponse[dict])
async def create_subscription(
    payload: CreateSubscriptionRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[dict, Depends(get_current_user)],
):
    if payload.gateway == PaymentGateway.RAZORPAY:
        return await _create_razorpay_order(payload, current_user)
    elif payload.gateway == PaymentGateway.STRIPE:
        return await _create_stripe_session(payload, current_user)
    raise HTTPException(status_code=400, detail="Unsupported payment gateway")


async def _create_razorpay_order(payload, current_user) -> APIResponse:
    if not settings.RAZORPAY_KEY_ID:
        raise HTTPException(status_code=503, detail="Payment gateway not configured")

    import razorpay  # type: ignore[import-untyped]

    price_map = {
        "silver": settings.SILVER_PRICE_INR,
        "gold": settings.GOLD_PRICE_INR,
        "platinum": settings.PLATINUM_PRICE_INR,
    }
    amount = price_map.get(payload.plan)
    if not amount:
        raise HTTPException(status_code=400, detail="Invalid plan")

    client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
    order = client.order.create(
        {"amount": amount, "currency": "INR", "receipt": f"sub_{current_user['sub'][:8]}"}
    )

    return APIResponse(
        success=True,
        data=RazorpayOrderResponse(
            order_id=order["id"],
            amount=amount,
            currency="INR",
            key_id=settings.RAZORPAY_KEY_ID,
        ).model_dump(),
    )


async def _create_stripe_session(payload, current_user) -> APIResponse:
    if not settings.STRIPE_SECRET_KEY:
        raise HTTPException(status_code=503, detail="Stripe not configured")

    import stripe  # type: ignore[import-untyped]

    stripe.api_key = settings.STRIPE_SECRET_KEY
    price_map = {
        "silver": "price_silver_usd",  # set real Stripe price IDs in env
        "gold": "price_gold_usd",
        "platinum": "price_platinum_usd",
    }
    session = stripe.checkout.Session.create(
        mode="subscription",
        line_items=[{"price": price_map[payload.plan], "quantity": 1}],
        success_url="https://bandhan.in/subscription/success",
        cancel_url="https://bandhan.in/subscription/cancel",
        client_reference_id=current_user["sub"],
    )
    return APIResponse(
        success=True,
        data=StripeCheckoutResponse(
            session_id=session.id, checkout_url=session.url
        ).model_dump(),
    )


@router.post("/webhooks/razorpay", status_code=200)
async def razorpay_webhook(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Verify Razorpay webhook signature, update subscription status."""
    body = await request.body()
    sig = request.headers.get("X-Razorpay-Signature", "")

    expected = hmac.new(
        settings.RAZORPAY_WEBHOOK_SECRET.encode(),
        body,
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected, sig):
        raise HTTPException(status_code=400, detail="Invalid webhook signature")

    event = json.loads(body)
    logger.info("razorpay_webhook", event_type=event.get("event"))

    # Sprint 5: handle payment.captured, subscription.activated, subscription.cancelled
    return {"status": "ok"}


@router.post("/webhooks/stripe", status_code=200)
async def stripe_webhook(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    body = await request.body()
    sig = request.headers.get("stripe-signature", "")

    if not settings.STRIPE_WEBHOOK_SECRET:
        raise HTTPException(status_code=503, detail="Stripe not configured")

    import stripe  # type: ignore[import-untyped]

    try:
        event = stripe.Webhook.construct_event(body, sig, settings.STRIPE_WEBHOOK_SECRET)
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid Stripe signature")

    logger.info("stripe_webhook", event_type=event.type)
    return {"status": "ok"}


@router.get("/subscriptions/limits", response_model=APIResponse[FeatureLimits])
async def get_feature_limits(
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Returns the current user's plan limits."""
    # In Sprint 2 this queries User + Subscription tables
    plan = "free"
    limits = PLAN_FEATURE_MAP.get(plan, PLAN_FEATURE_MAP["free"])

    return APIResponse(
        success=True,
        data=FeatureLimits(
            plan=plan,
            interests_remaining=limits["interests"],
            contacts_remaining=limits["contacts"],
            video_calls_remaining=limits["video_calls"],
            can_video_call=plan != "free",
            can_view_contact=plan in ("silver", "gold", "platinum"),
            can_incognito_browse=plan in ("gold", "platinum"),
            can_send_voice_note=True,
        ),
    )
