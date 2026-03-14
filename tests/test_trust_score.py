"""
Trust score computation tests.
"""
import pytest
from app.services.trust_score import compute_trust_score, compute_profile_completeness
from app.models.verification import VerificationType, VerificationStatus


class MockVerification:
    def __init__(self, v_type, status):
        self.verification_type = v_type
        self.status = status


class MockProfile:
    def __init__(self, **kwargs):
        defaults = {
            "first_name": None, "last_name": None, "date_of_birth": None,
            "gender": None, "city": None, "state": None, "religion": None,
            "mother_tongue": None, "height_cm": None, "education_level": None,
            "occupation": None, "bio": None, "photos": [],
        }
        defaults.update(kwargs)
        for k, v in defaults.items():
            setattr(self, k, v)


def test_trust_score_no_verifications():
    score = compute_trust_score([], 0, 0.0, 0)
    assert score == 0


def test_trust_score_full_verification():
    verifications = [
        MockVerification(VerificationType.AADHAAR, VerificationStatus.VERIFIED),
        MockVerification(VerificationType.PAN, VerificationStatus.VERIFIED),
        MockVerification(VerificationType.PHOTO_LIVENESS, VerificationStatus.VERIFIED),
    ]
    score = compute_trust_score(verifications, 100, 1.0, 0)
    # 25 + 15 + 20 (id) + 20 (profile) + 10 (response) + 10 (community) = 100
    assert score == 100


def test_trust_score_clamped_at_100():
    verifications = [
        MockVerification(VerificationType.AADHAAR, VerificationStatus.VERIFIED),
        MockVerification(VerificationType.PAN, VerificationStatus.VERIFIED),
        MockVerification(VerificationType.PHOTO_LIVENESS, VerificationStatus.VERIFIED),
        MockVerification(VerificationType.DIGILOCKER_EDUCATION, VerificationStatus.VERIFIED),
        MockVerification(VerificationType.LINKEDIN, VerificationStatus.VERIFIED),
    ]
    score = compute_trust_score(verifications, 100, 1.0, 0)
    assert score <= 100


def test_trust_score_reports_reduce_community_points():
    score_no_reports = compute_trust_score([], 0, 0.0, 0)
    score_with_reports = compute_trust_score([], 0, 0.0, 3)
    assert score_with_reports < score_no_reports


def test_trust_score_community_never_negative():
    score = compute_trust_score([], 0, 0.0, 999)
    assert score >= 0


def test_profile_completeness_empty():
    profile = MockProfile()
    assert compute_profile_completeness(profile) == 0


def test_profile_completeness_full():
    profile = MockProfile(
        first_name="Priya",
        last_name="Sharma",
        date_of_birth="1997-01-01",
        gender="female",
        city="Bangalore",
        state="Karnataka",
        religion="hindu",
        mother_tongue="Hindi",
        height_cm=162,
        education_level="BTech",
        occupation="Software Engineer",
        bio="I love hiking and reading.",
        photos=[{"url": "photo.jpg"}],
    )
    assert compute_profile_completeness(profile) == 100
