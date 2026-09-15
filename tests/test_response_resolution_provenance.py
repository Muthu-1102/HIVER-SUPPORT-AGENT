"""Validation for design-time response-resolution provenance."""

import hashlib
import json
import re
from pathlib import Path

from src.spotify_agent.intent_classifier import SUBSTANTIVE_INTENTS
from src.spotify_agent.response_generator import RESPONSES


ROOT = Path(__file__).resolve().parents[1]
PROVENANCE_PATH = ROOT / "data/processed/response_resolution_provenance.json"
CORPUS_PATH = ROOT / "data/processed/spotify_conversations.jsonl"
GOLD_PATH = ROOT / "data/processed/golden_set_annotations.jsonl"


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_every_substantive_intent_has_design_time_provenance() -> None:
    artifact = json.loads(PROVENANCE_PATH.read_text(encoding="utf-8"))
    records = artifact["records"]
    assert artifact["runtime_usage"] == "none"
    assert {record["intent"] for record in records} == set(SUBSTANTIVE_INTENTS)
    assert len(records) == len(SUBSTANTIVE_INTENTS)
    assert all(record["representative_conversations"] for record in records)


def test_provenance_sources_exist_and_are_non_gold() -> None:
    artifact = json.loads(PROVENANCE_PATH.read_text(encoding="utf-8"))
    corpus = _read_jsonl(CORPUS_PATH)
    corpus_by_id = {record["conversation_thread_id"]: record for record in corpus}
    gold_ids = {record["conversation_id"] for record in _read_jsonl(GOLD_PATH)}

    source_ids = []
    for record in artifact["records"]:
        for source in record["representative_conversations"]:
            source_id = source["conversation_id"]
            source_ids.append(source_id)
            assert source_id in corpus_by_id
            assert source_id not in gold_ids
            assert corpus_by_id[source_id].get("reconstruction_flags", []) == []
            assert source["evidence_excerpt"].strip()
            assert source["observed_resolution_pattern"].strip()
            assert source["policy_influence"].strip()

    assert len(source_ids) == len(set(source_ids))


def test_provenance_excerpts_are_redacted_for_publication() -> None:
    artifact = json.loads(PROVENANCE_PATH.read_text(encoding="utf-8"))
    sensitive_patterns = [r"https?://", r"www\.", r"@[A-Za-z0-9_]", r"\b\S+@\S+\b"]
    for record in artifact["records"]:
        for source in record["representative_conversations"]:
            excerpt = source["evidence_excerpt"]
            assert not any(re.search(pattern, excerpt, re.IGNORECASE) for pattern in sensitive_patterns)


def test_response_templates_have_not_changed() -> None:
    """The provenance artifact must not alter deterministic response behavior."""
    serialized = json.dumps(RESPONSES, sort_keys=True, ensure_ascii=True).encode("utf-8")
    assert hashlib.sha256(serialized).hexdigest() == "cf6e010d7c4ad264e83617b362365b9e64961b580ccd8c025b33915d7c2b07bc"
