"""Tests for scripts/demo_agent.py CLI interface and formatting."""

import pytest
from scripts.demo_agent import format_agent_result, run_demo
from src.spotify_agent.agent import SpotifySupportAgent


def test_demo_agent_formatting():
    """Verify that demo agent formats output correctly with all required fields."""
    agent = SpotifySupportAgent()
    msg = "Why was I charged twice for Spotify Premium this month?"
    result = agent.process_message(msg)
    output = format_agent_result(result, msg)

    assert "Customer Message:" in output
    assert "04_billing_payment" in output
    assert "Target Queue:" in output
    assert "billing_support" in output
    assert "Action:" in output
    assert "billing_and_payment_inquiry" in output
    assert "Priority:" in output
    assert "Human Escalation:" in output
    assert "Channel Handoff:" in output
    assert "GENERATED CUSTOMER-FACING RESPONSE:" in output


def test_demo_agent_run(capsys):
    """Verify demo execution on single inquiry prints clean report."""
    msg = "I forgot my password and cannot log in to my account"
    res = run_demo(msg)
    captured = capsys.readouterr()

    assert res.classification.primary_intent == "06_login_authentication"
    assert "security_account_recovery" in captured.out
    assert "password-reset" in captured.out or "security" in captured.out
