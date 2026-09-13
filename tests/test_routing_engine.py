"""Focused unit tests for the deterministic routing engine."""

import pytest

from src.spotify_agent.intent_classifier import (
    Classification,
    classify_conversation,
    classify_message,
)
from src.spotify_agent.routing_engine import (
    QUEUE_ACKNOWLEDGMENT_CLOSE,
    QUEUE_ARTIST_RIGHTS,
    QUEUE_BILLING_SUPPORT,
    QUEUE_CATALOG_CONTENT,
    QUEUE_CATALOG_METADATA,
    QUEUE_CLARIFICATION,
    QUEUE_PLAN_MANAGEMENT,
    QUEUE_PRIVATE_CHANNEL_HANDOFF,
    QUEUE_PRODUCT_FEEDBACK,
    QUEUE_REGIONAL_LICENSING,
    QUEUE_SECURITY_ACCOUNT_RECOVERY,
    QUEUE_SENIOR_SUPPORT_ESCALATION,
    QUEUE_SOCIAL_NON_SUPPORT,
    QUEUE_TECHNICAL_TROUBLESHOOTING,
    RoutingDecision,
    route_classification,
    route_conversation,
    route_message,
)


def test_substantive_intents_routing():
    """Verify standard routing for all 9 substantive intents without flags."""
    test_cases = [
        ("06_login_authentication", "Forgot password and can't log in", QUEUE_SECURITY_ACCOUNT_RECOVERY, "account_security_and_recovery", "critical"),
        ("04_billing_payment", "Why was I charged twice for premium this month?", QUEUE_BILLING_SUPPORT, "billing_and_payment_inquiry", "high"),
        ("07_technical_malfunction", "App keeps crashing on startup", QUEUE_TECHNICAL_TROUBLESHOOTING, "technical_diagnostic_clarification", "normal"),
        ("05_subscription_plan_management", "How to add a family member to my family plan?", QUEUE_PLAN_MANAGEMENT, "subscription_plan_guidance", "normal"),
        ("03_region_availability", "Why is this track greyed out in the UK?", QUEUE_REGIONAL_LICENSING, "regional_availability_guidance", "normal"),
        ("01_catalog_content_gap", "When will Young Thug new album be on Spotify?", QUEUE_CATALOG_CONTENT, "catalog_availability_lookup", "low"),
        ("02_catalog_metadata_error", "The artist name is misspelled on this track", QUEUE_CATALOG_METADATA, "log_metadata_correction_ticket", "low"),
        ("08_feature_request", "Please add playlist folder creation on mobile app", QUEUE_PRODUCT_FEEDBACK, "log_product_feedback", "low"),
        ("09_artist_rights_holder_mgmt", "How do I claim my artist profile on Spotify for Artists?", QUEUE_ARTIST_RIGHTS, "artist_portal_support_routing", "normal"),
    ]

    for expected_intent, text, expected_queue, expected_action, expected_priority in test_cases:
        decision = route_message(text)
        assert decision.classification.primary_intent == expected_intent, f"Failed intent for text: {text}"
        assert decision.target_queue == expected_queue
        assert decision.action == expected_action
        assert decision.priority == expected_priority
        assert not decision.requires_human_escalation
        assert not decision.requires_channel_handoff
        assert isinstance(decision.routing_reason, str) and len(decision.routing_reason) > 0


def test_non_intent_classes_routing():
    """Verify safe routing for all 3 non-intent classes without inventing tickets."""
    # 1. insufficient_information
    dec_vague = route_message("Help me")
    assert dec_vague.classification.is_non_intent is True
    assert dec_vague.classification.non_intent_class == "insufficient_information"
    assert dec_vague.target_queue == QUEUE_CLARIFICATION
    assert dec_vague.action == "request_more_information"
    assert not dec_vague.requires_human_escalation

    # 2. out_of_scope_non_support
    dec_social = route_message("I love spotify and listening to music!")
    assert dec_social.classification.is_non_intent is True
    assert dec_social.classification.non_intent_class == "out_of_scope_non_support"
    assert dec_social.target_queue == QUEUE_SOCIAL_NON_SUPPORT
    assert dec_social.action == "social_engagement_or_ignore"
    assert not dec_social.requires_human_escalation

    # 3. no_action_acknowledgment_only
    dec_ack = route_message("Thanks that fixed it!")
    assert dec_ack.classification.is_non_intent is True
    assert dec_ack.classification.non_intent_class == "no_action_acknowledgment_only"
    assert dec_ack.target_queue == QUEUE_ACKNOWLEDGMENT_CLOSE
    assert dec_ack.action == "close_ticket_acknowledged"
    assert not dec_ack.requires_human_escalation


