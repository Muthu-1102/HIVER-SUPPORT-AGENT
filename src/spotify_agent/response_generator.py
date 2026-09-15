"""Grounded response generator for Spotify customer support.

This module generates professional, concise, customer-facing responses
based on the Classification, RoutingDecision, and optional runtime
retrieved historical resolutions.

Key properties:
- Fully backwards-compatible with deterministic static templates.
- Supports runtime evidence grounding from historical Spotify support resolutions.
- Guarantees strict escalation & security guardrails (routing decisions always override retrieval).
- Validates all generated outputs through safety & sanitization filters.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Dict, List, Optional, Sequence, Union

from src.spotify_agent.conversation_parser import (
    ParsedConversation,
    ParsedMessage,
)
from src.spotify_agent.evidence_selector import SelectedEvidence, select_best_evidence
from src.spotify_agent.intent_classifier import (
    Classification,
    classify_conversation,
    classify_message,
)
from src.spotify_agent.retriever import RetrievedEvidence
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
from src.spotify_agent.safety_validator import sanitize_response_text, validate_response_safety


@dataclass(frozen=True)
class AgentResponse:
    """Customer-facing response paired with operational routing metadata and grounding provenance."""

    text: str
    action: str
    requires_human_escalation: bool
    requires_channel_handoff: bool
    target_queue: str
    grounding_source: str = "curated_policy_fallback"  # "historical_retrieval" | "curated_policy_fallback" | "escalation_override"
    retrieved_evidence: Optional[tuple[RetrievedEvidence, ...]] = None
    similarity_score: Optional[float] = None


# Alias for compatibility
Response = AgentResponse


# Standard customer-facing response templates (Curated Policy Baselines)
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


def _synthesize_grounded_response(
    intent: str,
    scope: Optional[str],
    evidence: SelectedEvidence,
    customer_query: str,
) -> str:
    """Synthesize a customer-facing response grounded in historical resolution evidence."""
    res_text = sanitize_response_text(evidence.resolution_text)

    # Ensure clean punctuation
    if not res_text.endswith((".", "!", "?")):
        res_text += "."

    # Adapt historical precedent based on intent and evidence actions
    actions = set(evidence.action_types)

    if intent == "07_technical_malfunction":
        if scope == "platform_wide":
            return RESPONSES["07_technical_malfunction_platform"]

        # Adapt troubleshooting sequence to customer query context
        parts = ["Thanks for reaching out!"]
        if "gather_device_diagnostics" in actions and not any(k in customer_query.lower() for k in ["iphone", "android", "windows", "mac", "ios", "version", "update"]):
            parts.append("Could you let us know what device model, operating system, and Spotify version you're running?")

        parts.append("To troubleshoot playback or device issues, try restarting the Spotify app and clearing your local cache in Spotify Settings > Storage.")

        if "clean_reinstall" in actions or "reinstall" in res_text.lower():
            parts.append("If the glitch continues, performing a clean reinstall of the app often resolves it.")
        elif len(res_text) > 15 and not any(p in res_text.lower() for p in ["hey there", "hey!", "hello!"]):
            parts.append(res_text)

        return " ".join(parts)

    elif intent == "04_billing_payment":
        if "request_dm" in actions or "dm" in res_text.lower():
            return (
                "For billing and account charges, please send us a Direct Message (DM) with your account email address "
                "so our billing specialists can securely look into your payment history. You can also view active charges "
                "at spotify.com/account/subscription."
            )
        return (
            f"{res_text} You can also review your billing history and subscription status directly at "
            "spotify.com/account/subscription."
        )

    elif intent == "05_subscription_plan_management":
        if "student_verification" in actions or "sheerid" in customer_query.lower():
            return (
                "For student discount verification and renewal, you can complete the SheerID verification process "
                "directly on your account overview at spotify.com/account."
            )
        return (
            f"{res_text} You can manage active plans and family member invites anytime at spotify.com/account."
        )

    elif intent == "01_catalog_content_gap":
        return (
            "Music and podcast availability on Spotify can change over time based on licensing agreements with artists "
            "and record labels. Following the artist profile on Spotify is the quickest way to receive notifications when "
            "releases become available in your region."
        )

    elif intent == "03_region_availability":
        return (
            f"{res_text} To check or update your account's registered country, visit your profile settings at "
            "spotify.com/account."
        )

    elif intent == "08_feature_request":
        return (
            "Thanks for sharing your suggestion with us! You can post and vote on feature ideas directly on our Spotify "
            "Community Ideas board at community.spotify.com so our product team can review feedback."
        )

    elif intent == "09_artist_rights_holder_mgmt":
        return (
            "For artist profile claims, release verification, and creator support, head over to artists.spotify.com. "
            "Our creator operations team will be happy to assist you there."
        )

    elif intent == "02_catalog_metadata_error":
        return (
            "Thank you for reporting this metadata error. We have noted the details so our catalog operations team "
            "can review and correct the track credits and metadata."
        )

    elif intent == "06_login_authentication":
        return (
            "If you need to reset your password or regain access, please visit spotify.com/password-reset. "
            "If your login email was altered or you suspect unauthorized access, our security team will assist in recovering your account."
        )

    return res_text


def generate_response(
    decision_or_classification: Union[RoutingDecision, Classification, ParsedConversation, ParsedMessage, Dict[str, Any], str],
    retrieved_candidates: Optional[Sequence[RetrievedEvidence]] = None,
    enable_retrieval: bool = False,
    customer_query: str = "",
) -> AgentResponse:
    """Generate a customer-facing response matching the routing decision and retrieved evidence.

    Pipeline:
    1. Check human escalation & private DM requirements (CRITICAL POLICY OVERRIDES).
    2. Check non-intent classes (insufficient info, out-of-scope, acknowledgment).
    3. If enable_retrieval is True and relevant evidence exists: synthesize evidence-grounded response.
    4. Fall back safely to curated policy templates.
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
        if isinstance(decision_or_classification, ParsedConversation):
            customer_query = decision_or_classification.combined_customer_text
    else:
        cls = classify_message(decision_or_classification)
        decision = route_classification(cls)
        if isinstance(decision_or_classification, str):
            customer_query = decision_or_classification

    classification = decision.classification

    # 1. HARD OVERRIDE: Human escalation for customer dissatisfaction
    if decision.requires_human_escalation or decision.target_queue == QUEUE_SENIOR_SUPPORT_ESCALATION:
        return AgentResponse(
            text=RESPONSES["dissatisfaction_escalation"],
            action=decision.action,
            requires_human_escalation=decision.requires_human_escalation,
            requires_channel_handoff=decision.requires_channel_handoff,
            target_queue=decision.target_queue,
            grounding_source="escalation_override",
        )

    # 2. HARD OVERRIDE: Channel handoff request
    if decision.requires_channel_handoff or decision.target_queue == QUEUE_PRIVATE_CHANNEL_HANDOFF:
        return AgentResponse(
            text=RESPONSES["channel_handoff"],
            action=decision.action,
            requires_human_escalation=decision.requires_human_escalation,
            requires_channel_handoff=decision.requires_channel_handoff,
            target_queue=decision.target_queue,
            grounding_source="escalation_override",
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
            grounding_source="curated_policy_fallback",
        )

    # 4. Substantive Intent handling
    primary = classification.primary_intent
    scope = classification.technical_malfunction_scope

    # Attempt runtime evidence grounding if enabled
    if enable_retrieval and retrieved_candidates:
        selected = select_best_evidence(retrieved_candidates)
        if selected is not None:
            synthesized = _synthesize_grounded_response(
                intent=primary,
                scope=scope,
                evidence=selected,
                customer_query=customer_query,
            )
            clean_synthesized = sanitize_response_text(synthesized)
            is_safe, _ = validate_response_safety(clean_synthesized)

            if is_safe:
                return AgentResponse(
                    text=clean_synthesized,
                    action=decision.action,
                    requires_human_escalation=decision.requires_human_escalation,
                    requires_channel_handoff=decision.requires_channel_handoff,
                    target_queue=decision.target_queue,
                    grounding_source="historical_retrieval",
                    retrieved_evidence=tuple(retrieved_candidates),
                    similarity_score=selected.similarity_score,
                )

    # 5. Curated Policy Template Fallback
    if primary == "07_technical_malfunction":
        if scope == "platform_wide":
            response_text = RESPONSES["07_technical_malfunction_platform"]
        elif scope == "individual":
            response_text = RESPONSES["07_technical_malfunction_individual"]
        else:
            response_text = RESPONSES["07_technical_malfunction_unclear"]
    elif primary in RESPONSES:
        response_text = RESPONSES[primary]
    else:
        response_text = RESPONSES["insufficient_information"]

    return AgentResponse(
        text=response_text,
        action=decision.action,
        requires_human_escalation=decision.requires_human_escalation,
        requires_channel_handoff=decision.requires_channel_handoff,
        target_queue=decision.target_queue,
        grounding_source="curated_policy_fallback",
        retrieved_evidence=tuple(retrieved_candidates) if retrieved_candidates else None,
    )
