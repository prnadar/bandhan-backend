"""
Auth endpoint tests — TDD spec for Sprint 1.
"""
import pytest
from httpx import AsyncClient
from unittest.mock import AsyncMock, patch


@pytest.mark.asyncio
async def test_register_valid_phone(client: AsyncClient):
    """POST /api/v1/auth/register with valid phone returns 200."""
    with patch("app.services.otp.send_otp", new_callable=AsyncMock, return_value=True):
        response = await client.post(
            "/api/v1/auth/register",
            json={"phone": "9876543210", "country_code": "+91"},
            headers={"X-Tenant-ID": "bandhan"},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert "OTP" in body["message"]


@pytest.mark.asyncio
async def test_register_invalid_phone(client: AsyncClient):
    """Short phone number should fail validation."""
    response = await client.post(
        "/api/v1/auth/register",
        json={"phone": "123", "country_code": "+91"},
        headers={"X-Tenant-ID": "bandhan"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_register_otp_send_failure(client: AsyncClient):
    """If OTP service fails, return 503."""
    with patch("app.services.otp.send_otp", new_callable=AsyncMock, return_value=False):
        response = await client.post(
            "/api/v1/auth/register",
            json={"phone": "9876543210", "country_code": "+91"},
            headers={"X-Tenant-ID": "bandhan"},
        )
    assert response.status_code == 503


@pytest.mark.asyncio
async def test_verify_otp_invalid(client: AsyncClient):
    """Wrong OTP returns 400."""
    with patch("app.services.otp.verify_otp", new_callable=AsyncMock, return_value=False):
        response = await client.post(
            "/api/v1/auth/verify-otp",
            json={"phone": "9876543210", "otp": "000000"},
            headers={"X-Tenant-ID": "bandhan"},
        )
    assert response.status_code == 400
    assert "Invalid or expired OTP" in response.json()["detail"]


@pytest.mark.asyncio
async def test_verify_otp_non_digit(client: AsyncClient):
    """OTP with letters fails schema validation."""
    response = await client.post(
        "/api/v1/auth/verify-otp",
        json={"phone": "9876543210", "otp": "abc123"},
        headers={"X-Tenant-ID": "bandhan"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_health_endpoint(client: AsyncClient):
    """Health endpoint always returns 200."""
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
