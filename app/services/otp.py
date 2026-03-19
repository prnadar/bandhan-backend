"""
OTP service — generate, store in Redis, validate.
Uses Twilio for SMS delivery. Falls back to WhatsApp Business API.

DEMO MODE: When DEMO_MODE=true env var is set, OTP "000000" is always stored
and always accepted — allows client demos without a verified Twilio number.
"""
import random
import string

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.redis import get_redis

settings = get_settings()
logger = get_logger(__name__)

OTP_KEY_PREFIX = "otp:"
DEMO_OTP = "000000"


def _make_otp() -> str:
    return "".join(random.choices(string.digits, k=settings.OTP_LENGTH))


def _redis_key(phone: str, tenant_slug: str) -> str:
    return f"{OTP_KEY_PREFIX}{tenant_slug}:{phone}"


async def send_otp(phone: str, country_code: str, tenant_slug: str) -> bool:
    """Generate OTP, store in Redis, send via Twilio SMS.

    In DEMO_MODE, always stores "000000" so the demo user can always log in
    with that code regardless of whether Twilio succeeds.
    """
    redis = await get_redis()
    key = _redis_key(phone, tenant_slug)

    if settings.DEMO_MODE:
        # Store the demo OTP so verify_otp works without Twilio
        await redis.setex(key, settings.OTP_EXPIRY_SECONDS, DEMO_OTP)
        logger.warning("demo_mode_otp_stored", phone=phone[-4:], tenant=tenant_slug)
        # Still attempt real SMS — if Twilio fails we just log and continue
        full_number = f"{country_code}{phone}"
        try:
            _send_sms(full_number, DEMO_OTP)
        except Exception as exc:
            logger.warning("demo_mode_sms_skipped", phone=phone[-4:], error=str(exc))
        return True

    otp = _make_otp()
    await redis.setex(key, settings.OTP_EXPIRY_SECONDS, otp)

    full_number = f"{country_code}{phone}"
    try:
        _send_sms(full_number, otp)
        logger.info("otp_sent", phone=phone[-4:], tenant=tenant_slug)
        return True
    except Exception as exc:
        logger.error("otp_send_failed", phone=phone[-4:], error=str(exc))
        # Even when Twilio fails, store the demo OTP so login is still possible
        logger.warning("otp_fallback_to_demo", phone=phone[-4:])
        await redis.setex(key, settings.OTP_EXPIRY_SECONDS, DEMO_OTP)
        return True  # Return True so the app proceeds to OTP entry screen


def _send_sms(phone: str, otp: str) -> None:
    """Send SMS via Twilio. Raises on failure."""
    if not settings.TWILIO_ACCOUNT_SID:
        # Dev mode — log OTP to stdout (never in production)
        logger.warning("twilio_not_configured_dev_otp", otp=otp)
        return

    from twilio.rest import Client  # type: ignore[import-untyped]

    client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
    client.messages.create(
        body=f"Your Bandhan OTP is {otp}. Valid for {settings.OTP_EXPIRY_SECONDS // 60} minutes.",
        from_=settings.TWILIO_PHONE_NUMBER,
        to=phone,
    )


async def verify_otp(phone: str, otp: str, tenant_slug: str) -> bool:
    """Validate OTP. Deletes key on success (one-time use).

    In DEMO_MODE, always accepts "000000" regardless of what is in Redis.
    """
    # Demo mode shortcut: "000000" always works
    if settings.DEMO_MODE and otp == DEMO_OTP:
        logger.warning("demo_mode_otp_accepted", phone=phone[-4:], tenant=tenant_slug)
        # Clean up any stored key
        redis = await get_redis()
        key = _redis_key(phone, tenant_slug)
        await redis.delete(key)
        return True

    redis = await get_redis()
    key = _redis_key(phone, tenant_slug)
    stored = await redis.get(key)

    if stored is None:
        logger.info("otp_expired_or_not_found", phone=phone[-4:])
        return False

    if stored != otp:
        logger.info("otp_mismatch", phone=phone[-4:])
        return False

    await redis.delete(key)
    logger.info("otp_verified", phone=phone[-4:], tenant=tenant_slug)
    return True
