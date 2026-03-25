"""
Subscription + Payments router.

POST /api/v1/subscriptions/create-checkout   — create Stripe or Razorpay checkout
POST /api/v1/subscriptions/webhook/stripe    — Stripe webhook handler
POST /api/v1/subscriptions/webhook/razorpay  — Razorpay webhook handler
POST /api/v1/subscriptions/create            — legacy gateway-based create (kept for compat)
GET  /api/v1/subscriptions/limits            — current user's plan limits
"""
import base64
import hashlib
import hmac
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal

import requests as http_requests
from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.core.logging import get_logger
from app.core.security import get_current_user
from app.models.notification import Notification
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

PLAN_TIER_MAP: dict[str, SubscriptionTier] = {
    "silver": SubscriptionTier.SILVER,
    "gold": SubscriptionTier.GOLD,
    "platinum": SubscriptionTier.PLATINUM,
    "free": SubscriptionTier.FREE,
}

# ─────────────────────────────────────────────────────────────────────────────
# Request / response schemas (inline — avoids touching schemas/ for now)
# ─────────────────────────────────────────────────────────────────────────────

class CheckoutRequest(BaseModel):
    plan: Literal["silver", "gold", "platinum"]
    currency: Literal["GBP", "INR"]


class StripeCheckoutOut(BaseModel):
    checkout_url: str
    session_id: str


class RazorpayOrderOut(BaseModel):
    order_id: str
    amount: int
    currency: str
    key: str


# ─────────────────────────────────────────────────────────────────────────────
# Helpers — raw Stripe HTTP (no SDK)
# ─────────────────────────────────────────────────────────────────────────────

_STRIPE_BASE = "https://api.stripe.com/v1"


def _stripe_headers() -> dict[str, str]:
    """Basic-auth header using secret key as username."""
    encoded = base64.b64encode(f"{settings.STRIPE_SECRET_KEY}:".encode()).decode()
    return {
        "Authorization": f"Basic {encoded}",
        "Content-Type": "application/x-www-form-urlencoded",
    }


def _stripe_post(path: str, data: dict) -> dict:
    """
    POST to Stripe REST API using form-encoded body.
    Raises HTTPException on non-2xx responses.
    """
    resp = http_requests.post(
        f"{_STRIPE_BASE}{path}",
        headers=_stripe_headers(),
        data=data,
        timeout=15,
    )
    if resp.status_code >= 400:
        err = resp.json().get("error", {})
        logger.error("stripe_api_error", status=resp.status_code, message=err.get("message"))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Stripe error: {err.get('message', 'unknown error')}",
        )
    return resp.json()


def _build_stripe_line_item_params(plan: str) -> dict:
    """
    Build Stripe Checkout line_items[0] params for form-encoded POST.
    Uses inline price_data (no pre-created Price object required).
    """
    price_map = {
        "silver": settings.SILVER_PRICE_GBP,
        "gold": settings.GOLD_PRICE_GBP,
        "platinum": settings.PLATINUM_PRICE_GBP,
    }
    plan_names = {
        "silver": "Silver Plan",
        "gold": "Gold Plan",
        "platinum": "Platinum Plan",
    }
    return {
        "line_items[0][price_data][currency]": "gbp",
        "line_items[0][price_data][unit_amount]": str(price_map[plan]),
        "line_items[0][price_data][product_data][name]": plan_names[plan],
        "line_items[0][quantity]": "1",
    }


