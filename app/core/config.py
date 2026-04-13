"""
Application configuration using pydantic-settings.
All values sourced from environment variables — 12-factor compliant.
"""
from functools import lru_cache
from typing import Literal

from pydantic import AnyHttpUrl, EmailStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # ── App ──────────────────────────────────────────────────────────────
    APP_NAME: str = "Match4Marriage API"
    APP_VERSION: str = "1.0.0"
    ENVIRONMENT: Literal["development", "staging", "production"] = "development"
    DEBUG: bool = False
    API_PREFIX: str = "/api/v1"
    ALLOWED_ORIGINS: str = "http://localhost:3000,https://frontend-black-psi-12.vercel.app,https://match4marriage.com,https://www.match4marriage.com"

    # ── Database ─────────────────────────────────────────────────────────
    DATABASE_URL: str = "sqlite+aiosqlite:///./bandhan_demo.db"
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_TIMEOUT: int = 30

    # ── Redis ────────────────────────────────────────────────────────────
    REDIS_URL: str = "redis://localhost:6379"

    # ── Auth0 ────────────────────────────────────────────────────────────
    AUTH0_DOMAIN: str = ""
    AUTH0_CLIENT_ID: str = ""
    AUTH0_CLIENT_SECRET: str = ""
    AUTH0_AUDIENCE: str = ""

    # ── Firebase Admin ───────────────────────────────────────────────────
    FIREBASE_PROJECT_ID: str = ""
    FIREBASE_CLIENT_EMAIL: str = ""
    FIREBASE_PRIVATE_KEY: str = ""

    # ── AWS / S3 (legacy) ──────────────────────────────────────────────
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    AWS_S3_BUCKET: str = "bandhan-media-dev"
    AWS_REGION: str = "ap-south-1"
    AWS_CLOUDFRONT_DOMAIN: str = ""

    # ── Cloudinary ──────────────────────────────────────────────────────
    CLOUDINARY_CLOUD_NAME: str = ""
    CLOUDINARY_API_KEY: str = ""
    CLOUDINARY_API_SECRET: str = ""
    CLOUDINARY_UPLOAD_FOLDER: str = "match4marriage"

    # ── Razorpay ─────────────────────────────────────────────────────────
    RAZORPAY_KEY_ID: str = ""
    RAZORPAY_KEY_SECRET: str = ""
    RAZORPAY_WEBHOOK_SECRET: str = ""

    # ── Stripe (diaspora / international) ────────────────────────────────
    STRIPE_SECRET_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""

    # ── Twilio ───────────────────────────────────────────────────────────
    TWILIO_ACCOUNT_SID: str = ""
    TWILIO_AUTH_TOKEN: str = ""
    TWILIO_PHONE_NUMBER: str = ""
    TWILIO_WHATSAPP_NUMBER: str = ""

    # ── AI / ML ──────────────────────────────────────────────────────────
    OPENAI_API_KEY: str = ""
    ANTHROPIC_API_KEY: str = ""
    PINECONE_API_KEY: str = ""
    PINECONE_INDEX: str = "bandhan-profiles"

    # ── VedAstro (Kundali matching) ──────────────────────────────────────
    VEDASTRO_API_KEY: str = "FreeAPIUser"

    # ── Email ────────────────────────────────────────────────────────────
    RESEND_API_KEY: str = ""
    RESEND_FROM_EMAIL: EmailStr = "hello@bandhan.in"  # type: ignore[assignment]

    # ── Multi-tenancy / White-label ───────────────────────────────────────
    # Each tenant gets their own subdomain: {slug}.bandhan.in
    DEFAULT_TENANT_SLUG: str = "bandhan"
    TENANT_HEADER: str = "X-Tenant-ID"

    # ── Rate limiting ────────────────────────────────────────────────────
    RATE_LIMIT_DEFAULT: str = "100/minute"
    RATE_LIMIT_AUTH: str = "10/minute"

    # ── Firebase ─────────────────────────────────────────────────────────
    # Service account credentials for Firebase Admin SDK (phone auth verify)
    FIREBASE_PROJECT_ID: str = ""
    FIREBASE_CLIENT_EMAIL: str = ""
    FIREBASE_PRIVATE_KEY: str = ""   # PEM key; literal \n accepted

    # ── OTP ──────────────────────────────────────────────────────────────
    OTP_EXPIRY_SECONDS: int = 300
    OTP_LENGTH: int = 6

    # ── Demo Mode ────────────────────────────────────────────────────────
    # When DEMO_MODE=true, OTP "000000" is always accepted (for client demos)
    DEMO_MODE: bool = False

    # ── Celery ───────────────────────────────────────────────────────────
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"

    # ── Subscription plans (prices in paise / lowest currency unit) ──────
    SILVER_PRICE_INR: int = 89900   # Rs 899
    GOLD_PRICE_INR: int = 249900    # Rs 2,499
    PLATINUM_PRICE_INR: int = 399900  # Rs 3,999

    # ── Subscription plans (prices in pence — GBP diaspora / UK) ─────────
    SILVER_PRICE_GBP: int = 999     # £9.99
    GOLD_PRICE_GBP: int = 2499      # £24.99
    PLATINUM_PRICE_GBP: int = 3999  # £39.99

    # Stripe prices in pence (GBP × 100)
    SILVER_PRICE_GBP: int = 999     # £9.99
    GOLD_PRICE_GBP: int = 2499      # £24.99
    PLATINUM_PRICE_GBP: int = 3999  # £39.99

    # Stripe publishable key (returned to frontend for Razorpay-style flows if needed)
    STRIPE_PUBLISHABLE_KEY: str = ""

    @property
    def allowed_origins_list(self) -> list[str]:
        """Parse ALLOWED_ORIGINS string into a list for CORS middleware."""
        v = self.ALLOWED_ORIGINS.strip()
        if v.startswith("["):
            import json
            try:
                return json.loads(v)
            except Exception:
                pass
        return [o.strip() for o in v.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

    @property
    def media_base_url(self) -> str:
        if self.AWS_CLOUDFRONT_DOMAIN:
            return f"https://{self.AWS_CLOUDFRONT_DOMAIN}"
        return f"https://{self.AWS_S3_BUCKET}.s3.{self.AWS_REGION}.amazonaws.com"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
