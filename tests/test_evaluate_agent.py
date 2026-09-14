"""Unit and integration tests for the Golden Set evaluation harness."""

import hashlib
import json
from pathlib import Path
import pytest

from scripts.evaluate_agent import (
    ERROR_ANALYSIS_JSONL_PATH,
    GOLDEN_ANNOTATIONS_PATH,
    GOLDEN_CANDIDATES_PATH,
    RESULTS_JSON_PATH,
    evaluate_agent,
    load_jsonl,
)


def _file_sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def test_evaluator_runs_and_evaluates_all_200_records(tmp_path: Path):
    """Verify evaluator processes all 200 golden set candidate records."""
    results_file = tmp_path / "test_results.json"
    error_file = tmp_path / "test_error_analysis.jsonl"

    report = evaluate_agent(
        results_path=results_file,
        error_analysis_path=error_file,
    )

    assert report["metrics"]["total_records"] == 200
    assert results_file.exists()
    assert error_file.exists()

    with open(results_file, "r", encoding="utf-8") as f:
        saved_report = json.load(f)

    assert saved_report["metrics"]["total_records"] == 200
    assert 0.0 <= saved_report["metrics"]["primary_intent_accuracy"] <= 1.0


def test_no_duplicate_conversation_ids():
    """Verify gold annotations and candidates have 200 distinct unique IDs."""
    gold_records = load_jsonl(GOLDEN_ANNOTATIONS_PATH)
    cand_records = load_jsonl(GOLDEN_CANDIDATES_PATH)

    gold_ids = [r["conversation_id"] for r in gold_records]
    cand_ids = [r["conversation_id"] for r in cand_records]

    assert len(gold_ids) == 200
    assert len(set(gold_ids)) == 200
    assert len(cand_ids) == 200
    assert len(set(cand_ids)) == 200
    assert set(gold_ids) == set(cand_ids)


def test_evaluator_deterministic_across_repeated_runs(tmp_path: Path):
    """Verify repeated evaluation runs produce bit-for-bit identical outputs."""
    r1 = tmp_path / "run1_results.json"
    e1 = tmp_path / "run1_errors.jsonl"
    r2 = tmp_path / "run2_results.json"
    e2 = tmp_path / "run2_errors.jsonl"

    evaluate_agent(results_path=r1, error_analysis_path=e1)
    evaluate_agent(results_path=r2, error_analysis_path=e2)

    assert _file_sha256(r1) == _file_sha256(r2)
    assert _file_sha256(e1) == _file_sha256(e2)


def test_error_analysis_record_structure(tmp_path: Path):
    """Verify error analysis records contain required audit fields."""
    r = tmp_path / "results.json"
    e = tmp_path / "errors.jsonl"

    evaluate_agent(results_path=r, error_analysis_path=e)

    error_records = load_jsonl(e)
    for err in error_records:
        assert "conversation_id" in err
        assert "customer_text" in err
        assert "gold_classification" in err
        assert "predicted_classification" in err
        assert "mismatched_fields" in err
        assert isinstance(err["mismatched_fields"], list)
        assert len(err["mismatched_fields"]) > 0


def test_source_files_immutability(tmp_path: Path):
    """Verify running the evaluation does not mutate golden dataset source files."""
    initial_cand_hash = _file_sha256(GOLDEN_CANDIDATES_PATH)
    initial_gold_hash = _file_sha256(GOLDEN_ANNOTATIONS_PATH)

    r = tmp_path / "results.json"
    e = tmp_path / "errors.jsonl"
    evaluate_agent(results_path=r, error_analysis_path=e)

    assert _file_sha256(GOLDEN_CANDIDATES_PATH) == initial_cand_hash
    assert _file_sha256(GOLDEN_ANNOTATIONS_PATH) == initial_gold_hash


def test_no_hardcoded_conversation_ids_in_evaluator():
    """Verify scripts/evaluate_agent.py does not hardcode conversation IDs."""
    eval_code = Path("scripts/evaluate_agent.py").read_text(encoding="utf-8")
    assert "spotify_root_" not in eval_code


def test_non_intent_metric_reports_none_when_zero_gold_examples(tmp_path: Path):
    """Verify evaluator reports None / N/A for non_intent_accuracy when zero gold non-intent examples exist."""
    # Create a synthetic 2-record candidate and annotation dataset with 0 non-intent examples
    cand_file = tmp_path / "substantive_cands.jsonl"
    gold_file = tmp_path / "substantive_golds.jsonl"
    results_file = tmp_path / "results.json"
    error_file = tmp_path / "errors.jsonl"

    all_cands = load_jsonl(GOLDEN_CANDIDATES_PATH)
    all_golds = load_jsonl(GOLDEN_ANNOTATIONS_PATH)

    # Pick only substantive records (is_non_intent == False)
    sub_golds = [g for g in all_golds if not g.get("is_non_intent")][:5]
    sub_ids = {g["conversation_id"] for g in sub_golds}
    sub_cands = [c for c in all_cands if c["conversation_id"] in sub_ids]

    with open(gold_file, "w", encoding="utf-8") as f:
        for g in sub_golds:
            f.write(json.dumps(g) + "\n")
    with open(cand_file, "w", encoding="utf-8") as f:
        for c in sub_cands:
            f.write(json.dumps(c) + "\n")

    report = evaluate_agent(
        candidates_path=cand_file,
        annotations_path=gold_file,
        results_path=results_file,
        error_analysis_path=error_file,
    )

    metrics = report["metrics"]
    assert metrics["non_intent_total"] == 0
    assert metrics["non_intent_correct"] == 0
    assert metrics["non_intent_accuracy"] is None


def test_canonical_evaluation_non_intent_metric(tmp_path: Path):
    """Verify canonical 200-record evaluation tracks non_intent_total and non_intent_correct properly."""
    results_file = tmp_path / "results.json"
    error_file = tmp_path / "errors.jsonl"

    report = evaluate_agent(
        results_path=results_file,
        error_analysis_path=error_file,
    )

    metrics = report["metrics"]
    assert metrics["non_intent_total"] == 12
    assert metrics["non_intent_correct"] == 12
    assert metrics["non_intent_accuracy"] == 1.0


