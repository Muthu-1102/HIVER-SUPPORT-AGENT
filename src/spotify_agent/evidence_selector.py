"""Evidence selector and resolution extractor for retrieved historical precedents.

Filters, ranks, and structures historical evidence to ground runtime response generation.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Dict, List, Optional, Sequence

from src.spotify_agent.retriever import RetrievedEvidence


@dataclass(frozen=True)
class SelectedEvidence:
    """Selected historical resolution evidence prepared for response synthesis."""

    evidence: RetrievedEvidence
    similarity_score: float
    resolution_text: str
    action_types: tuple[str, ...]
    is_high_confidence: bool

    @property
    def conversation_id(self) -> str:
        return self.evidence.conversation_id

    def to_dict(self) -> Dict[str, Any]:
        return {
            "conversation_id": self.conversation_id,
            "similarity_score": round(self.similarity_score, 4),
            "resolution_text": self.resolution_text,
            "action_types": list(self.action_types),
            "is_high_confidence": self.is_high_confidence,
        }


def select_best_evidence(
    candidates: Sequence[RetrievedEvidence],
    min_similarity_threshold: float = 0.20,
    high_confidence_threshold: float = 0.35,
) -> Optional[SelectedEvidence]:
    """Select the best matching historical resolution evidence if above threshold.

    Returns None if no candidate achieves the minimum similarity threshold,
    triggering graceful fallback to the curated policy baseline.
    """
    if not candidates:
        return None

    top = candidates[0]
    if top.similarity_score < min_similarity_threshold:
        return None

    # Check if resolution text has substantive content
    res_text = top.resolution_text.strip()
    if len(res_text) < 15:
        return None

    return SelectedEvidence(
        evidence=top,
        similarity_score=top.similarity_score,
        resolution_text=res_text,
        action_types=top.resolution_actions,
        is_high_confidence=(top.similarity_score >= high_confidence_threshold),
    )
