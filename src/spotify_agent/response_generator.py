"""Deterministic response generator for Spotify customer support.

This module generates professional, concise, customer-facing responses
based on the Classification and RoutingDecision.

Responses are strictly deterministic and never leak internal taxonomy
identifiers, routing queue names, or confidence metrics to the customer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Union

from src.spotify_agent.conversation_parser import (
    ParsedConversation,
    ParsedMessage,
)
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
)


@dataclass(frozen=True)
class AgentResponse:
    """Standard customer-facing response paired with operational routing metadata."""

    text: str
    action: str
    requires_human_escalation: bool
    requires_channel_handoff: bool
    target_queue: str


# Alias for compatibility
Response = AgentResponse


# Standard customer-facing response templates
RESPONSES = {
    # Flag Overrides
    "dissatisfaction_escalation": (
        "We understand your frustration regarding previous delays and apologize for the inconvenience. "
        "We have escalated your inquiry directly to our senior support specialists for priority review. "
        "A team member will follow up with you as soon as possible."
    ),
    "channel_handoff": (
        "To protect your private account details and look into this further, please send us a Direct Message (DM) "
        "with your Spotify account email address so we can assist you securely."
    ),

    # Non-Intent Classes
    "insufficient_information": (
        "Thanks for reaching out! Could you please share a few more details about what you're experiencing? "
        "If you are seeing an error message or having trouble on a specific device, letting us know will help us assist you."
    ),
    "out_of_scope_non_support": (
        "Thanks for the message! Our channel is dedicated to Spotify technical and account support. "
        "If you have an active account, billing, or playback question, feel free to let us know!"
    ),
    "no_action_acknowledgment_only": (
        "You're very welcome! Glad to hear everything is sorted out. "
        "If you ever need assistance in the future, don't hesitate to reach back out. Happy listening!"
    ),

    # Substantive Intents
    "06_login_authentication": (
        "If you are having trouble logging in or need to reset your password, please visit spotify.com/password-reset. "
        "If you suspect unauthorized access or your account email was changed without your consent, our security team "
        "will assist you in securing and recovering your account."
    ),
    "04_billing_payment": (
        "For billing and charge inquiries, you can check your transaction history and active subscription details at "
        "spotify.com/account/subscription. If you notice an unexpected or duplicate charge, our billing team will review "
        "your account charges."
    ),
    "07_technical_malfunction_platform": (
        "We are actively monitoring our systems. If there is a temporary platform-wide issue affecting playback or "
        "connectivity, our technical operations team is investigating. Please check back shortly."
    ),
    "07_technical_malfunction_individual": (
        "To troubleshoot playback or device issues, try restarting the Spotify app, checking for updates in your app store, "
        "and clearing your local cache in Spotify Settings > Storage. If the issue persists, a clean reinstall often resolves it."
    ),
    "07_technical_malfunction_unclear": (
        "Let's get this working! Try restarting the Spotify app and ensuring your device and app are updated to the latest "
        "version. If the problem continues, please let us know your device model and OS version so we can investigate."
    ),
    "05_subscription_plan_management": (
        "To manage your subscription, switch plans, or invite family members, head to your account page at "
        "spotify.com/account. For student plan verification, you can check your student status and renew verification "
        "through SheerID on your account overview."
    ),
    "03_region_availability": (
        "Track availability and subscription features can vary by country due to licensing agreements with rights holders. "
        "If you have moved or are traveling, you can check and update your registered country under your profile at "
        "spotify.com/account."
    ),
    "01_catalog_content_gap": (
        "Music and podcast availability on Spotify depends on licensing permissions from artists and record labels. "
        "While we strive to have all tracks available, catalogs can vary over time. Following the artist on Spotify "
        "is the best way to get notified when new releases arrive."
    ),
    "02_catalog_metadata_error": (
        "Thank you for reporting this metadata issue. We have logged the details regarding the track, artist credits, "
        "or lyrics so our content operations team can review and correct the catalog entry."
    ),
    "08_feature_request": (
        "Thanks for sharing your idea with us! We're always looking to improve Spotify. You can submit and vote on "
        "new feature requests directly on the Spotify Community Ideas board at community.spotify.com."
    ),
    "09_artist_rights_holder_mgmt": (
        "For artist profile verification, track uploads, and creator support, please access the Spotify for Artists portal "
        "at artists.spotify.com. If you are a rights holder needing to submit a DMCA or rights claim, you can use our "
        "official content claim form."
    ),
}


def generate_response(
    decision_or_classification: Union[RoutingDecision, Classification, ParsedConversation, ParsedMessage, Dict[str, Any], str],
) -> AgentResponse:
    """Generate a deterministic customer-facing response matching the routing decision.

    Consumes either a RoutingDecision directly, or any input compatible with
    classification and routing.
    """
    if isinstance(decision_or_classification, RoutingDecision):
        decision = decision_or_classification
    elif isinstance(decision_or_classification, Classification):
        decision = route_classification(decision_or_classification)
    elif isinstance(decision_or_classification, (ParsedConversation, dict)) and (
        isinstance(decision_or_classification, ParsedConversation) or "ordered_messages" in decision_or_classification
    ):
        cls = classify_conversation(decision_or_classification)
        decision = route_classification(cls)
    else:
        cls = classify_message(decision_or_classification)
        decision = route_classification(cls)

    classification = decision.classification

    # 1. Check human escalation for customer dissatisfaction
    if decision.requires_human_escalation or decision.target_queue == QUEUE_SENIOR_SUPPORT_ESCALATION:
        response_text = RESPONSES["dissatisfaction_escalation"]
        return AgentResponse(
            text=response_text,
            action=decision.action,
            requires_human_escalation=decision.requires_human_escalation,
            requires_channel_handoff=decision.requires_channel_handoff,
            target_queue=decision.target_queue,
        )

    # 2. Check channel handoff request
    if decision.requires_channel_handoff or decision.target_queue == QUEUE_PRIVATE_CHANNEL_HANDOFF:
        response_text = RESPONSES["channel_handoff"]
        return AgentResponse(
            text=response_text,
            action=decision.action,
            requires_human_escalation=decision.requires_human_escalation,
            requires_channel_handoff=decision.requires_channel_handoff,
            target_queue=decision.target_queue,
        )

    # 3. Non-Intent handling
    if classification.is_non_intent:
        non_intent_class = classification.non_intent_class or classification.primary_intent
        if non_intent_class == "no_action_acknowledgment_only":
            response_text = RESPONSES["no_action_acknowledgment_only"]
        elif non_intent_class == "out_of_scope_non_support":
            response_text = RESPONSES["out_of_scope_non_support"]
        else:
            response_text = RESPONSES["insufficient_information"]

        return AgentResponse(
            text=response_text,
            action=decision.action,
            requires_human_escalation=decision.requires_human_escalation,
            requires_channel_handoff=decision.requires_channel_handoff,
            target_queue=decision.target_queue,
        )

    # 4. Substantive Intent handling
    primary = classification.primary_intent

    if primary == "07_technical_malfunction":
        scope = classification.technical_malfunction_scope or "unclear"
        if scope == "platform_wide":
            response_text = RESPONSES["07_technical_malfunction_platform"]
        elif scope == "individual":
            response_text = RESPONSES["07_technical_malfunction_individual"]
        else:
            response_text = RESPONSES["07_technical_malfunction_unclear"]
    elif primary in RESPONSES:
        response_text = RESPONSES[primary]
    else:
        # Safe fallback
        response_text = RESPONSES["insufficient_information"]

    return AgentResponse(
        text=response_text,
        action=decision.action,
        requires_human_escalation=decision.requires_human_escalation,
        requires_channel_handoff=decision.requires_channel_handoff,
        target_queue=decision.target_queue,
    )
