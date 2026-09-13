import copy
import ast
import json
from pathlib import Path
import sys
import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))

from scripts.validate_gold_annotations import (
    validate_annotation_record,
    validate_annotations_file,
    verify_candidates_immutability,
    EXPECTED_CANDIDATES_SHA256,
    SCHEMA_VERSION,
    SUBSTANTIVE_INTENTS,
    NON_INTENT_CLASSES,
    CROSS_CUTTING_FLAGS,
    TECHNICAL_MALFUNCTION_SCOPES,
)
from scripts.adjudicate_annotations import (
    compute_inter_annotator_agreement,
    process_adjudications,
    get_effective_primary_label,
)

CANDIDATES_PATH = Path("data/processed/golden_set_candidates.jsonl")


@pytest.fixture
def valid_candidate_ids():
    """Load valid candidate IDs from canonical candidates file."""
    ok, msg, cids = verify_candidates_immutability(CANDIDATES_PATH)
    assert ok, msg
    return cids


@pytest.fixture
def sample_valid_annotation(valid_candidate_ids):
    """Return a single valid substantive intent annotation record."""
    cid = next(iter(valid_candidate_ids))
    return {
        "conversation_id": cid,
        "annotator_id": "annotator_1",
        "annotation_timestamp": "2026-09-13T12:00:00Z",
        "is_non_intent": False,
        "primary_intent": "01_catalog_content_gap",
        "secondary_intents": ["08_feature_request"],
        "non_intent_class": None,
        "technical_malfunction_scope": None,
        "cross_cutting_flags": ["alternate_channel_request"],
        "is_ambiguous": True,
        "ambiguity_category": "01_08",
        "ambiguity_notes": "User asked for unreleased song and suggested adding a preorder feature.",
        "confidence": "high",
        "evidence_quote": "when is this song coming to spotify, please add it",
        "schema_version": "1.0.0",
    }


def test_candidate_file_immutability():
    """Verify that golden_set_candidates.jsonl is unmodified and matches recorded SHA-256."""
    ok, msg, cids = verify_candidates_immutability(CANDIDATES_PATH)
    assert ok, msg
    assert len(cids) == 200


def test_valid_annotation_passes_validation(sample_valid_annotation, valid_candidate_ids):
    """Verify that a compliant annotation record passes validation with zero errors."""
    errors = validate_annotation_record(sample_valid_annotation, valid_candidate_ids)
    assert not errors, f"Unexpected validation errors: {errors}"


def test_schema_missing_fields(sample_valid_annotation, valid_candidate_ids):
    """Verify that missing required schema fields are detected."""
    rec = copy.deepcopy(sample_valid_annotation)
    del rec["annotator_id"]
    del rec["confidence"]
    errors = validate_annotation_record(rec, valid_candidate_ids)
    assert any("Missing required field: 'annotator_id'" in e for e in errors)
    assert any("Missing required field: 'confidence'" in e for e in errors)


def test_invalid_schema_version(sample_valid_annotation, valid_candidate_ids):
    """Verify that unsupported schema_version fails validation."""
    rec = copy.deepcopy(sample_valid_annotation)
    rec["schema_version"] = "2.0.0"
    errors = validate_annotation_record(rec, valid_candidate_ids)
    assert any("Invalid schema_version" in e for e in errors)


def test_referential_integrity(sample_valid_annotation, valid_candidate_ids):
    """Verify that unknown conversation_id not in candidates fails validation."""
    rec = copy.deepcopy(sample_valid_annotation)
    rec["conversation_id"] = "spotify_root_nonexistent_9999999"
    errors = validate_annotation_record(rec, valid_candidate_ids)
    assert any("Referential integrity violation" in e for e in errors)


