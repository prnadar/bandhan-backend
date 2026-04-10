"""
Firebase Admin SDK initialization — singleton pattern.
Used for verifying Firebase ID tokens from mobile phone auth.

Required environment variables:
  FIREBASE_PROJECT_ID     — Firebase project ID
  FIREBASE_CLIENT_EMAIL   — Service account client email
  FIREBASE_PRIVATE_KEY    — Service account private key (PEM, newlines as \\n)
"""
import firebase_admin
from firebase_admin import credentials, auth as firebase_auth

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_firebase_app: firebase_admin.App | None = None


def get_firebase_app() -> firebase_admin.App | None:
    """
    Return the initialized Firebase Admin app (singleton).
    Returns None if Firebase credentials are not configured — callers
    must handle this gracefully (e.g. raise HTTP 503).
    """
    global _firebase_app

    if _firebase_app is not None:
        return _firebase_app

    # Return existing default app if already initialised by another path
    if firebase_admin._apps:  # noqa: SLF001
        _firebase_app = firebase_admin.get_app()
        return _firebase_app

    settings = get_settings()
    if not all([
        settings.FIREBASE_PROJECT_ID,
        settings.FIREBASE_CLIENT_EMAIL,
        settings.FIREBASE_PRIVATE_KEY,
    ]):
        logger.warning("firebase_not_configured", detail="FIREBASE_* env vars missing — Firebase phone auth disabled")
        return None

    try:
        # Private key may have literal \n instead of real newlines in env vars
        private_key = settings.FIREBASE_PRIVATE_KEY.replace("\\n", "\n")

        cred = credentials.Certificate({
            "type": "service_account",
            "project_id": settings.FIREBASE_PROJECT_ID,
            "client_email": settings.FIREBASE_CLIENT_EMAIL,
            "private_key": private_key,
            "token_uri": "https://oauth2.googleapis.com/token",
        })
        _firebase_app = firebase_admin.initialize_app(cred)
        logger.info("firebase_initialized", project_id=settings.FIREBASE_PROJECT_ID)
        return _firebase_app
    except Exception as exc:
        logger.error("firebase_init_failed", error=str(exc))
        return None


def verify_firebase_id_token(id_token: str) -> dict:
    """
    Verify a Firebase ID token and return the decoded claims dict.
    Raises ValueError if the token is invalid or Firebase is not configured.
    """
    app = get_firebase_app()
    if app is None:
        raise ValueError("Firebase is not configured on this server")

    decoded = firebase_auth.verify_id_token(id_token, app=app, check_revoked=True)
    return decoded
