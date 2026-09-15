"""Unit tests for safety validation and sanitization of customer-facing responses."""

import pytest

from src.spotify_agent.safety_validator import (
    sanitize_response_text,
    validate_response_safety,
)


def test_sanitize_strips_twitter_handles():
    raw = "@115887 @SpotifyCares Hey! Could you try restarting the app? /CB"
    cleaned = sanitize_response_text(raw)
    assert "@115887" not in cleaned
    assert "@SpotifyCares" not in cleaned
    assert "/CB" not in cleaned
    assert "restarting the app" in cleaned


def test_sanitize_strips_internal_queues_and_taxonomy():
    raw = "Routing to QUEUE_BILLING_SUPPORT under 04_billing_payment intent."
    cleaned = sanitize_response_text(raw)
    assert "QUEUE_BILLING_SUPPORT" not in cleaned
    assert "04_billing_payment" not in cleaned


def test_validate_response_safety_approved():
    safe_text = (
        "To manage your subscription or check student verification, please visit "
        "spotify.com/account. If you need further help, feel free to reach out."
    )
    is_safe, violations = validate_response_safety(safe_text)
    assert is_safe is True
    assert len(violations) == 0


def test_validate_response_safety_detects_unapproved_urls():
    unsafe_text = "Visit http://phishing-spotify-login.com to reset your password."
    is_safe, violations = validate_response_safety(unsafe_text)
    assert is_safe is False
    assert any("unapproved URL domain" in v for v in violations)


def test_validate_response_safety_detects_leaked_handles():
    unsafe_text = "Hello @115887 please let us know your OS version."
    is_safe, violations = validate_response_safety(unsafe_text)
    assert is_safe is False
    assert any("unstripped @handle" in v for v in violations)