def test_mutual_exclusivity_non_intent(sample_valid_annotation, valid_candidate_ids):
    """Verify mutual exclusivity: is_non_intent == True requires null primary_intent and valid non_intent_class."""
    rec = copy.deepcopy(sample_valid_annotation)
    rec["is_non_intent"] = True
    rec["non_intent_class"] = "insufficient_information"
    rec["primary_intent"] = None
    rec["secondary_intents"] = []
    errors = validate_annotation_record(rec, valid_candidate_ids)
    assert not errors

    # Violate: set primary_intent while is_non_intent is True
    rec["primary_intent"] = "01_catalog_content_gap"
    errors = validate_annotation_record(rec, valid_candidate_ids)
    assert any("primary_intent must be null" in e for e in errors)

    # Violate: invalid non_intent_class
    rec["primary_intent"] = None
    rec["non_intent_class"] = "random_unapproved_class"
    errors = validate_annotation_record(rec, valid_candidate_ids)
    assert any("non_intent_class must be one of" in e for e in errors)


def test_mutual_exclusivity_substantive(sample_valid_annotation, valid_candidate_ids):
    """Verify mutual exclusivity: is_non_intent == False requires valid primary_intent and null non_intent_class."""
    rec = copy.deepcopy(sample_valid_annotation)
    rec["is_non_intent"] = False
    rec["non_intent_class"] = "out_of_scope_non_support"  # Illegal when is_non_intent is False
    errors = validate_annotation_record(rec, valid_candidate_ids)
    assert any("non_intent_class must be null" in e for e in errors)


def test_secondary_intents_validation(sample_valid_annotation, valid_candidate_ids):
    """Verify secondary intents cannot duplicate primary intent or contain unapproved enums."""
    rec = copy.deepcopy(sample_valid_annotation)
    rec["primary_intent"] = "04_billing_payment"
    rec["secondary_intents"] = ["04_billing_payment"]  # Duplicating primary intent
    errors = validate_annotation_record(rec, valid_candidate_ids)
    assert any("secondary_intents contains primary_intent" in e for e in errors)

    rec["secondary_intents"] = ["invented_intent"]
    errors = validate_annotation_record(rec, valid_candidate_ids)
    assert any("Invalid secondary_intent" in e for e in errors)


def test_technical_malfunction_scope_conditionality(sample_valid_annotation, valid_candidate_ids):
    """Verify scope is mandatory when 07 is present and must be null otherwise."""
    rec = copy.deepcopy(sample_valid_annotation)
    rec["primary_intent"] = "07_technical_malfunction"
    rec["technical_malfunction_scope"] = None  # Missing mandatory scope
    errors = validate_annotation_record(rec, valid_candidate_ids)
    assert any("technical_malfunction_scope is mandatory when intent 07 is present" in e for e in errors)

    rec["technical_malfunction_scope"] = "individual"
    errors = validate_annotation_record(rec, valid_candidate_ids)
    assert not errors

    # Illegal scope when 07 is absent
    rec["primary_intent"] = "01_catalog_content_gap"
    rec["secondary_intents"] = []
    rec["technical_malfunction_scope"] = "individual"
    errors = validate_annotation_record(rec, valid_candidate_ids)
    assert any("technical_malfunction_scope must be null when intent 07 is absent" in e for e in errors)


def test_cross_cutting_flags_validation(sample_valid_annotation, valid_candidate_ids):
    """Verify only approved cross_cutting_flags are permitted."""
    rec = copy.deepcopy(sample_valid_annotation)
    rec["cross_cutting_flags"] = ["prior_interaction_dissatisfaction", "unapproved_flag"]
    errors = validate_annotation_record(rec, valid_candidate_ids)
    assert any("Invalid cross_cutting_flag" in e for e in errors)


def test_confidence_and_ambiguity_validation(sample_valid_annotation, valid_candidate_ids):
    """Verify confidence enums and ambiguity category constraints."""
    rec = copy.deepcopy(sample_valid_annotation)
    rec["confidence"] = "very_high"  # Invalid enum
    errors = validate_annotation_record(rec, valid_candidate_ids)
    assert any("Invalid confidence level" in e for e in errors)

    rec["confidence"] = "high"
    rec["is_ambiguous"] = False
    rec["ambiguity_category"] = "01_02"  # Must be null when is_ambiguous is False
    errors = validate_annotation_record(rec, valid_candidate_ids)
    assert any("ambiguity_category must be null when is_ambiguous is False" in e for e in errors)


