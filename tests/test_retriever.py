"""Unit tests for runtime resolution retriever and strict data-leakage isolation."""

import json
from pathlib import Path
import pytest

from src.spotify_agent.retriever import ResolutionRetriever, RetrievedEvidence

PROJECT_ROOT = Path(__file__).resolve().parent.parent
GOLD_ANNOTATIONS_PATH = PROJECT_ROOT / "data" / "processed" / "golden_set_annotations.jsonl"
EXCLUSIONS_PATH = PROJECT_ROOT / "data" / "processed" / "golden_set_exclusions.txt"
HISTORICAL_RESOLUTIONS_PATH = PROJECT_ROOT / "data" / "processed" / "historical_resolutions.jsonl"


def test_retriever_initialization():
    """Verify retriever initializes with proper default exclusion sets."""
    retriever = ResolutionRetriever()
    assert len(retriever.exclusion_ids) >= 200
    retriever.load_index()
    assert retriever._is_indexed is True
    assert len(retriever.records) > 10000


def test_zero_gold_leakage_in_retrieval_corpus():
    """CRITICAL TEST: Verify that 0% of canonical gold IDs are retrievable."""
    retriever = ResolutionRetriever()
    retriever.load_index()

    gold_ids = set()
    with open(GOLD_ANNOTATIONS_PATH, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                gold_ids.add(json.loads(line)["conversation_id"])

    corpus_ids = set(retriever.record_ids)

    overlap = corpus_ids.intersection(gold_ids)
    assert len(overlap) == 0, f"DATA LEAKAGE DETECTED: {len(overlap)} gold IDs present in retrieval index: {overlap}"


def test_zero_design_time_exclusion_leakage():
    """Verify design-time audit IDs are strictly excluded."""
    retriever = ResolutionRetriever()
    retriever.load_index()

    exclusion_ids = set()
    with open(EXCLUSIONS_PATH, "r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if s and not s.startswith("#"):
                exclusion_ids.add(s)

    corpus_ids = set(retriever.record_ids)
    overlap = corpus_ids.intersection(exclusion_ids)
    assert len(overlap) == 0, f"DATA LEAKAGE: Design-time exclusions present in index: {overlap}"


def test_dynamic_exclusion_and_self_retrieval_prevention():
    """Verify a query conversation can never retrieve its own historical record."""
    retriever = ResolutionRetriever()
    retriever.load_index()

    # Pick an existing record from index
    sample_rec = retriever.records[10]
    sample_cid = sample_rec["conversation_id"]
    query = sample_rec["customer_query"]

    # Retrieve with exclude_conversation_id set to sample_cid
    results = retriever.retrieve(query=query, top_k=5, exclude_conversation_id=sample_cid)
    retrieved_cids = [r.conversation_id for r in results]

    assert sample_cid not in retrieved_cids, f"Self-retrieval violation: {sample_cid} was retrieved for itself!"


def test_retrieval_returns_traceable_evidence():
    """Verify retrieved results contain valid scores, conversation IDs, and actions."""
    retriever = ResolutionRetriever()
    results = retriever.retrieve(query="my student discount renewal is failing sheerid", top_k=3)

    assert len(results) > 0
    for r in results:
        assert isinstance(r, RetrievedEvidence)
        assert r.conversation_id.startswith("spotify_root_")
        assert r.similarity_score > 0.0
        assert len(r.resolution_text) > 5
        assert isinstance(r.resolution_actions, tuple)


def test_empty_query_returns_empty_list():
    """Verify blank or whitespace queries return empty results without error."""
    retriever = ResolutionRetriever()
    assert retriever.retrieve("") == []
    assert retriever.retrieve("   ") == []
