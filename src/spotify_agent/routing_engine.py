"""Deterministic routing engine for Spotify customer support.

This module consumes the Classification output from intent_classifier.py
and determines the operational routing decision (target queue, action,
priority, and escalation/handoff flags) based on the frozen taxonomy rules
defined in docs/intent_taxonomy.md.

Routing is strictly deterministic, non-destructive, and consumes
Classification metadata without modifying the underlying classification.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple, Union

from src.spotify_agent.conversation_parser import (
    ParsedConversation,
    ParsedMessage,
)
from src.spotify_agent.intent_classifier import (
    Classification,
    classify_conversation,
    classify_message,
)


# Standard Operational Queue Identifiers
QUEUE_SECURITY_ACCOUNT_RECOVERY = "security_account_recovery"
QUEUE_BILLING_SUPPORT = "billing_support"
QUEUE_TECHNICAL_TROUBLESHOOTING = "technical_troubleshooting"
QUEUE_PLAN_MANAGEMENT = "plan_management"
QUEUE_REGIONAL_LICENSING = "regional_licensing_support"
QUEUE_CATALOG_CONTENT = "catalog_content_support"
QUEUE_CATALOG_METADATA = "catalog_metadata_operations"
QUEUE_PRODUCT_FEEDBACK = "product_feedback_pipeline"
QUEUE_ARTIST_RIGHTS = "artist_rights_support"
QUEUE_SENIOR_SUPPORT_ESCALATION = "senior_support_escalation"
QUEUE_PRIVATE_CHANNEL_HANDOFF = "private_channel_handoff"
QUEUE_CLARIFICATION = "clarification_queue"
QUEUE_SOCIAL_NON_SUPPORT = "social_non_support"
QUEUE_ACKNOWLEDGMENT_CLOSE = "acknowledgment_close"


@dataclass(frozen=True)
class RoutingDecision:
    """Operational routing decision derived from classification metadata."""

    target_queue: str
    action: str
    priority: str
    requires_human_escalation: bool
    requires_channel_handoff: bool
    classification: Classification
    routing_reason: str


def route_classification(classification: Classification) -> RoutingDecision:
    """Determine operational routing from a Classification result."""
    has_dissatisfaction = "prior_interaction_dissatisfaction" in classification.cross_cutting_flags
    has_channel_request = "alternate_channel_request" in classification.cross_cutting_flags

    # 1. Flag Override: Prior interaction dissatisfaction forces immediate senior escalation
    if has_dissatisfaction:
        return RoutingDecision(
            target_queue=QUEUE_SENIOR_SUPPORT_ESCALATION,
            action="escalate_to_senior_support",
            priority="critical",
            requires_human_escalation=True,
            requires_channel_handoff=has_channel_request,
            classification=classification,
            routing_reason="Prior interaction dissatisfaction flagged; routing to senior human escalation.",
        )

    # 2. Flag Override: Alternate channel request triggers secure channel handoff
    if has_channel_request:
        return RoutingDecision(
            target_queue=QUEUE_PRIVATE_CHANNEL_HANDOFF,
            action="initiate_secure_channel_handoff",
            priority="high" if classification.primary_intent in ("06_login_authentication", "04_billing_payment") else "normal",
            requires_human_escalation=False,
            requires_channel_handoff=True,
            classification=classification,
            routing_reason="Alternate channel request flagged; routing to secure channel handoff workflow.",
        )

    # 3. Non-Intent Handling
    if classification.is_non_intent:
        non_intent_class = classification.non_intent_class or classification.primary_intent

        if non_intent_class == "no_action_acknowledgment_only":
            return RoutingDecision(
                target_queue=QUEUE_ACKNOWLEDGMENT_CLOSE,
                action="close_ticket_acknowledged",
                priority="low",
                requires_human_escalation=False,
                requires_channel_handoff=False,
                classification=classification,
                routing_reason="Non-intent acknowledgment only; closing ticket with polite confirmation.",
            )
        elif non_intent_class == "out_of_scope_non_support":
            return RoutingDecision(
                target_queue=QUEUE_SOCIAL_NON_SUPPORT,
                action="social_engagement_or_ignore",
                priority="low",
                requires_human_escalation=False,
                requires_channel_handoff=False,
                classification=classification,
                routing_reason="Non-intent social banter or out-of-scope mention; no support ticket created.",
            )
        else:  # insufficient_information
            return RoutingDecision(
                target_queue=QUEUE_CLARIFICATION,
                action="request_more_information",
                priority="normal",
                requires_human_escalation=False,
                requires_channel_handoff=False,
                classification=classification,
                routing_reason="Insufficient context to determine substantive intent; requesting customer clarification.",
            )

    # 4. Substantive Intent Routing
    primary = classification.primary_intent

    if primary == "06_login_authentication":
        return RoutingDecision(
            target_queue=QUEUE_SECURITY_ACCOUNT_RECOVERY,
            action="account_security_and_recovery",
            priority="critical",
            requires_human_escalation=False,
            requires_channel_handoff=False,
            classification=classification,
            routing_reason="High priority login and authentication security workflow.",
        )

    elif primary == "04_billing_payment":
        return RoutingDecision(
            target_queue=QUEUE_BILLING_SUPPORT,
            action="billing_and_payment_inquiry",
            priority="high",
            requires_human_escalation=False,
            requires_channel_handoff=False,
            classification=classification,
            routing_reason="Monetary dispute / billing transaction inquiry routed to billing queue.",
        )

    elif primary == "07_technical_malfunction":
        scope = classification.technical_malfunction_scope or "unclear"
        if scope == "platform_wide":
            action = "platform_outage_monitoring"
            priority = "high"
            reason = "Platform-wide technical malfunction scope detected; routing to outage status flow."
        elif scope == "individual":
            action = "individual_device_troubleshooting"
            priority = "normal"
            reason = "Individual technical malfunction scope detected; routing to device troubleshooting flow."
        else:
            action = "technical_diagnostic_clarification"
            priority = "normal"
            reason = "Unclear technical malfunction scope; routing to diagnostic troubleshooting."

        return RoutingDecision(
            target_queue=QUEUE_TECHNICAL_TROUBLESHOOTING,
            action=action,
            priority=priority,
            requires_human_escalation=False,
            requires_channel_handoff=False,
            classification=classification,
            routing_reason=reason,
        )

    elif primary == "05_subscription_plan_management":
        return RoutingDecision(
            target_queue=QUEUE_PLAN_MANAGEMENT,
            action="subscription_plan_guidance",
            priority="normal",
            requires_human_escalation=False,
            requires_channel_handoff=False,
            classification=classification,
            routing_reason="Plan change, family plan member invite, or student verification inquiry.",
        )

    elif primary == "03_region_availability":
        return RoutingDecision(
            target_queue=QUEUE_REGIONAL_LICENSING,
            action="regional_availability_guidance",
            priority="normal",
            requires_human_escalation=False,
            requires_channel_handoff=False,
            classification=classification,
            routing_reason="Geographical licensing restriction or region setting inquiry.",
        )

    elif primary == "01_catalog_content_gap":
        return RoutingDecision(
            target_queue=QUEUE_CATALOG_CONTENT,
            action="catalog_availability_lookup",
            priority="low",
            requires_human_escalation=False,
            requires_channel_handoff=False,
            classification=classification,
            routing_reason="Catalog inquiry for missing song, album, or unreleased content.",
        )

    elif primary == "02_catalog_metadata_error":
        return RoutingDecision(
            target_queue=QUEUE_CATALOG_METADATA,
            action="log_metadata_correction_ticket",
            priority="low",
            requires_human_escalation=False,
            requires_channel_handoff=False,
            classification=classification,
            routing_reason="Catalog metadata error report routed to content operations.",
        )

    elif primary == "08_feature_request":
        return RoutingDecision(
            target_queue=QUEUE_PRODUCT_FEEDBACK,
            action="log_product_feedback",
            priority="low",
            requires_human_escalation=False,
            requires_channel_handoff=False,
            classification=classification,
            routing_reason="Product feedback or feature suggestion routed to community/feedback pipeline.",
        )

    elif primary == "09_artist_rights_holder_mgmt":
        return RoutingDecision(
            target_queue=QUEUE_ARTIST_RIGHTS,
            action="artist_portal_support_routing",
            priority="normal",
            requires_human_escalation=False,
            requires_channel_handoff=False,
            classification=classification,
            routing_reason="Spotify for Artists or rights-holder inquiry routed to creator support.",
        )

    # Fallback safe default
    return RoutingDecision(
        target_queue=QUEUE_CLARIFICATION,
        action="request_more_information",
        priority="normal",
        requires_human_escalation=False,
        requires_channel_handoff=False,
        classification=classification,
        routing_reason=f"Unrecognized intent '{primary}'; fallback to clarification.",
    )


def route_message(
    message: Union[str, Dict[str, Any], ParsedMessage, ParsedConversation]
) -> RoutingDecision:
    """Convenience helper to classify and route a single message or thread."""
    classification = classify_message(message)
    return route_classification(classification)


def route_conversation(
    conversation: Union[str, Dict[str, Any], ParsedConversation]
) -> RoutingDecision:
    """Convenience helper to classify and route a multi-turn conversation."""
    classification = classify_conversation(conversation)
    return route_classification(classification)
