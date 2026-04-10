"""
Email service — transactional emails via Resend API.

All functions are async-compatible via asyncio.to_thread so the
FastAPI event loop is never blocked by the synchronous HTTP call.
"""
import asyncio
import logging
from typing import Any

import resend

from app.core.config import get_settings
from app.core.logging import get_logger

settings = get_settings()
logger = get_logger(__name__)


def _configure_resend() -> None:
    """Set the Resend API key (idempotent)."""
    resend.api_key = settings.RESEND_API_KEY


# ── Low-level helper ──────────────────────────────────────────────────────────


def _resend_post(
    to_email: str,
    to_name: str,
    subject: str,
    html_content: str,
    plain_content: str = "",
) -> bool:
    """
    Synchronous call to Resend emails.send.
    Returns True on success, False otherwise.
    Runs inside asyncio.to_thread to keep the event loop free.
    """
    if not settings.RESEND_API_KEY:
        logger.warning("resend_api_key_missing — email not sent")
        return False

    _configure_resend()
    from_email = str(settings.RESEND_FROM_EMAIL)

    params: dict[str, Any] = {
        "from": f"Match4Marriage <{from_email}>",
        "to": [to_email],
        "subject": subject,
        "html": html_content,
        "text": plain_content or _html_to_plain(html_content),
    }

    try:
        email = resend.Emails.send(params)
        logger.info(
            "email_sent",
            to=to_email,
            subject=subject,
            id=email.get("id"),
        )
        return True
    except Exception as exc:
        logger.error("resend_error", error=str(exc), to=to_email)
        return False


def _html_to_plain(html: str) -> str:
    """Very minimal HTML → plaintext strip for fallback plain part."""
    import re
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ── Public async API ──────────────────────────────────────────────────────────


async def send_verification_email(
    email: str,
    token: str,
    user_name: str,
) -> bool:
    """
    Send a 6-character email verification token to the user.

    Args:
        email:     recipient email address
        token:     6-char alphanumeric OTP
        user_name: display name for personalisation

    Returns True on delivery success, False otherwise.
    """
    subject = "Verify your Match4Marriage email address"

    html = f"""
<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="font-family: Arial, sans-serif; background: #f9f6f1; margin: 0; padding: 0;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f9f6f1; padding:40px 0;">
    <tr><td align="center">
      <table width="560" cellpadding="0" cellspacing="0"
             style="background:#ffffff; border-radius:12px; overflow:hidden;
                    box-shadow:0 2px 8px rgba(0,0,0,0.08);">
        <!-- Header -->
        <tr>
          <td style="background:#c0392b; padding:32px; text-align:center;">
            <h1 style="color:#ffffff; margin:0; font-size:24px; letter-spacing:1px;">
              Match4Marriage
            </h1>
          </td>
        </tr>
        <!-- Body -->
        <tr>
          <td style="padding:36px 40px;">
            <p style="font-size:16px; color:#333333; margin:0 0 16px;">
              Namaste {user_name},
            </p>
            <p style="font-size:15px; color:#555555; line-height:1.6; margin:0 0 24px;">
              Thank you for joining Match4Marriage — your trusted partner in finding a life partner
              within the UK Indian community. Please verify your email address using the code below.
            </p>
            <!-- Token box -->
            <div style="background:#f4f0ec; border-radius:8px; padding:24px; text-align:center;
                        margin:0 0 28px;">
              <p style="margin:0 0 8px; font-size:13px; color:#888888; text-transform:uppercase;
                         letter-spacing:1px;">Your verification code</p>
              <span style="font-size:36px; font-weight:bold; color:#c0392b; letter-spacing:6px;">
                {token}
              </span>
              <p style="margin:12px 0 0; font-size:12px; color:#aaaaaa;">
                Expires in 10 minutes
              </p>
            </div>
            <p style="font-size:13px; color:#888888; line-height:1.5;">
              If you did not create an account on Match4Marriage, please ignore this email.
              Never share this code with anyone.
            </p>
          </td>
        </tr>
        <!-- Footer -->
        <tr>
          <td style="background:#f4f0ec; padding:20px 40px; text-align:center;">
            <p style="margin:0; font-size:12px; color:#aaaaaa;">
              &copy; 2025 Match4Marriage &middot; All rights reserved
            </p>
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body>
</html>
"""

    plain = (
        f"Namaste {user_name},\n\n"
        f"Your Match4Marriage email verification code is: {token}\n\n"
        "This code expires in 10 minutes.\n\n"
        "If you did not create an account, please ignore this email."
    )

    return await asyncio.to_thread(
        _resend_post, email, user_name, subject, html, plain
    )