# ─────────────────────────────────────────────────────────────────────────────
# NEW: POST /subscriptions/create-checkout
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/subscriptions/create-checkout", response_model=APIResponse[dict])
async def create_checkout(
    payload: CheckoutRequest,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """
    Create a payment checkout session.
    - GBP → Stripe Checkout Session
    - INR → Razorpay Order
    """
    if payload.currency == "GBP":
        return await _checkout_stripe(payload, current_user)
    else:
        return await _checkout_razorpay(payload, current_user)


async def _checkout_stripe(payload: CheckoutRequest, current_user: dict) -> APIResponse:
    if not settings.STRIPE_SECRET_KEY:
        raise HTTPException(status_code=503, detail="Stripe not configured")

    user_id = current_user.get("sub", "")
    tenant_id = current_user.get("tenant_id", "")

    data: dict = {
        "mode": "payment",
        "success_url": "https://match4marriage.com/subscription?success=true",
        "cancel_url": "https://match4marriage.com/subscription",
        "metadata[user_id]": user_id,
        "metadata[plan]": payload.plan,
        "metadata[tenant_id]": str(tenant_id),
    }
    data.update(_build_stripe_line_item_params(payload.plan))

    session = _stripe_post("/checkout/sessions", data)

    logger.info(
        "stripe_checkout_created",
        session_id=session["id"],
        plan=payload.plan,
        user_id=user_id,
    )

    return APIResponse(
        success=True,
        data=StripeCheckoutOut(
            checkout_url=session["url"],
            session_id=session["id"],
        ).model_dump(),
    )


async def _checkout_razorpay(payload: CheckoutRequest, current_user: dict) -> APIResponse:
    if not settings.RAZORPAY_KEY_ID:
        raise HTTPException(status_code=503, detail="Razorpay not configured")

    price_map = {
        "silver": settings.SILVER_PRICE_INR,
        "gold": settings.GOLD_PRICE_INR,
        "platinum": settings.PLATINUM_PRICE_INR,
    }
    amount = price_map[payload.plan]
    user_id = current_user.get("sub", "unknown")

    try:
        import razorpay  # type: ignore[import-untyped]
        client = razorpay.Client(
            auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET)
        )
        order = client.order.create(
            {
                "amount": amount,
                "currency": "INR",
                "receipt": f"sub_{user_id[:8]}",
                "notes": {
                    "plan": payload.plan,
                    "user_id": user_id,
                },
            }
        )
    except ImportError:
        # Fallback: raw requests if razorpay SDK not installed
        resp = http_requests.post(
            "https://api.razorpay.com/v1/orders",
            auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET),
            json={
                "amount": amount,
                "currency": "INR",
                "receipt": f"sub_{user_id[:8]}",
                "notes": {"plan": payload.plan, "user_id": user_id},
            },
            timeout=15,
        )
        if resp.status_code >= 400:
            logger.error("razorpay_order_error", status=resp.status_code, body=resp.text)
            raise HTTPException(status_code=502, detail="Razorpay order creation failed")
        order = resp.json()

    logger.info(
        "razorpay_order_created",
        order_id=order["id"],
        plan=payload.plan,
        user_id=user_id,
    )

    return APIResponse(
        success=True,
        data=RazorpayOrderOut(
            order_id=order["id"],
            amount=amount,
            currency="INR",
            key=settings.RAZORPAY_KEY_ID,
        ).model_dump(),
    )


