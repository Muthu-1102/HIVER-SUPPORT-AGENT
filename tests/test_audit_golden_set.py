import json
from pathlib import Path
import sys
import pytest
sys.path.insert(0, str(Path(__file__).parents[1]))
from scripts.audit_golden_set import audit_golden_set, FIXED_SALT
CANDIDATES_PATH = Path("data/processed/golden_set_candidates.jsonl")
EXCLUSIONS_PATH = Path("data/processed/golden_set_exclusions.txt")
def test_audit_golden_set_success():
    """Verify that audit_golden_set passes completely on the canonical candidate dataset."""
    results = audit_golden_set(
        candidates_path=CANDIDATES_PATH,
        exclusions_path=EXCLUSIONS_PATH,
        salt=FIXED_SALT,
    )
    assert results["overall_passed"] is True
    assert results["total_records"] == 200
    assert results["unique_conversation_ids"] == 200
    assert len(results["duplicate_conversation_ids"]) == 0
    assert len(results["leaked_exclusions"]) == 0
    assert results["missing_fields_count"] == 0
    assert len(results["duplicate_tweet_ids_in_thread"]) == 0
    assert results["invalid_hash_format_count"] == 0
    assert results["mismatched_hashes_count"] == 0
    assert results["multi_turn_count"] >= 70
    assert all(q["passed"] for q in results["quota_results"])
def test_audit_detects_duplicate_conversation_id(tmp_path):
    """Verify audit fails when duplicate conversation IDs are present."""
    lines = CANDIDATES_PATH.read_text(encoding="utf-8").strip().splitlines()
    # Duplicate first record
    bad_lines = lines[:-1] + [lines[0]]
    bad_file = tmp_path / "dup_conv.jsonl"
    bad_file.write_text("\n".join(bad_lines) + "\n", encoding="utf-8")
    results = audit_golden_set(
        candidates_path=bad_file,
        exclusions_path=EXCLUSIONS_PATH,
        salt=FIXED_SALT,
    )
    assert results["overall_passed"] is False
    assert len(results["duplicate_conversation_ids"]) > 0
def test_audit_detects_leaked_exclusion(tmp_path):
    """Verify audit fails when an excluded conversation ID is present."""
    records = [json.loads(x) for x in CANDIDATES_PATH.read_text(encoding="utf-8").strip().splitlines()]
    records[0]["conversation_id"] = "spotify_root_784880"
    records[0]["sampling_hash"] = "invalid_hash"
    bad_file = tmp_path / "leaked.jsonl"
    with bad_file.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    results = audit_golden_set(
        candidates_path=bad_file,
        exclusions_path=EXCLUSIONS_PATH,
        salt=FIXED_SALT,
    )
    assert results["overall_passed"] is False
    assert "spotify_root_784880" in results["leaked_exclusions"]
def test_audit_detects_missing_schema_field(tmp_path):
    """Verify audit fails when required schema fields are missing."""
    records = [json.loads(x) for x in CANDIDATES_PATH.read_text(encoding="utf-8").strip().splitlines()]
    del records[0]["ordered_messages"]
    bad_file = tmp_path / "missing_field.jsonl"
    with bad_file.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    results = audit_golden_set(
        candidates_path=bad_file,
        exclusions_path=EXCLUSIONS_PATH,
        salt=FIXED_SALT,
    )
    assert results["overall_passed"] is False
    assert results["missing_fields_count"] > 0
def test_audit_detects_duplicate_tweet_id_in_thread(tmp_path):
    """Verify audit fails when duplicate tweet IDs occur inside a conversation thread."""
    records = [json.loads(x) for x in CANDIDATES_PATH.read_text(encoding="utf-8").strip().splitlines()]
    # Introduce duplicate tweet ID in first record
    if records[0]["ordered_messages"]:
        first_msg = records[0]["ordered_messages"][0]
        records[0]["ordered_messages"].append(dict(first_msg))
    bad_file = tmp_path / "dup_tweet.jsonl"
    with bad_file.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    results = audit_golden_set(
        candidates_path=bad_file,
        exclusions_path=EXCLUSIONS_PATH,
        salt=FIXED_SALT,
    )
    assert results["overall_passed"] is False
    assert len(results["duplicate_tweet_ids_in_thread"]) > 0
def test_audit_detects_hash_tampering(tmp_path):
    """Verify audit fails when sampling hash is corrupted or does not match conversation_id + salt."""
    records = [json.loads(x) for x in CANDIDATES_PATH.read_text(encoding="utf-8").strip().splitlines()]
    records[0]["sampling_hash"] = "0" * 64
    bad_file = tmp_path / "bad_hash.jsonl"
    with bad_file.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    results = audit_golden_set(
        candidates_path=bad_file,
        exclusions_path=EXCLUSIONS_PATH,
        salt=FIXED_SALT,
    )
    assert results["overall_passed"] is False
    assert results["mismatched_hashes_count"] > 0
def test_audit_detects_unstratified_control_anomaly(tmp_path):
    """Verify audit fails when unstratified_control stratum is misapplied (e.g., to all 200 records)."""
    records = [json.loads(x) for x in CANDIDATES_PATH.read_text(encoding="utf-8").strip().splitlines()]
    # Incorrectly tag all records as unstratified_control
    for r in records:
        if "unstratified_control" not in r["sampling_strata"]:
            r["sampling_strata"].append("unstratified_control")
    bad_file = tmp_path / "bad_control.jsonl"
    with bad_file.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    results = audit_golden_set(
        candidates_path=bad_file,
        exclusions_path=EXCLUSIONS_PATH,
        salt=FIXED_SALT,
    )
    assert results["overall_passed"] is False
    ctrl_quota = next(q for q in results["quota_results"] if q["key"] == "unstratified_control")
    assert ctrl_quota["passed"] is False
    assert ctrl_quota["actual"] == 200
    assert ctrl_quota["shortfall"] == 186
