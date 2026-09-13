"""Focused unit tests for the deterministic Spotify response generator."""

import pytest

from src.spotify_agent.intent_classifier import (
    NON_INTENT_CLASSES,
    SUBSTANTIVE_INTENTS,
    Classification,
    classify_message,
)
from src.spotify_agent.response_generator import (
    AgentResponse,
    Response,
    generate_response,
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
    route_message,
)


INTERNAL_LEAKAGE_TERMS = list(SUBSTANTIVE_INTENTS) + list(NON_INTENT_CLASSES) + [
    QUEUE_SECURITY_ACCOUNT_RECOVERY,
    QUEUE_BILLING_SUPPORT,
    QUEUE_TECHNICAL_TROUBLESHOOTING,
    QUEUE_PLAN_MANAGEMENT,
    QUEUE_REGIONAL_LICENSING,
    QUEUE_CATALOG_CONTENT,
    QUEUE_CATALOG_METADATA,
    QUEUE_PRODUCT_FEEDBACK,
    QUEUE_ARTIST_RIGHTS,
    QUEUE_SENIOR_SUPPORT_ESCALATION,
    QUEUE_PRIVATE_CHANNEL_HANDOFF,
    QUEUE_CLARIFICATION,
    QUEUE_SOCIAL_NON_SUPPORT,
    QUEUE_ACKNOWLEDGMENT_CLOSE,
    "confidence",
    "is_non_intent",
    "primary_intent",
    "secondary_intents",
    "cross_cutting_flags",
    "technical_malfunction_scope",
    "schema_version",
]


def _assert_no_internal_leakage(text: str):
    """Ensure internal taxonomy and routing terms do not leak into customer text."""
    lowered = text.lower()
    for term in INTERNAL_LEAKAGE_TERMS:
        assert term.lower() not in lowered, f"Internal term '{term}' leaked in response text: {text}"


def test_substantive_intents_responses():
    """Verify customer response generation for all 9 substantive intents."""
    test_queries = [
        ("06_login_authentication", "I forgot my password and cannot log into my account."),
        ("04_billing_payment", "Why was I charged twice for Spotify Premium this month?"),
        ("07_technical_malfunction", "App keeps crashing whenever I tap a playlist on my iPhone."),
        ("05_subscription_plan_management", "How do I invite my family members to our Family Plan?"),
        ("03_region_availability", "Why is this artist's music greyed out in my country?"),
        ("01_catalog_content_gap", "When will Young Thug's new album be added to Spotify?"),
        ("02_catalog_metadata_error", "The track title is misspelled on album track 4."),
        ("08_feature_request", "Please add a dark mode toggle and playlist folders on mobile."),
        ("09_artist_rights_holder_mgmt", "How do I claim and verify my artist profile on Spotify for Artists?"),
    ]

    for expected_intent, query in test_queries:
        resp = generate_response(query)
        assert isinstance(resp, AgentResponse)
        assert isinstance(resp.text, str) and len(resp.text) > 30
        assert resp.action
        assert resp.target_queue
        _assert_no_internal_leakage(resp.text)


def test_non_intent_classes_responses():
    """Verify safe customer responses for all 3 non-intent classes."""
    # 1. insufficient_information
    resp_vague = generate_response("Help me please")
    assert resp_vague.target_queue == QUEUE_CLARIFICATION
    assert resp_vague.action == "request_more_information"
    assert "more details" in resp_vague.text.lower() or "details" in resp_vague.text.lower()
    _assert_no_internal_leakage(resp_vague.text)

    # 2. out_of_scope_non_support
    resp_social = generate_response("I love spotify and music!")
    assert resp_social.target_queue == QUEUE_SOCIAL_NON_SUPPORT
    assert resp_social.action == "social_engagement_or_ignore"
    _assert_no_internal_leakage(resp_social.text)

    # 3. no_action_acknowledgment_only
    resp_ack = generate_response("Thanks, that fixed it!")
    assert resp_ack.target_queue == QUEUE_ACKNOWLEDGMENT_CLOSE
    assert resp_ack.action == "close_ticket_acknowledged"
    assert "welcome" in resp_ack.text.lower() or "happy listening" in resp_ack.text.lower()
    _assert_no_internal_leakage(resp_ack.text)


def test_human_escalation_dissatisfaction():
    """Verify dissatisfaction triggers senior escalation response."""
    msg = "This is the third time reaching out! Sent 5 messages and still no reply regarding my account charge."
    resp = generate_response(msg)

    assert resp.requires_human_escalation is True
    assert resp.target_queue == QUEUE_SENIOR_SUPPORT_ESCALATION
    assert resp.action == "escalate_to_senior_support"
    assert "senior support" in resp.text.lower()
    _assert_no_internal_leakage(resp.text)


def test_channel_handoff_response():
    """Verify channel handoff triggers private DM response."""
    msg = "Please DM me directly to help with my subscription issue."
    resp = generate_response(msg)

    assert resp.requires_channel_handoff is True
    assert resp.target_queue == QUEUE_PRIVATE_CHANNEL_HANDOFF
    assert "direct message" in resp.text.lower() or "dm" in resp.text.lower()
    _assert_no_internal_leakage(resp.text)


def test_technical_malfunction_scopes_responses():
    """Verify responses differ appropriately by technical scope."""
    # Platform-wide scope
    resp_plat = generate_response("Is Spotify down for everyone right now? Servers are down.")
    assert "monitoring" in resp_plat.text.lower() or "platform-wide" in resp_plat.text.lower()
    _assert_no_internal_leakage(resp_plat.text)

    # Individual scope
    resp_ind = generate_response("The repeat button is not working on my iPhone.")
    assert "reinstall" in resp_ind.text.lower() or "cache" in resp_ind.text.lower()
    _assert_no_internal_leakage(resp_ind.text)

    # Unclear scope
    resp_unclear = generate_response("Audio skipping and playback error.")
    assert "model and os version" in resp_unclear.text.lower() or "restarting" in resp_unclear.text.lower()
    _assert_no_internal_leakage(resp_unclear.text)


def test_deterministic_reproducibility():
    """Verify identical inputs produce identical responses across multiple runs."""
    inputs = [
        "Why was I charged twice for Spotify?",
        "Can't log in to my account, password reset link not working",
        "Songs are buffering constantly",
        {"ordered_messages": [{"author_id": "u1", "inbound": True, "text": "Thanks that fixed it"}]},
    ]

    for inp in inputs:
        res1 = generate_response(inp)
        res2 = generate_response(inp)
        assert res1 == res2
        assert res1.text == res2.text
        assert res1.action == res2.action
        assert res1.target_queue == res2.target_queue
        assert res1.requires_human_escalation == res2.requires_human_escalation
        assert res1.requires_channel_handoff == res2.requires_channel_handoff