# ─────────────────────────────────────────────────────────────────────────────
# NEW: POST /subscriptions/webhook/stripe
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/subscriptions/webhook/stripe", status_code=200)
async def stripe_webhook_v2(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """
    Verify Stripe webhook signature and handle checkout.session.completed.
    Updates user subscription_tier and creates subscription_activated notification.
    """
    if not settings.STRIPE_WEBHOOK_SECRET:
        raise HTTPException(status_code=503, detail="Stripe webhook not configured")

    body = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    # ── Verify Stripe webhook signature (HMAC-SHA256, timestamp-tolerant) ──
    event = _verify_stripe_signature(body, sig_header, settings.STRIPE_WEBHOOK_SECRET)

    event_type = event.get("type", "")
    logger.info("stripe_webhook_v2", event_type=event_type, event_id=event.get("id"))

    if event_type == "checkout.session.completed":
        session_obj = event.get("data", {}).get("object", {})
        metadata = session_obj.get("metadata", {})

        user_id_str = metadata.get("user_id", "")
        plan = metadata.get("plan", "")
        tenant_id_str = metadata.get("tenant_id", "")
        stripe_session_id = session_obj.get("id", "")
        amount_total = session_obj.get("amount_total", 0)  # in pence

        if not user_id_str or not plan:
            logger.warning("stripe_webhook_missing_metadata", metadata=metadata)
            return {"status": "ok", "skipped": "missing metadata"}

        try:
            user_uuid = uuid.UUID(user_id_str)
        except ValueError:
            logger.warning("stripe_webhook_invalid_user_id", user_id=user_id_str)
            return {"status": "ok", "skipped": "invalid user_id"}

        tier = PLAN_TIER_MAP.get(plan.lower())
        if not tier:
            logger.warning("stripe_webhook_invalid_plan", plan=plan)
            return {"status": "ok", "skipped": "invalid plan"}

        # ── Update User.subscription_tier ──
        await db.execute(
            update(User)
            .where(User.id == user_uuid)
            .values(subscription_tier=tier)
        )

        # ── Upsert Subscription record ──
        now = datetime.now(timezone.utc)
        period_end = now + timedelta(days=30)

        subscription = Subscription(
            user_id=user_uuid,
            plan=plan.lower(),
            status=SubscriptionStatus.ACTIVE,
            gateway=PaymentGateway.STRIPE,
            gateway_subscription_id=stripe_session_id,
            amount_paise=amount_total,
            currency="GBP",
            current_period_start=now,
            current_period_end=period_end,
            monthly_interests=PLAN_FEATURE_MAP.get(plan.lower(), {}).get("interests", 10),
            monthly_contacts=PLAN_FEATURE_MAP.get(plan.lower(), {}).get("contacts", 0),
            monthly_video_calls=PLAN_FEATURE_MAP.get(plan.lower(), {}).get("video_calls", 0),
            raw_webhook_data=event,
        )
        db.add(subscription)

        # ── Create subscription_activated notification ──
        plan_display = plan.title()
        notification = Notification(
            user_id=user_uuid,
            type="subscription_activated",
            title=f"Welcome to {plan_display}!",
            body=(
                f"Your {plan_display} plan is now active. "
                "Enjoy unlimited matches and premium features."
            ),
            action_url="/subscription",
            metadata={
                "plan": plan.lower(),
                "gateway": "stripe",
                "session_id": stripe_session_id,
            },
        )
        db.add(notification)

        await db.commit()
        logger.info(
            "stripe_subscription_activated",
            user_id=user_id_str,
            plan=plan,
            session_id=stripe_session_id,
        )

    return {"status": "ok"}


def _verify_stripe_signature(
    payload: bytes, sig_header: str, secret: str
) -> dict:
    """
    Manually verify Stripe-Signature header (no SDK).
    Header format: t=<timestamp>,v1=<sig>[,v0=<sig>]
    Raises 400 if invalid or timestamp too old (>5 min).
    """
    try:
        parts = {k: v for k, v in (p.split("=", 1) for p in sig_header.split(",") if "=" in p)}
        timestamp = parts.get("t", "")
        v1_sig = parts.get("v1", "")
    except Exception:
        raise HTTPException(status_code=400, detail="Malformed Stripe-Signature header")

    if not timestamp or not v1_sig:
        raise HTTPException(status_code=400, detail="Missing Stripe-Signature components")

    # Replay-attack guard: reject events older than 5 minutes
    try:
        event_ts = int(timestamp)
        now_ts = int(datetime.now(timezone.utc).timestamp())
        if abs(now_ts - event_ts) > 300:
            raise HTTPException(status_code=400, detail="Stripe webhook timestamp too old")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid Stripe-Signature timestamp")

    signed_payload = f"{timestamp}.".encode() + payload
    expected = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()

    if not hmac.compare_digest(expected, v1_sig):
        raise HTTPException(status_code=400, detail="Invalid Stripe webhook signature")

    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON in Stripe webhook body")


# ─────────────────────────────────────────────────────────────────────────────
# NEW: POST /subscriptions/webhook/razorpay
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/subscriptions/webhook/razorpay", status_code=200)
async def razorpay_webhook_v2(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """
    Verify Razorpay webhook signature (HMAC-SHA256) and handle payment.captured.
    Updates user subscription_tier.
    """
    body = await request.body()
    sig = request.headers.get("X-Razorpay-Signature", "")

    if not settings.RAZORPAY_WEBHOOK_SECRET:
        raise HTTPException(status_code=503, detail="Razorpay webhook not configured")

    # ── Verify signature ──
    expected = hmac.new(
        settings.RAZORPAY_WEBHOOK_SECRET.encode(),
        body,
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected, sig):
        raise HTTPException(status_code=400, detail="Invalid Razorpay webhook signature")

    try:
        event = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON in webhook body")

    event_type = event.get("event", "")
    logger.info("razorpay_webhook_v2", event_type=event_type)

    if event_type == "payment.captured":
        payment = event.get("payload", {}).get("payment", {}).get("entity", {})
        notes = payment.get("notes", {})

        user_id_str = notes.get("user_id", "")
        plan = notes.get("plan", "")
        payment_id = payment.get("id", "")
        amount = payment.get("amount", 0)  # in paise

        if not user_id_str or not plan:
            logger.warning("razorpay_webhook_missing_notes", notes=notes)
            return {"status": "ok", "skipped": "missing notes"}

        try:
            user_uuid = uuid.UUID(user_id_str)
        except ValueError:
            logger.warning("razorpay_webhook_invalid_user_id", user_id=user_id_str)
            return {"status": "ok", "skipped": "invalid user_id"}

        tier = PLAN_TIER_MAP.get(plan.lower())
        if not tier:
            logger.warning("razorpay_webhook_invalid_plan", plan=plan)
            return {"status": "ok", "skipped": "invalid plan"}

        # ── Update User.subscription_tier ──
        await db.execute(
            update(User)
            .where(User.id == user_uuid)
            .values(subscription_tier=tier)
        )

        # ── Upsert Subscription record ──
        now = datetime.now(timezone.utc)
        period_end = now + timedelta(days=30)

        subscription = Subscription(
            user_id=user_uuid,
            plan=plan.lower(),
            status=SubscriptionStatus.ACTIVE,
            gateway=PaymentGateway.RAZORPAY,
            gateway_subscription_id=payment_id,
            amount_paise=amount,
            currency="INR",
            current_period_start=now,
            current_period_end=period_end,
            monthly_interests=PLAN_FEATURE_MAP.get(plan.lower(), {}).get("interests", 10),
            monthly_contacts=PLAN_FEATURE_MAP.get(plan.lower(), {}).get("contacts", 0),
            monthly_video_calls=PLAN_FEATURE_MAP.get(plan.lower(), {}).get("video_calls", 0),
            raw_webhook_data=event,
        )
        db.add(subscription)

        # ── Create subscription_activated notification ──
        plan_display = plan.title()
        notification = Notification(
            user_id=user_uuid,
            type="subscription_activated",
            title=f"Welcome to {plan_display}!",
            body=(
                f"Your {plan_display} plan is now active. "
                "Enjoy unlimited matches and premium features."
            ),
            action_url="/subscription",
            metadata={
                "plan": plan.lower(),
                "gateway": "razorpay",
                "payment_id": payment_id,
            },
        )
        db.add(notification)

        await db.commit()
        logger.info(
            "razorpay_subscription_activated",
            user_id=user_id_str,
            plan=plan,
            payment_id=payment_id,
        )

    return {"status": "ok"}


# ─────────────────────────────────────────────────────────────────────────────
# LEGACY: POST /subscriptions/create  (kept for backward compatibility)
# ─────────────────────────────────────────────────────────────────────────────

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

    try:
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
    except ImportError:
        raise HTTPException(status_code=503, detail="Razorpay SDK not available")

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

    price_map = {
        "silver": "price_silver_usd",
        "gold": "price_gold_usd",
        "platinum": "price_platinum_usd",
    }
    data = {
        "mode": "subscription",
        "line_items[0][price]": price_map.get(payload.plan, ""),
        "line_items[0][quantity]": "1",
        "success_url": "https://match4marriage.com/subscription?success=true",
        "cancel_url": "https://match4marriage.com/subscription",
        "client_reference_id": current_user.get("sub", ""),
    }
    session = _stripe_post("/checkout/sessions", data)

    return APIResponse(
        success=True,
        data=StripeCheckoutResponse(
            session_id=session["id"], checkout_url=session["url"]
        ).model_dump(),
    )


# ─────────────────────────────────────────────────────────────────────────────
# LEGACY: Webhook routes (kept at old paths for backward compat)
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/webhooks/razorpay", status_code=200)
async def razorpay_webhook_legacy(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Legacy path — delegates to new handler logic."""
    return await razorpay_webhook_v2(request, db)


@router.post("/webhooks/stripe", status_code=200)
async def stripe_webhook_legacy(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Legacy path — delegates to new handler logic."""
    return await stripe_webhook_v2(request, db)


# ─────────────────────────────────────────────────────────────────────────────
# GET /subscriptions/limits
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/subscriptions/limits", response_model=APIResponse[FeatureLimits])
async def get_feature_limits(
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Returns the current user's plan limits based on active subscription."""
    user_id_str = current_user.get("sub", "")
    plan = "free"

    try:
        user_uuid = uuid.UUID(user_id_str)
        result = await db.execute(
            select(User.subscription_tier).where(User.id == user_uuid)
        )
        row = result.scalar_one_or_none()
        if row:
            plan = row.value
    except (ValueError, AttributeError):
        pass  # demo mode or invalid UUID — default to free

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