def test_technical_malfunction_scopes_routing():
    """Verify routing distinguishes individual, platform_wide, and unclear scopes."""
    # Individual scope
    dec_ind = route_message("The shuffle button is broken on my iPhone.")
    assert dec_ind.classification.primary_intent == "07_technical_malfunction"
    assert dec_ind.classification.technical_malfunction_scope == "individual"
    assert dec_ind.target_queue == QUEUE_TECHNICAL_TROUBLESHOOTING
    assert dec_ind.action == "individual_device_troubleshooting"
    assert dec_ind.priority == "normal"

    # Platform-wide scope
    dec_outage = route_message("Is Spotify down for everyone? Servers are down.")
    assert dec_outage.classification.primary_intent == "07_technical_malfunction"
    assert dec_outage.classification.technical_malfunction_scope == "platform_wide"
    assert dec_outage.target_queue == QUEUE_TECHNICAL_TROUBLESHOOTING
    assert dec_outage.action == "platform_outage_monitoring"
    assert dec_outage.priority == "high"

    # Unclear scope
    dec_unclear = route_message("Playback error constantly buffering.")
    assert dec_unclear.classification.primary_intent == "07_technical_malfunction"
    assert dec_unclear.classification.technical_malfunction_scope == "unclear"
    assert dec_unclear.target_queue == QUEUE_TECHNICAL_TROUBLESHOOTING
    assert dec_unclear.action == "technical_diagnostic_clarification"
    assert dec_unclear.priority == "normal"


def test_dissatisfaction_escalation_override():
    """Verify prior interaction dissatisfaction forces senior human escalation."""
    msg = "This is the third time reaching out! Sent 5 messages and still no reply regarding my billing charge."
    decision = route_message(msg)

    assert "prior_interaction_dissatisfaction" in decision.classification.cross_cutting_flags
    assert decision.target_queue == QUEUE_SENIOR_SUPPORT_ESCALATION
    assert decision.action == "escalate_to_senior_support"
    assert decision.priority == "critical"
    assert decision.requires_human_escalation is True


def test_alternate_channel_handoff():
    """Verify alternate channel requests route to secure channel handoff."""
    msg = "Please DM me directly to help with my subscription renewal."
    decision = route_message(msg)

    assert "alternate_channel_request" in decision.classification.cross_cutting_flags
    assert decision.target_queue == QUEUE_PRIVATE_CHANNEL_HANDOFF
    assert decision.action == "initiate_secure_channel_handoff"
    assert decision.requires_channel_handoff is True


def test_multi_intent_priority_routing():
    """Verify routing follows primary intent selected by multi-intent priority order."""
    # Login (06) + Billing (04) -> Login wins
    msg = "Can't log in to my account and I was charged twice for premium!"
    dec = route_message(msg)
    assert dec.classification.primary_intent == "06_login_authentication"
    assert "04_billing_payment" in dec.classification.secondary_intents
    assert dec.target_queue == QUEUE_SECURITY_ACCOUNT_RECOVERY

    # Billing (04) + Plan Management (05) -> Billing wins
    msg2 = "I was double charged when trying to switch to family plan."
    dec2 = route_message(msg2)
    assert dec2.classification.primary_intent == "04_billing_payment"
    assert "05_subscription_plan_management" in dec2.classification.secondary_intents
    assert dec2.target_queue == QUEUE_BILLING_SUPPORT


def test_multi_turn_conversation_routing():
    """Verify multi-turn conversation parsing routes properly with combined context."""
    conv_dict = {
        "conversation_id": "conv_test_1",
        "ordered_messages": [
            {"author_id": "user1", "inbound": True, "text": "Hello, I have an issue"},
            {"author_id": "SpotifyCares", "inbound": False, "text": "Hi! How can we help?"},
            {"author_id": "user1", "inbound": True, "text": "My sheerid student verification link expired"},
        ],
    }
    decision = route_conversation(conv_dict)
    assert decision.classification.primary_intent == "05_subscription_plan_management"
    assert decision.target_queue == QUEUE_PLAN_MANAGEMENT
    assert decision.action == "subscription_plan_guidance"


def test_metadata_preservation_and_immutability():
    """Verify routing preserves Classification object without mutation."""
    cls_obj = Classification(
        primary_intent="04_billing_payment",
        secondary_intents=("05_subscription_plan_management",),
        technical_malfunction_scope=None,
        cross_cutting_flags=("alternate_channel_request",),
        is_non_intent=False,
        non_intent_class=None,
        confidence=0.88,
        evidence_quote="double charged",
    )

    decision = route_classification(cls_obj)
    assert decision.classification is cls_obj
    assert decision.classification.primary_intent == "04_billing_payment"
    assert decision.classification.secondary_intents == ("05_subscription_plan_management",)
    assert decision.classification.confidence == 0.88
