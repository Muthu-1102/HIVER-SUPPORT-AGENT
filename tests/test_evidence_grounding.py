"""Unit tests for evidence grounding, feature flag parity, and escalation guardrails."""

import pytest

from src.spotify_agent.agent import SpotifySupportAgent
from src.spotify_agent.response_generator import RESPONSES, generate_response
from src.spotify_agent.routing_engine import (
    QUEUE_BILLING_SUPPORT,
    QUEUE_PRIVATE_CHANNEL_HANDOFF,
    QUEUE_SENIOR_SUPPORT_ESCALATION,
    QUEUE_TECHNICAL_TROUBLESHOOTING,
)


def test_feature_flag_false_reproduces_static_baseline():
    """Verify enable_retrieval=False exactly reproduces static baseline responses."""
    agent_static = SpotifySupportAgent(enable_retrieval=False)

    msg = "I was double charged on my card for premium"
    result = agent_static.process_message(msg)

    assert result.text == RESPONSES["04_billing_payment"]
    assert result.target_queue == QUEUE_BILLING_SUPPORT
    assert result.grounding_source == "curated_policy_fallback"
    assert result.retrieved_evidence is None


def test_feature_flag_true_enables_historical_grounding():
    """Verify enable_retrieval=True retrieves historical evidence and grounds response."""
    agent_rag = SpotifySupportAgent(enable_retrieval=True)

    msg = "My app keeps crashing whenever I try to play my offline downloaded songs on iPhone"
    result = agent_rag.process_message(msg)

    assert result.classification.primary_intent == "07_technical_malfunction"
    assert result.grounding_source == "historical_retrieval"
    assert result.retrieved_evidence is not None
    assert len(result.retrieved_evidence) > 0
    assert result.similarity_score is not None
    assert result.similarity_score > 0.0

    # Ensure response text contains actionable guidance
    assert len(result.text) > 20
    assert "@" not in result.text


def test_escalation_override_takes_absolute_precedence_over_retrieval():
    """Verify customer dissatisfaction escalation is NEVER overridden by retrieval."""
    agent_rag = SpotifySupportAgent(enable_retrieval=True)

    msg = "This is the third time I am contacting you and nobody has replied. Fix this now!"
    result = agent_rag.process_message(msg)

    assert result.requires_human_escalation is True
    assert result.target_queue == QUEUE_SENIOR_SUPPORT_ESCALATION
    assert result.grounding_source == "escalation_override"
    assert result.text == RESPONSES["dissatisfaction_escalation"]


def test_channel_handoff_override_takes_absolute_precedence():
    """Verify private DM requests always route to handoff regardless of retrieval."""
    agent_rag = SpotifySupportAgent(enable_retrieval=True)

    msg = "Can you send me a DM? I need to share my private email address."
    result = agent_rag.process_message(msg)

    assert result.requires_channel_handoff is True
    assert result.target_queue == QUEUE_PRIVATE_CHANNEL_HANDOFF
    assert result.grounding_source == "escalation_override"
    assert result.text == RESPONSES["channel_handoff"]


def test_non_intent_acknowledgment_preserves_safe_behavior():
    """Verify non-intent acknowledgment yields advocacy reply."""
    agent_rag = SpotifySupportAgent(enable_retrieval=True)

    msg = "Thank you so much, everything is working great now!"
    result = agent_rag.process_message(msg)

    assert result.classification.is_non_intent is True
    assert result.text == RESPONSES["no_action_acknowledgment_only"]
