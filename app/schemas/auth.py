"""
Auth schemas — registration, OTP, token response.
"""
import re

from pydantic import field_validator

from app.schemas.common import BaseSchema


class RegisterRequest(BaseSchema):
    phone: str
    country_code: str = "+91"

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        cleaned = re.sub(r"\D", "", v)
        if len(cleaned) not in (10, 12):
            raise ValueError("Phone must be 10 digits (India) or 12 with country code")
        return cleaned


class OTPVerifyRequest(BaseSchema):
    phone: str
    otp: str
    country_code: str = "+91"

    @field_validator("otp")
    @classmethod
    def validate_otp(cls, v: str) -> str:
        if not v.isdigit() or len(v) != 6:
            raise ValueError("OTP must be 6 digits")
        return v


class TokenResponse(BaseSchema):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user_id: str
    is_new_user: bool = False


class RefreshTokenRequest(BaseSchema):
    refresh_token: str


class FirebaseVerifyRequest(BaseSchema):
    """Payload for POST /auth/firebase-verify — exchange Firebase ID token for backend session."""
    id_token: str


class EmailRegisterRequest(BaseSchema):
    """Payload for POST /auth/email-register — create/upsert user by email after web OTP verification."""
    email: str
    name: str = ""
    gender: str = ""