async def send_welcome_email(
    email: str,
    user_name: str,
) -> bool:
    """
    Send a welcome email after a user completes email verification.

    Args:
        email:     recipient email address
        user_name: display name

    Returns True on delivery success, False otherwise.
    """
    subject = "Welcome to Match4Marriage — your journey begins"

    html = f"""
<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="font-family: Arial, sans-serif; background: #f9f6f1; margin: 0; padding: 0;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f9f6f1; padding:40px 0;">
    <tr><td align="center">
      <table width="560" cellpadding="0" cellspacing="0"
             style="background:#ffffff; border-radius:12px; overflow:hidden;
                    box-shadow:0 2px 8px rgba(0,0,0,0.08);">
        <tr>
          <td style="background:#c0392b; padding:32px; text-align:center;">
            <h1 style="color:#ffffff; margin:0; font-size:24px; letter-spacing:1px;">
              Match4Marriage
            </h1>
          </td>
        </tr>
        <tr>
          <td style="padding:36px 40px;">
            <p style="font-size:16px; color:#333333; margin:0 0 16px;">
              Welcome, {user_name}!
            </p>
            <p style="font-size:15px; color:#555555; line-height:1.6; margin:0 0 20px;">
              Your email has been verified. You're now a verified member of Match4Marriage —
              the most trusted matrimonial platform for the UK Indian community.
            </p>
            <p style="font-size:15px; color:#555555; line-height:1.6; margin:0 0 28px;">
              Here's what to do next:
            </p>
            <table width="100%" cellpadding="0" cellspacing="0" style="margin:0 0 28px;">
              <tr>
                <td style="background:#fdf8f4; border-left:4px solid #c0392b; padding:14px 18px;
                            border-radius:4px; margin-bottom:12px;">
                  <strong style="color:#333;">1. Complete your profile</strong>
                  <p style="margin:4px 0 0; font-size:13px; color:#777;">
                    Profiles with photos get 8&times; more responses.
                  </p>
                </td>
              </tr>
              <tr><td style="height:10px;"></td></tr>
              <tr>
                <td style="background:#fdf8f4; border-left:4px solid #c0392b; padding:14px 18px;
                            border-radius:4px;">
                  <strong style="color:#333;">2. Explore daily matches</strong>
                  <p style="margin:4px 0 0; font-size:13px; color:#777;">
                    We curate 5 compatible matches for you every morning.
                  </p>
                </td>
              </tr>
            </table>
            <p style="font-size:13px; color:#888888;">
              Wishing you all the very best on your journey.
            </p>
          </td>
        </tr>
        <tr>
          <td style="background:#f4f0ec; padding:20px 40px; text-align:center;">
            <p style="margin:0; font-size:12px; color:#aaaaaa;">
              &copy; 2025 Match4Marriage &middot; All rights reserved
            </p>
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body>
</html>
"""

    plain = (
        f"Welcome, {user_name}!\n\n"
        "Your email has been verified. You are now a verified member of Match4Marriage.\n\n"
        "Next steps:\n"
        "1. Complete your profile — profiles with photos get 8x more responses.\n"
        "2. Explore your daily matches — we curate 5 compatible profiles every morning.\n\n"
        "Wishing you all the very best on your journey.\n\n"
        "— The Match4Marriage Team"
    )

    return await asyncio.to_thread(
        _resend_post, email, user_name, subject, html, plain
    )


async def send_interest_notification_email(
    email: str,
    from_name: str,
    recipient_name: str = "there",
) -> bool:
    """
    Notify a user that someone has expressed interest in their profile.

    Args:
        email:          recipient email address
        from_name:      display name of the person who sent the interest
        recipient_name: display name of the recipient (defaults to "there")

    Returns True on delivery success, False otherwise.
    """
    subject = f"{from_name} is interested in your profile"

    html = f"""
<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="font-family: Arial, sans-serif; background: #f9f6f1; margin: 0; padding: 0;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f9f6f1; padding:40px 0;">
    <tr><td align="center">
      <table width="560" cellpadding="0" cellspacing="0"
             style="background:#ffffff; border-radius:12px; overflow:hidden;
                    box-shadow:0 2px 8px rgba(0,0,0,0.08);">
        <tr>
          <td style="background:#c0392b; padding:32px; text-align:center;">
            <h1 style="color:#ffffff; margin:0; font-size:24px; letter-spacing:1px;">
              Match4Marriage
            </h1>
          </td>
        </tr>
        <tr>
          <td style="padding:36px 40px; text-align:center;">
            <h2 style="color:#c0392b; font-size:22px; margin:0 0 16px;">
              You have a new interest!
            </h2>
            <p style="font-size:15px; color:#555555; line-height:1.6; margin:0 0 24px;">
              Namaste {recipient_name},<br><br>
              <strong>{from_name}</strong> has expressed interest in your profile.
              Log in to view their profile and decide if you'd like to connect.
            </p>
            <!-- CTA button -->
            <a href="#"
               style="display:inline-block; background:#c0392b; color:#ffffff; font-size:15px;
                      font-weight:bold; padding:14px 32px; border-radius:6px;
                      text-decoration:none; margin:0 0 28px;">
              View Their Profile &rarr;
            </a>
            <p style="font-size:13px; color:#aaaaaa; line-height:1.5;">
              If you're not interested, simply ignore this notification or decline from within the
              app. Your privacy is always respected.
            </p>
          </td>
        </tr>
        <tr>
          <td style="background:#f4f0ec; padding:20px 40px; text-align:center;">
            <p style="margin:0; font-size:12px; color:#aaaaaa;">
              &copy; 2025 Match4Marriage &middot; All rights reserved
            </p>
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body>
</html>
"""

    plain = (
        f"Namaste {recipient_name},\n\n"
        f"{from_name} has expressed interest in your profile on Match4Marriage.\n\n"
        "Log in to view their profile and decide whether you'd like to connect.\n\n"
        "— The Match4Marriage Team"
    )

    return await asyncio.to_thread(
        _resend_post, email, recipient_name, subject, html, plain
    )
