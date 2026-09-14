"""End-to-end deterministic Spotify Support Agent orchestration.

This module unifies conversation parsing, intent classification,
operational routing, and customer response generation into a clean,
immutable, and deterministic agent interface.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Union

from src.spotify_agent.conversation_parser import (
    ParsedConversation,
    ParsedMessage,
    parse_conversation,
    parse_message,
)
from src.spotify_agent.intent_classifier import (
    Classification,
    classify_conversation,
    classify_message,
)
from src.spotify_agent.response_generator import (
    AgentResponse,
    Response,
    generate_response,
)
from src.spotify_agent.routing_engine import (
    RoutingDecision,
    route_classification,
    route_conversation,
    route_message,
)


@dataclass(frozen=True)
class AgentResult:
    """Immutable result object of an end-to-end agent processing pipeline run."""

    conversation: ParsedConversation
    classification: Classification
    routing: RoutingDecision
    response: AgentResponse

    @property
    def text(self) -> str:
        """Customer-facing response text."""
        return self.response.text

    @property
    def action(self) -> str:
        """Operational action to perform."""
        return self.response.action

    @property
    def target_queue(self) -> str:
        """Target operational queue."""
        return self.routing.target_queue

    @property
    def requires_human_escalation(self) -> bool:
        """True if human specialist intervention is required."""
        return self.routing.requires_human_escalation

    @property
    def requires_channel_handoff(self) -> bool:
        """True if private DM channel handoff is required."""
        return self.routing.requires_channel_handoff


class SpotifySupportAgent:
    """Deterministic, pipeline-driven customer support agent for SpotifyCares."""

    def __init__(self) -> None:
        """Initialize the deterministic support agent."""
        pass

    def process_message(
        self,
        message: Union[str, Dict[str, Any], ParsedMessage, ParsedConversation],
    ) -> AgentResult:
        """Process an inbound single customer message through the agent pipeline.

        Pipeline stages:
        1. Parse conversation/message structure
        2. Classify customer intent deterministically
        3. Route classification to target operational queue & action
        4. Generate customer-facing response
        """
        if isinstance(message, ParsedConversation):
            conv = message
        elif isinstance(message, dict) and "ordered_messages" in message:
            conv = parse_conversation(message)
        elif isinstance(message, ParsedMessage):
            conv = parse_conversation({
                "ordered_messages": [
                    {
                        "author_id": message.author_id,
                        "inbound": message.is_inbound,
                        "text": message.text,
                    }
                ]
            })
        elif isinstance(message, dict):
            conv = parse_conversation({"ordered_messages": [message]})
        elif isinstance(message, str):
            conv = parse_conversation(message)
        else:
            raise TypeError(f"Unsupported message input type: {type(message).__name__}")

        classification = classify_conversation(conv)
        routing = route_classification(classification)
        response = generate_response(routing)

        return AgentResult(
            conversation=conv,
            classification=classification,
            routing=routing,
            response=response,
        )

    def process_conversation(
        self,
        conversation: Union[str, Dict[str, Any], ParsedConversation],
    ) -> AgentResult:
        """Process a multi-turn conversation thread through the agent pipeline.

        Pipeline stages:
        1. Parse conversation structure and aggregate customer turns
        2. Classify customer intent deterministically
        3. Route classification to target operational queue & action
        4. Generate customer-facing response
        """
        conv = parse_conversation(conversation)
        classification = classify_conversation(conv)
        routing = route_classification(classification)
        response = generate_response(routing)

        return AgentResult(
            conversation=conv,
            classification=classification,
            routing=routing,
            response=response,
        )
