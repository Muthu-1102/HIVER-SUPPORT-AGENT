"""Unit tests for the holdout evaluation harness."""

import json
from pathlib import Path
import pytest

from scripts.evaluate_holdout import (
    DEFAULT_SAMPLE_SIZE,
    DEFAULT_SEED,
    evaluate_holdout,
    extract_eligible_holdout_conversations,
    load_canonical_gold_ids,
    sample_holdout_conversations,
)


def test_load_canonical_gold_ids():
    """Verify that canonical gold IDs are loaded accurately (200 records)."""
    gold_ids = load_canonical_gold_ids()
    assert len(gold_ids) == 200
    assert all(cid.startswith("spotify_root_") for cid in gold_ids)


def test_holdout_strict_zero_overlap():
    """Verify that no holdout candidate exists in the canonical gold dataset."""
    gold_ids = load_canonical_gold_ids()
    eligible = extract_eligible_holdout_conversations(gold_ids=gold_ids)

    # Invariant: zero overlap
    eligible_ids = {r["conversation_id"] for r in eligible}
    overlap = eligible_ids.intersection(gold_ids)
    assert len(overlap) == 0, f"Found overlapping IDs: {overlap}"
    assert len(eligible) > 1000, "Expected thousands of eligible non-gold conversations"


def test_holdout_deterministic_sampling():
    """Verify that sampling is strictly deterministic across runs with fixed seed."""
    gold_ids = load_canonical_gold_ids()
    eligible = extract_eligible_holdout_conversations(gold_ids=gold_ids)

    sample_1 = sample_holdout_conversations(eligible, sample_size=50, seed=42)
    sample_2 = sample_holdout_conversations(eligible, sample_size=50, seed=42)

    assert len(sample_1) == 50
    assert len(sample_2) == 50
    assert [r["conversation_id"] for r in sample_1] == [r["conversation_id"] for r in sample_2]


def test_holdout_evaluation_pipeline(tmp_path: Path):
    """Verify end-to-end holdout execution and output JSON schema."""
    out_file = tmp_path / "holdout_results.json"
    summary = evaluate_holdout(results_path=out_file, sample_size=10, seed=42)

    assert summary["evaluation_type"] == "UNLABELED / QUALITATIVE GENERALIZATION HOLDOUT"
    assert summary["canonical_gold_overlap_count"] == 0
    assert summary["sampled_holdout_count"] == 10
    assert len(summary["holdout_evaluations"]) == 10

    # Verify each evaluation record contains valid non-empty predictions
    for eval_rec in summary["holdout_evaluations"]:
        assert eval_rec["conversation_id"].startswith("spotify_root_")
        assert eval_rec["message_count"] >= 2
        assert "target_queue" in eval_rec
        assert "action" in eval_rec
        assert "response_preview" in eval_rec

    assert out_file.exists()
    saved = json.loads(out_file.read_text(encoding="utf-8"))
    assert saved["sampled_holdout_count"] == 10
