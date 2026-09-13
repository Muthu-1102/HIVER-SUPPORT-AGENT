import json
from pathlib import Path
import sys
import pytest

# Ensure root is in sys.path
sys.path.insert(0, str(Path(__file__).parents[1]))

from scripts.create_golden_set import (
    generate_golden_set_candidates,
    compute_deterministic_hash,
    load_exclusions,
    FIXED_SALT,
    get_strata_specifications,
)

CORPUS_PATH = Path("data/processed/spotify_conversations.jsonl")
EXCLUSIONS_PATH = Path("data/processed/golden_set_exclusions.txt")
CANDIDATES_PATH = Path("data/processed/golden_set_candidates.jsonl")


def test_deterministic_hash_consistency():
    """Verify deterministic hash produces consistent SHA256 output with fixed salt."""
    tid = "spotify_root_12345"
    h1 = compute_deterministic_hash(tid, FIXED_SALT)
    h2 = compute_deterministic_hash(tid, FIXED_SALT)
    assert h1 == h2
    assert len(h1) == 64


def test_exclusion_loading():
    """Verify exclusion list is properly loaded from file."""
    exclusions = load_exclusions(EXCLUSIONS_PATH)
    assert len(exclusions) >= 28
    assert "spotify_root_784880" in exclusions
    assert "spotify_root_904057" in exclusions
    assert "spotify_root_1151701" in exclusions


def test_golden_set_candidate_file_exists_and_valid():
    """Verify candidate file exists, is valid JSONL, and contains exactly 200 unique records."""
    assert CANDIDATES_PATH.exists()
    records = []
    with CANDIDATES_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))

    assert len(records) == 200

    # Verify uniqueness
    ids = [r["conversation_id"] for r in records]
    assert len(set(ids)) == 200, "Duplicate conversation IDs found in candidate set"


def test_golden_set_exclusions_strictly_enforced():
    """Verify no excluded conversation IDs appear in the generated candidates."""
    exclusions = load_exclusions(EXCLUSIONS_PATH)
    with CANDIDATES_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            assert (
                rec["conversation_id"] not in exclusions
            ), f"Excluded conversation {rec['conversation_id']} found in candidate set!"


def test_multi_turn_quota_enforced():
    """Verify that at least 35% (>= 70 threads) are multi-turn conversations."""
    records = []
    with CANDIDATES_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            records.append(json.loads(line))

    multi_turn_count = sum(1 for r in records if r["is_multi_turn"])
    assert (
        multi_turn_count >= 70
    ), f"Multi-turn count {multi_turn_count} is less than required 70 (35%)"
    for r in records:
        assert r["is_multi_turn"] == (r["customer_brand_interaction_turn_count"] >= 2)


def test_schema_and_metadata_preservation():
    """Verify all required metadata and thread reconstruction fields are preserved."""
    required_fields = {
        "conversation_id",
        "sampling_strata",
        "candidate_intent",
        "technical_scope_candidate",
        "prior_interaction_dissatisfaction_candidate",
        "alternate_channel_request_candidate",
        "is_multi_turn",
        "is_structural_risk",
        "sampling_hash",
        "thread_root_tweet_id",
        "ordered_messages",
        "conversation_depth",
        "contains_customer_and_spotify",
        "customer_brand_interaction_turn_count",
        "contains_two_or_more_customer_brand_interaction_turns",
        "reconstruction_flags",
    }

    with CANDIDATES_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            missing = required_fields - set(rec.keys())
            assert not missing, f"Record {rec.get('conversation_id')} missing fields: {missing}"
            assert isinstance(rec["sampling_strata"], list)
            assert len(rec["sampling_strata"]) >= 1
            assert isinstance(rec["ordered_messages"], list)
            assert len(rec["ordered_messages"]) >= 1
            assert rec["contains_customer_and_spotify"] is True
            assert rec["sampling_hash"] == compute_deterministic_hash(rec["conversation_id"])


