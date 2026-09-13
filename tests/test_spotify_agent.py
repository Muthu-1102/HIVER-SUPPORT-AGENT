"""Integration tests for end-to-end SpotifySupportAgent orchestration."""

import pytest

from src.spotify_agent import (
    AgentResult,
    ParsedConversation,
    SpotifySupportAgent,
    QUEUE_ACKNOWLEDGMENT_CLOSE,
    QUEUE_BILLING_SUPPORT,
    QUEUE_PLAN_MANAGEMENT,
    QUEUE_PRIVATE_CHANNEL_HANDOFF,
    QUEUE_SECURITY_ACCOUNT_RECOVERY,
    QUEUE_SENIOR_SUPPORT_ESCALATION,
    QUEUE_TECHNICAL_TROUBLESHOOTING,
)


@pytest.fixture
def agent() -> SpotifySupportAgent:
    """Fixture returning a clean SpotifySupportAgent instance."""
    return SpotifySupportAgent()


def test_1_single_message_billing_request(agent: SpotifySupportAgent):
    """Test 1: Single-message billing request processed end-to-end."""
    msg = "I was charged twice for Spotify Premium this month. Can I get a refund for the duplicate charge?"
    res = agent.process_message(msg)

    assert isinstance(res, AgentResult)
    assert isinstance(res.conversation, ParsedConversation)
    assert res.classification.primary_intent == "04_billing_payment"
    assert res.target_queue == QUEUE_BILLING_SUPPORT
    assert res.action == "billing_and_payment_inquiry"
    assert not res.requires_human_escalation
    assert "subscription details" in res.text.lower() or "billing" in res.text.lower()


def test_2_login_security_request(agent: SpotifySupportAgent):
    """Test 2: Login and account security recovery request."""
    msg = "Cannot log in to my account and my password reset link is not arriving. My account was hacked!"
    res = agent.process_message(msg)

    assert res.classification.primary_intent == "06_login_authentication"
    assert res.target_queue == QUEUE_SECURITY_ACCOUNT_RECOVERY
    assert res.action == "account_security_and_recovery"
    assert "password-reset" in res.text.lower() or "security" in res.text.lower()


def test_3_technical_malfunction(agent: SpotifySupportAgent):
    """Test 3: Technical malfunction and device troubleshooting."""
    msg = "The repeat button is not working on my iPhone app, it keeps freezing."
    res = agent.process_message(msg)

    assert res.classification.primary_intent == "07_technical_malfunction"
    assert res.classification.technical_malfunction_scope == "individual"
    assert res.target_queue == QUEUE_TECHNICAL_TROUBLESHOOTING
    assert res.action == "individual_device_troubleshooting"
    assert "cache" in res.text.lower() or "reinstall" in res.text.lower() or "restart" in res.text.lower()


def test_4_multi_intent_priority(agent: SpotifySupportAgent):
    """Test 4: Multi-intent priority resolution (06_login > 04_billing > 05_plan)."""
    # 06_login + 04_billing -> 06_login wins
    msg1 = "Locked out of my account and cannot log in, plus I was double charged."
    res1 = agent.process_message(msg1)
    assert res1.classification.primary_intent == "06_login_authentication"
    assert "04_billing_payment" in res1.classification.secondary_intents
    assert res1.target_queue == QUEUE_SECURITY_ACCOUNT_RECOVERY

    # 04_billing + 05_plan -> 04_billing wins
    msg2 = "Charged twice while trying to switch to family plan."
    res2 = agent.process_message(msg2)
    assert res2.classification.primary_intent == "04_billing_payment"
    assert "05_subscription_plan_management" in res2.classification.secondary_intents
    assert res2.target_queue == QUEUE_BILLING_SUPPORT


def test_5_dissatisfaction_escalation(agent: SpotifySupportAgent):
    """Test 5: Prior interaction dissatisfaction forces senior human escalation."""
    msg = "Fourth time reaching out! Sent 5 messages and still no reply regarding my billing charge!"
    res = agent.process_message(msg)

    assert "prior_interaction_dissatisfaction" in res.classification.cross_cutting_flags
    assert res.target_queue == QUEUE_SENIOR_SUPPORT_ESCALATION
    assert res.action == "escalate_to_senior_support"
    assert res.requires_human_escalation is True
    assert "senior support" in res.text.lower()


def test_6_alternate_channel_handoff(agent: SpotifySupportAgent):
    """Test 6: Alternate channel request triggers secure DM handoff."""
    msg = "Please send me a DM so I can send my email address privately."
    res = agent.process_message(msg)

    assert "alternate_channel_request" in res.classification.cross_cutting_flags
    assert res.target_queue == QUEUE_PRIVATE_CHANNEL_HANDOFF
    assert res.action == "initiate_secure_channel_handoff"
    assert res.requires_channel_handoff is True
    assert "direct message" in res.text.lower() or "dm" in res.text.lower()


def test_7_non_intent_acknowledgment(agent: SpotifySupportAgent):
    """Test 7: Closing statement acknowledgment without ticket escalation."""
    msg = "Thank you so much, that fixed it!"
    res = agent.process_message(msg)

    assert res.classification.is_non_intent is True
    assert res.classification.non_intent_class == "no_action_acknowledgment_only"
    assert res.target_queue == QUEUE_ACKNOWLEDGMENT_CLOSE
    assert res.action == "close_ticket_acknowledged"
    assert not res.requires_human_escalation


def test_8_multi_turn_conversation(agent: SpotifySupportAgent):
    """Test 8: Multi-turn conversation processing with customer context aggregation."""
    conv = {
        "conversation_id": "conv_multi_turn_test",
        "ordered_messages": [
            {"author_id": "cust123", "inbound": True, "text": "Hi there!"},
            {"author_id": "SpotifyCares", "inbound": False, "text": "Hey! How can we help today? /SU"},
            {"author_id": "cust123", "inbound": True, "text": "I'm having trouble with my student verification link on SheerID"},
        ],
    }
    res = agent.process_conversation(conv)

    assert res.conversation.conversation_id == "conv_multi_turn_test"
    assert len(res.conversation.messages) == 3
    assert res.classification.primary_intent == "05_subscription_plan_management"
    assert res.target_queue == QUEUE_PLAN_MANAGEMENT
    assert res.action == "subscription_plan_guidance"
    assert "sheerid" in res.text.lower() or "student" in res.text.lower()


def test_9_deterministic_repeated_execution(agent: SpotifySupportAgent):
    """Test 9: Identical repeated executions yield bit-for-bit identical results."""
    query = "Why is this song greyed out in the UK?"

    runs = [agent.process_message(query) for _ in range(5)]

    for r in runs[1:]:
        assert r == runs[0]
        assert r.text == runs[0].text
        assert r.target_queue == runs[0].target_queue
        assert r.action == runs[0].action
        assert r.classification == runs[0].classification
        assert r.routing == runs[0].routing


def test_10_immutability_of_result_and_metadata(agent: SpotifySupportAgent):
    """Test 10: Immutability of returned AgentResult, Classification, and Routing."""
    res = agent.process_message("How do I cancel my subscription?")

    assert isinstance(res, AgentResult)

    with pytest.raises(Exception):
        res.text = "Tampered text"  # type: ignore

    with pytest.raises(Exception):
        res.classification.primary_intent = "06_login_authentication"  # type: ignore

    with pytest.raises(Exception):
        res.routing.target_queue = "tampered_queue"  # type: ignore