def test_timestamp_iso8601_validation(sample_valid_annotation, valid_candidate_ids):
    """Verify timestamp must be valid ISO-8601 format."""
    rec = copy.deepcopy(sample_valid_annotation)
    rec["annotation_timestamp"] = "13/09/2026 12:00:00"
    errors = validate_annotation_record(rec, valid_candidate_ids)
    assert any("Invalid annotation_timestamp format" in e for e in errors)


def test_inter_annotator_agreement_computation():
    """Verify calculation of raw agreement and Cohen's Kappa on double-annotated pairs."""
    pair1 = (
        {"is_non_intent": False, "primary_intent": "01_catalog_content_gap", "secondary_intents": [], "technical_malfunction_scope": None, "cross_cutting_flags": []},
        {"is_non_intent": False, "primary_intent": "01_catalog_content_gap", "secondary_intents": [], "technical_malfunction_scope": None, "cross_cutting_flags": []},
    )
    pair2 = (
        {"is_non_intent": False, "primary_intent": "04_billing_payment", "secondary_intents": [], "technical_malfunction_scope": None, "cross_cutting_flags": []},
        {"is_non_intent": False, "primary_intent": "05_subscription_plan_management", "secondary_intents": [], "technical_malfunction_scope": None, "cross_cutting_flags": []},
    )

    metrics = compute_inter_annotator_agreement([pair1, pair2])
    assert metrics["total_double_annotated"] == 2
    assert metrics["primary_label_raw_agreement_pct"] == 50.0
    assert metrics["full_consensus_count"] == 1
    assert metrics["disagreement_count"] == 1


def test_adjudication_pipeline_flow(tmp_path, valid_candidate_ids):
    """Test full adjudication workflow including consensus promotion and adjudicator resolution."""
    cids = sorted(list(valid_candidate_ids))
    raw_path = tmp_path / "raw_annotations.jsonl"
    adj_out = tmp_path / "adjudications.jsonl"
    gold_out = tmp_path / "canonical_gold.jsonl"

    raw_records = []

    # 1. Double annotated item with consensus (cids[0])
    raw_records.append({
        "conversation_id": cids[0], "annotator_id": "annotator_1", "annotation_timestamp": "2026-09-13T12:00:00Z",
        "is_non_intent": False, "primary_intent": "01_catalog_content_gap", "secondary_intents": [],
        "non_intent_class": None, "technical_malfunction_scope": None, "cross_cutting_flags": [],
        "is_ambiguous": False, "ambiguity_category": None, "ambiguity_notes": None,
        "confidence": "high", "evidence_quote": "missing song", "schema_version": "1.0.0"
    })
    raw_records.append({
        "conversation_id": cids[0], "annotator_id": "annotator_2", "annotation_timestamp": "2026-09-13T12:05:00Z",
        "is_non_intent": False, "primary_intent": "01_catalog_content_gap", "secondary_intents": [],
        "non_intent_class": None, "technical_malfunction_scope": None, "cross_cutting_flags": [],
        "is_ambiguous": False, "ambiguity_category": None, "ambiguity_notes": None,
        "confidence": "high", "evidence_quote": "missing album", "schema_version": "1.0.0"
    })

    # 2. Double annotated item with discrepancy resolved by adjudicator (cids[1])
    raw_records.append({
        "conversation_id": cids[1], "annotator_id": "annotator_1", "annotation_timestamp": "2026-09-13T12:00:00Z",
        "is_non_intent": False, "primary_intent": "04_billing_payment", "secondary_intents": [],
        "non_intent_class": None, "technical_malfunction_scope": None, "cross_cutting_flags": [],
        "is_ambiguous": False, "ambiguity_category": None, "ambiguity_notes": None,
        "confidence": "medium", "evidence_quote": "charge issue", "schema_version": "1.0.0"
    })
    raw_records.append({
        "conversation_id": cids[1], "annotator_id": "annotator_2", "annotation_timestamp": "2026-09-13T12:05:00Z",
        "is_non_intent": False, "primary_intent": "05_subscription_plan_management", "secondary_intents": [],
        "non_intent_class": None, "technical_malfunction_scope": None, "cross_cutting_flags": [],
        "is_ambiguous": True, "ambiguity_category": "04_05", "ambiguity_notes": "family plan billing",
        "confidence": "medium", "evidence_quote": "family plan payment", "schema_version": "1.0.0"
    })
    raw_records.append({
        "conversation_id": cids[1], "annotator_id": "adjudicator", "annotation_timestamp": "2026-09-13T12:10:00Z",
        "is_non_intent": False, "primary_intent": "04_billing_payment", "secondary_intents": ["05_subscription_plan_management"],
        "non_intent_class": None, "technical_malfunction_scope": None, "cross_cutting_flags": [],
        "is_ambiguous": True, "ambiguity_category": "04_05", "ambiguity_notes": "Primary intent is monetary charge dispute.",
        "confidence": "high", "evidence_quote": "charged twice for family plan", "schema_version": "1.0.0"
    })

    # 3. Single annotated remaining items (cids[2:])
    for cid in cids[2:]:
        raw_records.append({
            "conversation_id": cid, "annotator_id": "annotator_1", "annotation_timestamp": "2026-09-13T12:00:00Z",
            "is_non_intent": False, "primary_intent": "06_login_authentication", "secondary_intents": [],
            "non_intent_class": None, "technical_malfunction_scope": None, "cross_cutting_flags": [],
            "is_ambiguous": False, "ambiguity_category": None, "ambiguity_notes": None,
            "confidence": "high", "evidence_quote": "cant login", "schema_version": "1.0.0"
        })

    with raw_path.open("w", encoding="utf-8") as f:
        for r in raw_records:
            f.write(json.dumps(r) + "\n")

    res = process_adjudications(
        raw_annotations_path=raw_path,
        candidates_path=CANDIDATES_PATH,
        output_adjudications_path=adj_out,
        output_consolidated_path=gold_out,
        min_double_annotation_count=1,
    )

    assert res["canonical_gold_records"] == 200
    assert res["double_annotated_count"] == 2
    assert adj_out.exists()
    assert gold_out.exists()

    # Validate the generated canonical gold annotations file
    val_res = validate_annotations_file(gold_out, candidates_path=CANDIDATES_PATH, mode="canonical")
    assert val_res["overall_passed"] is True


