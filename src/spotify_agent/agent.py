"""End-to-end deterministic Spotify Support Agent orchestration.

This module unifies conversation parsing, intent classification,
operational routing, runtime resolution retrieval, and customer response
generation into a clean, immutable, and deterministic agent interface.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Set, Union

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
from src.spotify_agent.retriever import ResolutionRetriever, RetrievedEvidence
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

    @property
    def grounding_source(self) -> str:
        """Provenance of the generated response (historical_retrieval, curated_policy_fallback, escalation_override)."""
        return self.response.grounding_source

    @property
    def retrieved_evidence(self) -> Optional[tuple[RetrievedEvidence, ...]]:
        """Retrieved historical support resolutions used for grounding, if any."""
        return self.response.retrieved_evidence

    @property
    def similarity_score(self) -> Optional[float]:
        """Similarity score of the top-matched historical evidence."""
        return self.response.similarity_score


class SpotifySupportAgent:
    """Deterministic, pipeline-driven customer support agent for SpotifyCares."""

    def __init__(
        self,
        enable_retrieval: bool = True,
        custom_exclusion_ids: Optional[Set[str]] = None,
        retriever: Optional[ResolutionRetriever] = None,
    ) -> None:
        """Initialize the support agent.

        Args:
            enable_retrieval: If True, uses runtime historical-resolution RAG.
                              If False, reproduces baseline deterministic template responses.
            custom_exclusion_ids: Extra conversation IDs to strictly exclude from retrieval.
            retriever: Optional pre-initialized ResolutionRetriever instance.
        """
        self.enable_retrieval = enable_retrieval
        self._custom_exclusion_ids = set(custom_exclusion_ids or [])
        self._retriever = retriever

    @property
    def retriever(self) -> Optional[ResolutionRetriever]:
        """Lazy-loaded resolution retriever instance."""
        if not self.enable_retrieval:
            return None

        if self._retriever is None:
            self._retriever = ResolutionRetriever(
                custom_exclusion_ids=self._custom_exclusion_ids,
            )
        return self._retriever

    def process_message(
        self,
        message: Union[str, Dict[str, Any], ParsedMessage, ParsedConversation],
    ) -> AgentResult:
        """Process an inbound single customer message through the agent pipeline."""
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

        return self.process_conversation(conv)

    def process_conversation(
        self,
        conversation: Union[str, Dict[str, Any], ParsedConversation],
        exclude_self: bool = True,
    ) -> AgentResult:
        """Process a multi-turn conversation thread through the agent pipeline.

        Pipeline stages:
        1. Parse conversation structure and aggregate customer turns
        2. Classify customer intent deterministically
        3. Route classification to target operational queue & action
        4. (Optional) Retrieve relevant historical resolved support cases
        5. Generate customer-facing response (grounded or curated fallback)
        """
        conv = parse_conversation(conversation) if not isinstance(conversation, ParsedConversation) else conversation
        classification = classify_conversation(conv)
        routing = route_classification(classification)

        retrieved_candidates: List[RetrievedEvidence] = []
        if self.enable_retrieval and self.retriever is not None:
            query_text = conv.combined_customer_text
            exclude_id = conv.conversation_id if exclude_self else None
            retrieved_candidates = self.retriever.retrieve(
                query=query_text,
                top_k=3,
                exclude_conversation_id=exclude_id,
            )

        response = generate_response(
            decision_or_classification=routing,
            retrieved_candidates=retrieved_candidates,
            enable_retrieval=self.enable_retrieval,
            customer_query=conv.combined_customer_text,
        )

        return AgentResult(
            conversation=conv,
            classification=classification,
            routing=routing,
            response=response,
        )
