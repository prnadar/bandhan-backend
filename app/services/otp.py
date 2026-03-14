"""
OTP service — generate, store in Redis, validate.
Uses Twilio for SMS delivery. Falls back to WhatsApp Business API.
"""
import random
import string

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.redis import get_redis

settings = get_settings()
logger = get_logger(__name__)

OTP_KEY_PREFIX = "otp:"


def _make_otp() -> str:
    return "".join(random.choices(string.digits, k=settings.OTP_LENGTH))


def _redis_key(phone: str, tenant_slug: str) -> str:
    return f"{OTP_KEY_PREFIX}{tenant_slug}:{phone}"


async def send_otp(phone: str, country_code: str, tenant_slug: str) -> bool:
    """Generate OTP, store in Redis, send via Twilio SMS."""
    otp = _make_otp()
    redis = await get_redis()
    key = _redis_key(phone, tenant_slug)

    await redis.setex(key, settings.OTP_EXPIRY_SECONDS, otp)

    full_number = f"{country_code}{phone}"
    try:
        _send_sms(full_number, otp)
        logger.info("otp_sent", phone=phone[-4:], tenant=tenant_slug)
        return True
    except Exception as exc:
        logger.error("otp_send_failed", phone=phone[-4:], error=str(exc))
        return False


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
    """Validate OTP. Deletes key on success (one-time use)."""
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
