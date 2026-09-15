"""Runtime historical-resolution retriever for the Spotify Support Agent.

Enables runtime evidence retrieval from 28,000+ sanitized historical
Spotify support resolutions, strictly excluding:
- Canonical gold evaluation records (200 records)
- Design-time provenance and exclusion records (28 records)
- Dynamic evaluation/holdout query IDs

Uses TF-IDF sparse vector indexing with sublinear term-frequency scaling
and cosine similarity for sub-millisecond, zero-dependency retrieval.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import logging
from pathlib import Path
import re
import sys
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_RESOLUTIONS_PATH = PROJECT_ROOT / "data" / "processed" / "historical_resolutions.jsonl"
DEFAULT_GOLD_PATH = PROJECT_ROOT / "data" / "processed" / "golden_set_annotations.jsonl"
DEFAULT_EXCLUSIONS_PATH = PROJECT_ROOT / "data" / "processed" / "golden_set_exclusions.txt"


@dataclass(frozen=True)
class RetrievedEvidence:
    """A single retrieved historical resolution precedent with full provenance."""

    conversation_id: str
    similarity_score: float
    customer_query: str
    resolution_text: str
    resolution_actions: tuple[str, ...]
    turn_count: int
    all_agent_resolutions: tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        """Convert evidence to serializable dictionary."""
        return {
            "conversation_id": self.conversation_id,
            "similarity_score": round(self.similarity_score, 4),
            "customer_query": self.customer_query,
            "resolution_text": self.resolution_text,
            "resolution_actions": list(self.resolution_actions),
            "turn_count": self.turn_count,
            "all_agent_resolutions": list(self.all_agent_resolutions),
        }


class ResolutionRetriever:
    """Deterministic, high-speed sparse retriever for historical support resolutions."""

    def __init__(
        self,
        corpus_path: Path = DEFAULT_RESOLUTIONS_PATH,
        custom_exclusion_ids: Optional[Set[str]] = None,
        min_similarity_threshold: float = 0.20,
    ) -> None:
        """Initialize the historical resolution retriever."""
        self.corpus_path = Path(corpus_path)
        self.min_similarity_threshold = min_similarity_threshold

        # Compile total exclusion set (gold + design-time + custom)
        self.exclusion_ids: Set[str] = set()
        self._load_default_exclusions()
        if custom_exclusion_ids:
            self.exclusion_ids.update(custom_exclusion_ids)

        # In-memory corpus records and vector index
        self.records: List[Dict[str, Any]] = []
        self.record_ids: List[str] = []
        self.vectorizer: Optional[TfidfVectorizer] = None
        self.tfidf_matrix: Any = None
        self._is_indexed: bool = False

    def _load_default_exclusions(self) -> None:
        """Load protected canonical gold IDs and design-time exclusions."""
        if DEFAULT_GOLD_PATH.is_file():
            with open(DEFAULT_GOLD_PATH, "r", encoding="utf-8") as f:
                for line in f:
                    line_str = line.strip()
                    if line_str:
                        try:
                            data = json.loads(line_str)
                            cid = data.get("conversation_id")
                            if cid:
                                self.exclusion_ids.add(cid)
                        except Exception:
                            pass

        if DEFAULT_EXCLUSIONS_PATH.is_file():
            with open(DEFAULT_EXCLUSIONS_PATH, "r", encoding="utf-8") as f:
                for line in f:
                    line_str = line.strip()
                    if line_str and not line_str.startswith("#"):
                        self.exclusion_ids.add(line_str)

    def add_exclusion_ids(self, ids: Sequence[str]) -> None:
        """Add additional runtime conversation IDs to exclude from retrieval."""
        self.exclusion_ids.update(ids)

    def load_index(self) -> None:
        """Load corpus and build TF-IDF sparse matrix index."""
        if self._is_indexed:
            return

        if not self.corpus_path.is_file():
            # Graceful degraded mode if corpus file does not exist yet
            logger.warning("Resolution corpus file not found: %s", self.corpus_path)
            self._is_indexed = True
            return

        corpus_texts: List[str] = []
        self.records = []
        self.record_ids = []

        with open(self.corpus_path, "r", encoding="utf-8") as f:
            for line in f:
                line_str = line.strip()
                if not line_str:
                    continue
                rec = json.loads(line_str)
                cid = rec.get("conversation_id")

                # Strict exclusion check
                if not cid or cid in self.exclusion_ids:
                    continue

                # Query target is customer query context
                query_target = rec.get("customer_query", "")
                if not query_target:
                    continue

                self.records.append(rec)
                self.record_ids.append(cid)
                corpus_texts.append(query_target)

        if corpus_texts:
            self.vectorizer = TfidfVectorizer(
                ngram_range=(1, 2),
                min_df=2,
                max_df=0.85,
                sublinear_tf=True,
                stop_words="english",
            )
            self.tfidf_matrix = self.vectorizer.fit_transform(corpus_texts)

        self._is_indexed = True

    def retrieve(
        self,
        query: str,
        top_k: int = 3,
        exclude_conversation_id: Optional[str] = None,
    ) -> List[RetrievedEvidence]:
        """Retrieve Top-K historical support resolutions for a given customer query.

        Guarantees:
        1. Excludes all gold & protected IDs.
        2. Excludes query's own conversation ID (if provided).
        3. Returns strictly traceable candidate resolutions with similarity scores.
        """
        if not self._is_indexed:
            self.load_index()

        if not query or not query.strip() or self.tfidf_matrix is None or self.vectorizer is None or not self.records:
            return []

        # Vectorize query
        clean_query = query.strip()
        query_vec = self.vectorizer.transform([clean_query])

        # Compute cosine similarity across entire corpus
        sims = cosine_similarity(query_vec, self.tfidf_matrix)[0]

        # Find top candidates
        top_indices = np.argsort(sims)[::-1]

        results: List[RetrievedEvidence] = []
        for idx in top_indices:
            score = float(sims[idx])
            if score <= 0.0:
                break

            cid = self.record_ids[idx]

            # Dynamic exclusion checks
            if exclude_conversation_id and cid == exclude_conversation_id:
                continue
            if cid in self.exclusion_ids:
                continue

            rec = self.records[idx]
            evidence = RetrievedEvidence(
                conversation_id=cid,
                similarity_score=score,
                customer_query=rec.get("customer_query", ""),
                resolution_text=rec.get("resolution_text", ""),
                resolution_actions=tuple(rec.get("resolution_actions") or []),
                turn_count=rec.get("turn_count", 0),
                all_agent_resolutions=tuple(rec.get("all_agent_resolutions") or []),
            )
            results.append(evidence)

            if len(results) >= top_k:
                break

        return results