def test_strata_representation_coverage():
    """Verify all 24 required sampling strata are represented in the candidate set."""
    strata_specs = get_strata_specifications()
    all_strata_names = {s[0] for s in strata_specs}

    records = []
    with CANDIDATES_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            records.append(json.loads(line))

    represented_strata = {s for r in records for s in r["sampling_strata"]}
    missing_strata = all_strata_names - represented_strata
    assert not missing_strata, f"Missing required strata representation: {missing_strata}"


def test_unstratified_control_exact_count():
    """Verify that exactly 14 candidates are tagged with unstratified_control stratum."""
    records = []
    with CANDIDATES_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            records.append(json.loads(line))

    control_records = [r for r in records if "unstratified_control" in r["sampling_strata"]]
    assert len(control_records) == 14, f"Expected exactly 14 unstratified control records, found {len(control_records)}"


def test_technical_malfunction_scopes_represented():
    """Verify individual, platform_wide, and unclear technical malfunction scopes are present."""
    records = []
    with CANDIDATES_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            records.append(json.loads(line))

    tech_records = [
        r for r in records
        if "intent_baseline_07_technical_malfunction_individual" in r["sampling_strata"]
        or "intent_baseline_07_technical_malfunction_platform_wide" in r["sampling_strata"]
        or "intent_baseline_07_technical_malfunction_unclear" in r["sampling_strata"]
    ]
    assert len(tech_records) >= 16

    scopes = {r["technical_scope_candidate"] for r in tech_records}
    assert "individual" in scopes
    assert "platform_wide" in scopes
    assert "unclear" in scopes


def test_deterministic_reproducibility(tmp_path):
    """Verify running the generator on the same input produces byte-for-byte identical output."""
    out1 = tmp_path / "cand1.jsonl"
    out2 = tmp_path / "cand2.jsonl"

    generate_golden_set_candidates(
        input_path=CORPUS_PATH,
        output_candidates_path=out1,
        exclusions_path=EXCLUSIONS_PATH,
        salt=FIXED_SALT,
        target_total=200,
    )

    generate_golden_set_candidates(
        input_path=CORPUS_PATH,
        output_candidates_path=out2,
        exclusions_path=EXCLUSIONS_PATH,
        salt=FIXED_SALT,
        target_total=200,
    )

    assert out1.read_bytes() == out2.read_bytes(), "Deterministic rerun produced differing output"


def test_loud_failure_on_shortfall(tmp_path):
    """Verify that candidate generation fails loudly with diagnostic report when quota cannot be fulfilled."""
    tiny_corpus = tmp_path / "tiny.jsonl"
    # Create tiny corpus with only 1 conversation
    single_conv = {
        "conversation_thread_id": "spotify_root_999999",
        "thread_root_tweet_id": "999999",
        "contains_customer_and_spotify": True,
        "customer_brand_interaction_turn_count": 1,
        "conversation_depth": 0,
        "contains_two_or_more_customer_brand_interaction_turns": False,
        "reconstruction_flags": [],
        "ordered_messages": [
            {
                "tweet_id": "999999",
                "author_id": "cust1",
                "inbound": True,
                "text": "song missing on spotify",
            },
            {
                "tweet_id": "1000000",
                "author_id": "SpotifyCares",
                "inbound": False,
                "text": "we will check",
            },
        ],
    }
    with tiny_corpus.open("w", encoding="utf-8") as f:
        f.write(json.dumps(single_conv) + "\n")

    tiny_out = tmp_path / "tiny_out.jsonl"
    empty_exclusions = tmp_path / "exclusions.txt"
    empty_exclusions.write_text("", encoding="utf-8")

    with pytest.raises(RuntimeError) as excinfo:
        generate_golden_set_candidates(
            input_path=tiny_corpus,
            output_candidates_path=tiny_out,
            exclusions_path=empty_exclusions,
            salt=FIXED_SALT,
            target_total=200,
        )

    err_text = str(excinfo.value)
    assert "FAIL: Stratum quota shortfall detected:" in err_text
    assert "Required:" in err_text
    assert "Available:" in err_text
    assert "Shortfall:" in err_text