def test_prepare_annotation_workspace_flow(tmp_path):
    """Verify that annotation workspace preparation creates 200 Annotator 1 templates and exactly 50 double-annotation templates."""
    from scripts.prepare_annotation_workspace import prepare_annotation_workspace

    double_ids_file = tmp_path / "double_ids.txt"
    a1_file = tmp_path / "a1_workspace.jsonl"
    a2_file = tmp_path / "a2_workspace.jsonl"

    res = prepare_annotation_workspace(
        candidates_path=CANDIDATES_PATH,
        output_double_ids_path=double_ids_file,
        output_annotator_1_path=a1_file,
        output_annotator_2_path=a2_file,
    )

    assert res["total_candidates"] == 200
    assert res["annotator_1_templates"] == 200
    assert res["annotator_2_templates"] == 50
    assert len(res["double_annotation_cids"]) == 50
    assert len(set(res["double_annotation_cids"])) == 50

    # Ensure templates are blank / have no pre-assigned gold labels
    with a1_file.open("r", encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            assert rec["primary_intent"] is None
            assert rec["is_non_intent"] is None
            assert rec["annotator_id"] == "annotator_1"

    with a2_file.open("r", encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            assert rec["primary_intent"] is None
            assert rec["is_non_intent"] is None
            assert rec["annotator_id"] == "annotator_2"


def test_canonical_golden_set_annotations_artifact():
    """Verify that the generated canonical gold annotations artifact passes validation with zero errors."""
    gold_file = Path("data/processed/golden_set_annotations.jsonl")
    if gold_file.exists():
        res = validate_annotations_file(
            gold_file, candidates_path=CANDIDATES_PATH, mode="canonical"
        )
        assert res["overall_passed"] is True
        assert res["total_records"] == 200
        assert res["unique_conversation_ids"] == 200


def test_detect_field_differences():
    """Verify dynamic field-difference detection across all 4 dimensions."""
    from scripts.adjudicate_annotations import detect_field_differences

    base = {
        "is_non_intent": False,
        "primary_intent": "04_billing_payment",
        "secondary_intents": ["05_subscription_plan_management"],
        "non_intent_class": None,
        "technical_malfunction_scope": None,
        "cross_cutting_flags": ["alternate_channel_request"],
    }

    # Identical -> no diffs
    assert detect_field_differences(base, base) == {}

    # Primary diff
    diff_p = copy.deepcopy(base)
    diff_p["primary_intent"] = "05_subscription_plan_management"
    d = detect_field_differences(base, diff_p)
    assert "primary_label" in d

    # Secondary diff
    diff_s = copy.deepcopy(base)
    diff_s["secondary_intents"] = []
    d = detect_field_differences(base, diff_s)
    assert "secondary_intents" in d

    # Scope diff
    diff_scope_1 = copy.deepcopy(base)
    diff_scope_1["technical_malfunction_scope"] = "individual"
    diff_scope_2 = copy.deepcopy(base)
    diff_scope_2["technical_malfunction_scope"] = "unclear"
    d = detect_field_differences(diff_scope_1, diff_scope_2)
    assert "technical_malfunction_scope" in d

    # Flags diff
    diff_f = copy.deepcopy(base)
    diff_f["cross_cutting_flags"] = []
    d = detect_field_differences(base, diff_f)
    assert "cross_cutting_flags" in d


def test_adjudications_artifact_validation():
    """Verify independent validation of golden_set_adjudications.jsonl artifact."""
    from scripts.validate_gold_annotations import validate_adjudications_file

    adj_file = Path("data/processed/golden_set_adjudications.jsonl")
    if adj_file.exists():
        res = validate_adjudications_file(
            adjudications_path=adj_file,
            annotator_1_path=Path("data/processed/annotator_1_completed.jsonl"),
            annotator_2_path=Path("data/processed/annotator_2_completed.jsonl"),
            candidates_path=CANDIDATES_PATH,
        )
        assert res["overall_passed"] is True
        assert res["total_adjudications"] == 50
        assert res["consensus_count"] == 37
        assert res["adjudicated_count"] == 13


def test_adjudications_provenance_tamper_detection(tmp_path, valid_candidate_ids):
    """Verify that validator catches false consensus or misreported disagreement status."""
    from scripts.validate_gold_annotations import validate_adjudications_file

    cid = next(iter(valid_candidate_ids))
    a1_file = tmp_path / "a1.jsonl"
    a2_file = tmp_path / "a2.jsonl"
    adj_file = tmp_path / "adj.jsonl"
    double_ids = tmp_path / "double.txt"

    double_ids.write_text(f"{cid}\n", encoding="utf-8")

    rec1 = {
        "conversation_id": cid, "annotator_id": "annotator_1", "annotation_timestamp": "2026-09-13T12:00:00Z",
        "is_non_intent": False, "primary_intent": "04_billing_payment", "secondary_intents": [],
        "non_intent_class": None, "technical_malfunction_scope": None, "cross_cutting_flags": [],
        "is_ambiguous": False, "ambiguity_category": None, "ambiguity_notes": None,
        "confidence": "high", "evidence_quote": "charge", "schema_version": "1.0.0"
    }
    rec2 = copy.deepcopy(rec1)
    rec2["primary_intent"] = "05_subscription_plan_management"  # Disagreement!
    rec2["annotator_id"] = "annotator_2"

    a1_file.write_text(json.dumps(rec1) + "\n", encoding="utf-8")
    a2_file.write_text(json.dumps(rec2) + "\n", encoding="utf-8")

    # Tampered adjudication claiming consensus when there is a disagreement
    tampered_adj = {
        "conversation_id": cid,
        "annotator_a": "annotator_1",
        "annotator_b": "annotator_2",
        "has_disagreement": False,  # False claim!
        "resolved_by": "consensus",
        "resolved_gold_record": rec1,
        "adjudication_reasoning": "tampered",
    }
    adj_file.write_text(json.dumps(tampered_adj) + "\n", encoding="utf-8")

    res = validate_adjudications_file(
        adjudications_path=adj_file,
        annotator_1_path=a1_file,
        annotator_2_path=a2_file,
        candidates_path=CANDIDATES_PATH,
        double_ids_path=double_ids,
    )
    assert res["overall_passed"] is False
    assert any("Inconsistency: has_disagreement=False does not match actual difference" in e for e in res["validation_errors"])


def test_unresolved_disagreement_raises_error(tmp_path, valid_candidate_ids):
    """Verify that process_adjudications_from_annotators raises an error when a disagreement has no adjudicator resolution."""
    from scripts.adjudicate_annotations import process_adjudications_from_annotators

    cids = sorted(list(valid_candidate_ids))
    cid = cids[0]

    a1_file = tmp_path / "a1.jsonl"
    a2_file = tmp_path / "a2.jsonl"
    cands_file = tmp_path / "cands.jsonl"

    rec1 = {
        "conversation_id": cid, "annotator_id": "annotator_1", "annotation_timestamp": "2026-09-13T12:00:00Z",
        "is_non_intent": False, "primary_intent": "01_catalog_content_gap", "secondary_intents": [],
        "non_intent_class": None, "technical_malfunction_scope": None, "cross_cutting_flags": [],
        "is_ambiguous": False, "ambiguity_category": None, "ambiguity_notes": None,
        "confidence": "high", "evidence_quote": "missing", "schema_version": "1.0.0"
    }
    rec2 = copy.deepcopy(rec1)
    rec2["primary_intent"] = "02_catalog_metadata_error"
    rec2["annotator_id"] = "annotator_2"

    a1_file.write_text(json.dumps(rec1) + "\n", encoding="utf-8")
    a2_file.write_text(json.dumps(rec2) + "\n", encoding="utf-8")
    cands_file.write_text(json.dumps({"conversation_id": cid}) + "\n", encoding="utf-8")

    # Pass non-existent lead adjudications path so no resolution exists
    with pytest.raises(RuntimeError, match="disagreements lack lead adjudicator resolution"):
        process_adjudications_from_annotators(
            annotator_1_path=a1_file,
            annotator_2_path=a2_file,
            candidates_path=cands_file,
            output_adjudications_path=tmp_path / "adj.jsonl",
            output_consolidated_path=tmp_path / "gold.jsonl",
            lead_adjudications_path=None,
        )


def test_frozen_multi_intent_priority_order():
    """Verify frozen multi-intent priority order constant."""
    from scripts.adjudicate_annotations import MULTI_INTENT_PRIORITY

    billing_idx = MULTI_INTENT_PRIORITY.index("04_billing_payment")
    plan_idx = MULTI_INTENT_PRIORITY.index("05_subscription_plan_management")
    region_idx = MULTI_INTENT_PRIORITY.index("03_region_availability")

    # 04_billing_payment > 05_subscription_plan_management > 03_region_availability
    assert billing_idx < plan_idx < region_idx


def test_no_hardcoded_adjudication_map_in_engine():
    """Reject hard-coded conversation-ID resolution maps regardless of their name."""
    import scripts.adjudicate_annotations as adj_mod
    import scripts.build_canonical_gold_annotations as build_mod

    assert not hasattr(adj_mod, "LEAD_ADJUDICATOR_RESOLUTIONS"), "Hard-coded LEAD_ADJUDICATOR_RESOLUTIONS map must not exist in engine!"
    assert not hasattr(build_mod, "ADJUDICATED_RESOLUTIONS"), "Hard-coded ADJUDICATED_RESOLUTIONS map must not exist in builder!"

    for module in (adj_mod, build_mod):
        tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
        for dictionary in (node for node in ast.walk(tree) if isinstance(node, ast.Dict)):
            string_keys = [key.value for key in dictionary.keys if isinstance(key, ast.Constant) and isinstance(key.value, str)]
            assert not any(key.startswith("spotify_root_") for key in string_keys), (
                "Hard-coded conversation-ID resolution map must not exist, regardless of variable name"
            )


def test_canonical_double_annotated_equals_adjudication_resolved_gold():
    """Verify canonical double-annotated records equal corresponding adjudication resolved_gold_record."""
    adj_file = Path("data/processed/golden_set_adjudications.jsonl")
    gold_file = Path("data/processed/golden_set_annotations.jsonl")

    if not adj_file.exists() or not gold_file.exists():
        pytest.skip("Adjudications or gold set file not found.")

    adj_records = {json.loads(line)["conversation_id"]: json.loads(line) for line in adj_file.open(encoding="utf-8") if line.strip()}
    gold_records = {json.loads(line)["conversation_id"]: json.loads(line) for line in gold_file.open(encoding="utf-8") if line.strip()}

    for cid, adj in adj_records.items():
        assert cid in gold_records
        assert gold_records[cid] == adj["resolved_gold_record"]


def test_adjudications_snapshot_fidelity_and_difference_correspondence():
    """Verify that embedded annotator source snapshots and recorded differences correspond to actual sources."""
    adj_file = Path("data/processed/golden_set_adjudications.jsonl")
    a1_file = Path("data/processed/annotator_1_completed.jsonl")
    a2_file = Path("data/processed/annotator_2_completed.jsonl")

    if not adj_file.exists() or not a1_file.exists() or not a2_file.exists():
        pytest.skip("Annotation files not found.")

    a1_records = {json.loads(line)["conversation_id"]: json.loads(line) for line in a1_file.open(encoding="utf-8") if line.strip()}
    a2_records = {json.loads(line)["conversation_id"]: json.loads(line) for line in a2_file.open(encoding="utf-8") if line.strip()}

    from scripts.adjudicate_annotations import detect_field_differences

    with adj_file.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            r = json.loads(line)
            cid = r["conversation_id"]
            assert cid in a1_records and cid in a2_records

            # Snapshot fidelity
            assert r["annotator_a_record"] == a1_records[cid]
            assert r["annotator_b_record"] == a2_records[cid]

            # Differences correspondence
            actual_diffs = detect_field_differences(a1_records[cid], a2_records[cid])
            assert r["has_disagreement"] == bool(actual_diffs)
            assert set(r["disagreement_fields"]) == set(actual_diffs.keys())
            expected_field_differences = {
                field: {"annotator_1": values[0], "annotator_2": values[1]}
                for field, values in actual_diffs.items()
            }
            # JSON artifacts serialize tuple-valued primary labels as lists.
            expected_field_differences = json.loads(json.dumps(expected_field_differences))
            assert r["field_differences"] == expected_field_differences


def test_adjudications_field_differences_value_tamper_detection(tmp_path):
    """A changed difference value must fail even when its field name is unchanged."""
    from scripts.validate_gold_annotations import validate_adjudications_file

    source_adj = next(
        json.loads(line)
        for line in Path("data/processed/golden_set_adjudications.jsonl").open(encoding="utf-8")
        if line.strip() and json.loads(line)["field_differences"]
    )
    cid = source_adj["conversation_id"]
    tampered = copy.deepcopy(source_adj)
    field = next(iter(tampered["field_differences"]))
    tampered["field_differences"][field]["annotator_1"] = "tampered source value"

    adj_file = tmp_path / "adj.jsonl"
    a1_file = tmp_path / "a1.jsonl"
    a2_file = tmp_path / "a2.jsonl"
    double_ids = tmp_path / "double.txt"
    adj_file.write_text(json.dumps(tampered) + "\n", encoding="utf-8")
    a1_file.write_text(json.dumps(source_adj["annotator_a_record"]) + "\n", encoding="utf-8")
    a2_file.write_text(json.dumps(source_adj["annotator_b_record"]) + "\n", encoding="utf-8")
    double_ids.write_text(f"{cid}\n", encoding="utf-8")

    result = validate_adjudications_file(adj_file, a1_file, a2_file, CANDIDATES_PATH, double_ids)
    assert result["overall_passed"] is False
    assert any("field_differences does not exactly match" in error for error in result["validation_errors"])


def test_adjudications_source_snapshot_tamper_detection(tmp_path):
    """A changed embedded annotator source snapshot must fail validation."""
    from scripts.validate_gold_annotations import validate_adjudications_file

    source_adj = next(
        json.loads(line)
        for line in Path("data/processed/golden_set_adjudications.jsonl").open(encoding="utf-8")
        if line.strip()
    )
    cid = source_adj["conversation_id"]
    tampered = copy.deepcopy(source_adj)
    tampered["annotator_a_record"]["evidence_quote"] = "tampered source snapshot"

    adj_file = tmp_path / "adj.jsonl"
    a1_file = tmp_path / "a1.jsonl"
    a2_file = tmp_path / "a2.jsonl"
    double_ids = tmp_path / "double.txt"
    adj_file.write_text(json.dumps(tampered) + "\n", encoding="utf-8")
    a1_file.write_text(json.dumps(source_adj["annotator_a_record"]) + "\n", encoding="utf-8")
    a2_file.write_text(json.dumps(source_adj["annotator_b_record"]) + "\n", encoding="utf-8")
    double_ids.write_text(f"{cid}\n", encoding="utf-8")

    result = validate_adjudications_file(adj_file, a1_file, a2_file, CANDIDATES_PATH, double_ids)
    assert result["overall_passed"] is False
    assert any("annotator_a_record snapshot does not match" in error for error in result["validation_errors"])


def test_priority_cases_compliance():
    """Verify that the multi-intent priority cases are strictly compliant with 04_billing > 05_plan > 03_region."""
    gold_file = Path("data/processed/golden_set_annotations.jsonl")
    if not gold_file.exists():
        pytest.skip("Canonical gold annotations file not found.")

    gold_records = {json.loads(line)["conversation_id"]: json.loads(line) for line in gold_file.open(encoding="utf-8") if line.strip()}

    # Case 1: spotify_root_492446 (04_billing_payment > 05_subscription_plan_management)
    assert gold_records["spotify_root_492446"]["primary_intent"] == "04_billing_payment"
    assert "05_subscription_plan_management" in gold_records["spotify_root_492446"]["secondary_intents"]

    # Case 2: spotify_root_2158604 (04_billing_payment > 05_subscription_plan_management)
    assert gold_records["spotify_root_2158604"]["primary_intent"] == "04_billing_payment"
    assert "05_subscription_plan_management" in gold_records["spotify_root_2158604"]["secondary_intents"]

    # Case 3: spotify_root_2175388 (04_billing_payment > 05_subscription_plan_management > 03_region_availability)
    assert gold_records["spotify_root_2175388"]["primary_intent"] == "04_billing_payment"
    assert "05_subscription_plan_management" in gold_records["spotify_root_2175388"]["secondary_intents"]
    assert "03_region_availability" in gold_records["spotify_root_2175388"]["secondary_intents"]


def test_immutable_input_files_checksums():
    """Verify SHA-256 checksums of immutable input files."""
    from scripts.validate_gold_annotations import (
        verify_candidates_immutability,
        verify_input_file_immutability,
        EXPECTED_CANDIDATES_SHA256,
        EXPECTED_ANNOTATOR_1_SHA256,
        EXPECTED_ANNOTATOR_2_SHA256,
    )

    ok, msg, cids = verify_candidates_immutability(CANDIDATES_PATH, EXPECTED_CANDIDATES_SHA256)
    assert ok, msg
    assert len(cids) == 200

    ok1, msg1 = verify_input_file_immutability(Path("data/processed/annotator_1_completed.jsonl"), EXPECTED_ANNOTATOR_1_SHA256)
    assert ok1, msg1

    ok2, msg2 = verify_input_file_immutability(Path("data/processed/annotator_2_completed.jsonl"), EXPECTED_ANNOTATOR_2_SHA256)
    assert ok2, msg2
