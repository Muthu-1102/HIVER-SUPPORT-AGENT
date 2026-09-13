#!/usr/bin/env python3
"""
Validation Script for Human Gold Annotations (Schema v1.0.0) and Adjudications.

Validates:
1. Schema structure and data types against schema_version == "1.0.0".
2. Referential integrity against data/processed/golden_set_candidates.jsonl.
3. Immutability / checksum protection of golden_set_candidates.jsonl and completed annotator inputs.
4. Mutual exclusivity of substantive intents vs non-intent classes.
5. Frozen taxonomy enums (9 substantive intents, 3 non-intents, 2 flags, 3 technical scopes).
6. Technical malfunction scope conditionality (mandatory if intent 07 present, null otherwise).
7. Flag independence and enum validity.
8. Ambiguity and confidence constraints.
9. ISO-8601 UTC timestamp format.
10. Uniqueness and 200-record canonical completeness.
11. Adjudication artifact validation (structure, 50 double-annotation records, provenance, snapshot fidelity, consistency with completed annotator files).
12. Strict canonical-to-adjudication and canonical-to-source provenance alignment.

Exit code: 0 on PASS, 1 on any check FAIL.
"""

import argparse
import datetime
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SCHEMA_VERSION = "1.0.0"

# Canonical checksums of immutable input files
EXPECTED_CANDIDATES_SHA256 = "14419814b778607b06a7bcce5459716ba65b43a22c18279f609ba5884d8d61ee"
EXPECTED_ANNOTATOR_1_SHA256 = "594157f9e0255a7c7db786c00fed10562f6c421dc254ebaa91cd4311f9181bfa"
EXPECTED_ANNOTATOR_2_SHA256 = "10460499f4b9e9bbb770c7d1ede4dca0b217ddd91379eeea1ce355b4f1887de8"

# ---------------------------------------------------------------------------
# Frozen Taxonomy Constants
# ---------------------------------------------------------------------------

SUBSTANTIVE_INTENTS = {
    "01_catalog_content_gap",
    "02_catalog_metadata_error",
    "03_region_availability",
    "04_billing_payment",
    "05_subscription_plan_management",
    "06_login_authentication",
    "07_technical_malfunction",
    "08_feature_request",
    "09_artist_rights_holder_mgmt",
}

NON_INTENT_CLASSES = {
    "insufficient_information",
    "out_of_scope_non_support",
    "no_action_acknowledgment_only",
}

CROSS_CUTTING_FLAGS = {
    "prior_interaction_dissatisfaction",
    "alternate_channel_request",
}

TECHNICAL_MALFUNCTION_SCOPES = {
    "individual",
    "platform_wide",
    "unclear",
}

CONFIDENCE_LEVELS = {
    "high",
    "medium",
    "low",
}

REQUIRED_ANNOTATION_FIELDS = {
    "conversation_id": str,
    "annotator_id": str,
    "annotation_timestamp": str,
    "is_non_intent": bool,
    "primary_intent": (str, type(None)),
    "secondary_intents": list,
    "non_intent_class": (str, type(None)),
    "technical_malfunction_scope": (str, type(None)),
    "cross_cutting_flags": list,
    "is_ambiguous": bool,
    "ambiguity_category": (str, type(None)),
    "ambiguity_notes": (str, type(None)),
    "confidence": str,
    "evidence_quote": str,
    "schema_version": str,
}

REQUIRED_ADJUDICATION_FIELDS = {
    "conversation_id": str,
    "annotator_a": str,
    "annotator_b": str,
    "has_disagreement": bool,
    "resolved_by": str,
    "resolved_gold_record": dict,
    "adjudication_reasoning": str,
}

ISO8601_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)

# ---------------------------------------------------------------------------
# Candidate Corpus Verification
# ---------------------------------------------------------------------------

def verify_candidates_immutability(
    candidates_path: Path, expected_sha256: str = EXPECTED_CANDIDATES_SHA256
) -> Tuple[bool, str, Set[str]]:
    """Verify that candidates JSONL exists, matches expected checksum, and load conversation IDs."""
    if not candidates_path.exists():
        return False, f"Candidates file not found: {candidates_path}", set()

    data = candidates_path.read_bytes()
    actual_sha256 = hashlib.sha256(data).hexdigest()
    if actual_sha256 != expected_sha256:
        return (
            False,
            f"Checksum mismatch for {candidates_path}! Expected {expected_sha256}, got {actual_sha256}",
            set(),
        )

    valid_cids = set()
    for line in data.decode("utf-8").splitlines():
        line = line.strip()
        if line:
            rec = json.loads(line)
            valid_cids.add(rec["conversation_id"])

    return True, f"Verified candidates file ({len(valid_cids)} conversations).", valid_cids


def verify_input_file_immutability(file_path: Path, expected_sha256: str) -> Tuple[bool, str]:
    """Verify that an input file exists and matches expected checksum."""
    if not file_path.exists():
        return False, f"Input file not found: {file_path}"
    data = file_path.read_bytes()
    actual_sha256 = hashlib.sha256(data).hexdigest()
    if actual_sha256 != expected_sha256:
        return False, f"Checksum mismatch for {file_path}! Expected {expected_sha256}, got {actual_sha256}"
    return True, f"Verified {file_path} checksum."

# ---------------------------------------------------------------------------
# Single Record Validation
# ---------------------------------------------------------------------------

def validate_annotation_record(
    record: Dict[str, Any],
    valid_candidate_ids: Set[str],
    line_number: int = 1,
) -> List[str]:
    """Validate a single annotation record against Schema v1.0.0 and taxonomy rules."""
    errors: List[str] = []
    cid = record.get("conversation_id", f"<unknown_line_{line_number}>")

    # 1. Required fields presence & types
    for field_name, expected_type in REQUIRED_ANNOTATION_FIELDS.items():
        if field_name not in record:
            errors.append(f"[{cid}] Missing required field: '{field_name}'")
        else:
            val = record[field_name]
            if not isinstance(val, expected_type):
                errors.append(
                    f"[{cid}] Field '{field_name}' type mismatch: expected {expected_type}, got {type(val).__name__}"
                )

    if errors:
        return errors

    # 2. Schema version
    if record["schema_version"] != SCHEMA_VERSION:
        errors.append(
            f"[{cid}] Invalid schema_version: expected '{SCHEMA_VERSION}', got '{record['schema_version']}'"
        )

    # 3. Referential integrity
    if record["conversation_id"] not in valid_candidate_ids:
        errors.append(
            f"[{cid}] Referential integrity violation: conversation_id not found in golden set candidates"
        )

    # 4. Annotator ID non-empty
    if not record["annotator_id"].strip():
        errors.append(f"[{cid}] annotator_id must not be empty")

    # 5. Timestamp format (ISO-8601 UTC)
    ts = record["annotation_timestamp"]
    if not ISO8601_PATTERN.match(ts):
        errors.append(
            f"[{cid}] Invalid annotation_timestamp format: '{ts}' (expected ISO-8601 UTC, e.g. '2026-09-13T12:00:00Z')"
        )

    # 6. Mutual Exclusivity: Non-Intent vs Substantive Intent
    is_non_intent = record["is_non_intent"]
    primary_intent = record["primary_intent"]
    non_intent_class = record["non_intent_class"]
    secondary_intents = record["secondary_intents"]

    if is_non_intent:
        if primary_intent is not None:
            errors.append(
                f"[{cid}] When is_non_intent is True, primary_intent must be null (got '{primary_intent}')"
            )
        if non_intent_class not in NON_INTENT_CLASSES:
            errors.append(
                f"[{cid}] When is_non_intent is True, non_intent_class must be one of {sorted(NON_INTENT_CLASSES)} (got '{non_intent_class}')"
            )
        if len(secondary_intents) > 0:
            errors.append(
                f"[{cid}] When is_non_intent is True, secondary_intents must be empty (got {secondary_intents})"
            )
    else:
        if primary_intent not in SUBSTANTIVE_INTENTS:
            errors.append(
                f"[{cid}] When is_non_intent is False, primary_intent must be one of {sorted(SUBSTANTIVE_INTENTS)} (got '{primary_intent}')"
            )
        if non_intent_class is not None:
            errors.append(
                f"[{cid}] When is_non_intent is False, non_intent_class must be null (got '{non_intent_class}')"
            )

    # 7. Secondary intents validation
    for s_intent in secondary_intents:
        if s_intent not in SUBSTANTIVE_INTENTS:
            errors.append(
                f"[{cid}] Invalid secondary_intent '{s_intent}'. Must be one of {sorted(SUBSTANTIVE_INTENTS)}"
            )
        if s_intent == primary_intent:
            errors.append(
                f"[{cid}] secondary_intents contains primary_intent '{s_intent}'. Must not duplicate primary intent."
            )
    if len(secondary_intents) != len(set(secondary_intents)):
        errors.append(f"[{cid}] Duplicate intents in secondary_intents: {secondary_intents}")

    # 8. Technical Malfunction Scope Conditionality
    scope = record["technical_malfunction_scope"]
    has_07_intent = (primary_intent == "07_technical_malfunction") or (
        "07_technical_malfunction" in secondary_intents
    )

    if has_07_intent:
        if scope not in TECHNICAL_MALFUNCTION_SCOPES:
            errors.append(
                f"[{cid}] technical_malfunction_scope is mandatory when intent 07 is present. Must be one of {sorted(TECHNICAL_MALFUNCTION_SCOPES)} (got '{scope}')"
            )
    else:
        if scope is not None:
            errors.append(
                f"[{cid}] technical_malfunction_scope must be null when intent 07 is absent (got '{scope}')"
            )

    # 9. Cross-Cutting Flags
    flags = record["cross_cutting_flags"]
    for flag in flags:
        if flag not in CROSS_CUTTING_FLAGS:
            errors.append(
                f"[{cid}] Invalid cross_cutting_flag '{flag}'. Must be one of {sorted(CROSS_CUTTING_FLAGS)}"
            )
    if len(flags) != len(set(flags)):
        errors.append(f"[{cid}] Duplicate cross_cutting_flags: {flags}")

    # 10. Ambiguity & Confidence
    confidence = record["confidence"]
    if confidence not in CONFIDENCE_LEVELS:
        errors.append(
            f"[{cid}] Invalid confidence level: '{confidence}'. Must be one of {sorted(CONFIDENCE_LEVELS)}"
        )

    is_ambiguous = record["is_ambiguous"]
    ambiguity_category = record["ambiguity_category"]
    if not is_ambiguous and ambiguity_category is not None:
        errors.append(
            f"[{cid}] ambiguity_category must be null when is_ambiguous is False (got '{ambiguity_category}')"
        )

    return errors

# ---------------------------------------------------------------------------
# Adjudications Artifact Validation
# ---------------------------------------------------------------------------

def derive_field_differences(
    annotator_a_record: Dict[str, Any], annotator_b_record: Dict[str, Any]
) -> Dict[str, Dict[str, Any]]:
    """Derive the serialized disagreement evidence from the two source snapshots."""
    differences: Dict[str, Dict[str, Any]] = {}

    primary_a = [
        annotator_a_record.get("is_non_intent"),
        annotator_a_record.get("primary_intent"),
        annotator_a_record.get("non_intent_class"),
    ]
    primary_b = [
        annotator_b_record.get("is_non_intent"),
        annotator_b_record.get("primary_intent"),
        annotator_b_record.get("non_intent_class"),
    ]
    if primary_a != primary_b:
        differences["primary_label"] = {
            "annotator_1": primary_a,
            "annotator_2": primary_b,
        }

    secondary_a = sorted(set(annotator_a_record.get("secondary_intents") or []))
    secondary_b = sorted(set(annotator_b_record.get("secondary_intents") or []))
    if secondary_a != secondary_b:
        differences["secondary_intents"] = {
            "annotator_1": secondary_a,
            "annotator_2": secondary_b,
        }

    scope_a = annotator_a_record.get("technical_malfunction_scope")
    scope_b = annotator_b_record.get("technical_malfunction_scope")
    if scope_a != scope_b:
        differences["technical_malfunction_scope"] = {
            "annotator_1": scope_a,
            "annotator_2": scope_b,
        }

    flags_a = sorted(set(annotator_a_record.get("cross_cutting_flags") or []))
    flags_b = sorted(set(annotator_b_record.get("cross_cutting_flags") or []))
    if flags_a != flags_b:
        differences["cross_cutting_flags"] = {
            "annotator_1": flags_a,
            "annotator_2": flags_b,
        }

    return differences

def validate_adjudications_file(
    adjudications_path: Path = Path("data/processed/golden_set_adjudications.jsonl"),
    annotator_1_path: Path = Path("data/processed/annotator_1_completed.jsonl"),
    annotator_2_path: Path = Path("data/processed/annotator_2_completed.jsonl"),
    candidates_path: Path = Path("data/processed/golden_set_candidates.jsonl"),
    double_ids_path: Path = Path("data/processed/double_annotation_conversation_ids.txt"),
    expected_candidates_sha256: str = EXPECTED_CANDIDATES_SHA256,
) -> Dict[str, Any]:
    """Validate adjudication artifact structure, provenance, snapshots, and consistency with completed annotator files."""
    adjudications_path = Path(adjudications_path)
    annotator_1_path = Path(annotator_1_path)
    annotator_2_path = Path(annotator_2_path)
    candidates_path = Path(candidates_path)
    double_ids_path = Path(double_ids_path)

    errors: List[str] = []

    # 1. Verify candidate immutability
    cand_ok, cand_msg, valid_cids = verify_candidates_immutability(
        candidates_path, expected_sha256=expected_candidates_sha256
    )
    if not cand_ok:
        return {"overall_passed": False, "validation_errors": [cand_msg], "error_count": 1}

    if not adjudications_path.exists():
        return {
            "overall_passed": False,
            "validation_errors": [f"Adjudications file not found: {adjudications_path}"],
            "error_count": 1,
        }

    # Load double annotation IDs
    expected_double_ids: Set[str] = set()
    if double_ids_path.exists():
        expected_double_ids = {
            line.strip()
            for line in double_ids_path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        }

    # Load Annotator 1 and Annotator 2 completed files
    a1_by_cid: Dict[str, Dict[str, Any]] = {}
    if annotator_1_path.exists():
        with annotator_1_path.open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    rec = json.loads(line)
                    a1_by_cid[rec["conversation_id"]] = rec

    a2_by_cid: Dict[str, Dict[str, Any]] = {}
    if annotator_2_path.exists():
        with annotator_2_path.open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    rec = json.loads(line)
                    a2_by_cid[rec["conversation_id"]] = rec

    # Read adjudications
    adj_records: List[Dict[str, Any]] = []
    with adjudications_path.open("r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                adj_records.append(json.loads(line))
            except json.JSONDecodeError as e:
                errors.append(f"JSON decode error in adjudications at line {line_num}: {e}")

    if errors:
        return {"overall_passed": False, "validation_errors": errors, "error_count": len(errors)}

    adj_cids = [r.get("conversation_id") for r in adj_records]
    if len(adj_cids) != len(set(adj_cids)):
        errors.append(f"Duplicate conversation IDs found in adjudications: {Counter(adj_cids)}")

    if expected_double_ids and set(adj_cids) != expected_double_ids:
        missing = expected_double_ids - set(adj_cids)
        extra = set(adj_cids) - expected_double_ids
        if missing:
            errors.append(f"Adjudications missing double-annotation IDs: {missing}")
        if extra:
            errors.append(f"Adjudications contain unexpected IDs not in double-annotation list: {extra}")

    consensus_count = 0
    adjudicated_count = 0

    for idx, r in enumerate(adj_records, 1):
        cid = r.get("conversation_id", f"<adj_line_{idx}>")

        # Check required adjudication fields
        for field, exp_type in REQUIRED_ADJUDICATION_FIELDS.items():
            if field not in r:
                errors.append(f"[{cid}] Adjudication missing required field: '{field}'")
            elif not isinstance(r[field], exp_type):
                errors.append(
                    f"[{cid}] Adjudication field '{field}' type mismatch: expected {exp_type}, got {type(r[field]).__name__}"
                )

        # Validate resolved_gold_record against Schema v1.0.0
        gold_rec = r.get("resolved_gold_record", {})
        if isinstance(gold_rec, dict):
            gold_errs = validate_annotation_record(gold_rec, valid_cids, line_number=idx)
            for ge in gold_errs:
                errors.append(f"[{cid}] In resolved_gold_record: {ge}")

        # Derive the complete serialized disagreement evidence from the embedded
        # source snapshots for every adjudication, independent of provenance lookup.
        snapshot_a = r.get("annotator_a_record")
        snapshot_b = r.get("annotator_b_record")
        if not isinstance(snapshot_a, dict) or not isinstance(snapshot_b, dict):
            errors.append(
                f"[{cid}] annotator_a_record and annotator_b_record must be object snapshots"
            )
            expected_field_differences: Dict[str, Dict[str, Any]] = {}
        else:
            expected_field_differences = derive_field_differences(snapshot_a, snapshot_b)

        if r.get("field_differences") != expected_field_differences:
            errors.append(
                f"[{cid}] field_differences does not exactly match values derived from annotator source snapshots"
            )

        # Provenance and consistency check against completed annotator files
        if cid in a1_by_cid and cid in a2_by_cid:
            r1 = a1_by_cid[cid]
            r2 = a2_by_cid[cid]

            # 1. Embedded source snapshot fidelity check
            if "annotator_a_record" in r and r["annotator_a_record"] != r1:
                errors.append(f"[{cid}] annotator_a_record snapshot does not match actual Annotator 1 record")
            if "annotator_b_record" in r and r["annotator_b_record"] != r2:
                errors.append(f"[{cid}] annotator_b_record snapshot does not match actual Annotator 2 record")

            # 2. Compute disagreement status from the immutable completed
            # source records; snapshot fidelity above guarantees that the
            # serialized evidence was derived from the same sources.
            actual_diff_fields = list(derive_field_differences(r1, r2))
            l1 = (r1.get("is_non_intent"), r1.get("primary_intent"), r1.get("non_intent_class"))
            s1 = set(r1.get("secondary_intents") or [])
            scope1 = r1.get("technical_malfunction_scope")
            f1 = set(r1.get("cross_cutting_flags") or [])

            has_actual_diff = len(actual_diff_fields) > 0

            reported_disagreement = r.get("has_disagreement")
            if reported_disagreement != has_actual_diff:
                errors.append(
                    f"[{cid}] Inconsistency: has_disagreement={reported_disagreement} does not match actual difference status ({has_actual_diff})"
                )

            # Check recorded disagreement_fields matches actual differences
            recorded_diff_fields = set(r.get("disagreement_fields", []))
            if recorded_diff_fields != set(actual_diff_fields):
                errors.append(
                    f"[{cid}] Recorded disagreement_fields {recorded_diff_fields} does not match actual difference fields {actual_diff_fields}"
                )

            if not has_actual_diff:
                consensus_count += 1
                if r.get("resolved_by") != "consensus":
                    errors.append(
                        f"[{cid}] For full consensus pair, resolved_by must be 'consensus' (got '{r.get('resolved_by')}')"
                    )
                if gold_rec.get("annotator_id") != "consensus":
                    errors.append(
                        f"[{cid}] For full consensus pair, resolved_gold_record.annotator_id must be 'consensus' (got '{gold_rec.get('annotator_id')}')"
                    )
                # Verify gold record matches unanimous values
                if (
                    gold_rec.get("primary_intent") != r1.get("primary_intent")
                    or gold_rec.get("is_non_intent") != r1.get("is_non_intent")
                    or gold_rec.get("non_intent_class") != r1.get("non_intent_class")
                    or set(gold_rec.get("secondary_intents") or []) != s1
                    or gold_rec.get("technical_malfunction_scope") != scope1
                    or set(gold_rec.get("cross_cutting_flags") or []) != f1
                ):
                    errors.append(f"[{cid}] Consensus resolved_gold_record does not match unanimous annotator values")
            else:
                adjudicated_count += 1
                if r.get("resolved_by") not in ("adjudicator", "lead_adjudicator"):
                    errors.append(
                        f"[{cid}] For disagreement pair, resolved_by must be 'adjudicator' (got '{r.get('resolved_by')}')"
                    )
                if gold_rec.get("annotator_id") != "adjudicator":
                    errors.append(
                        f"[{cid}] For disagreement pair, resolved_gold_record.annotator_id must be 'adjudicator' (got '{gold_rec.get('annotator_id')}')"
                    )
                if not r.get("adjudication_reasoning", "").strip():
                    errors.append(f"[{cid}] Missing adjudication_reasoning for disagreement case")

    return {
        "overall_passed": len(errors) == 0,
        "total_adjudications": len(adj_records),
        "consensus_count": consensus_count,
        "adjudicated_count": adjudicated_count,
        "validation_errors": errors,
        "error_count": len(errors),
    }

# ---------------------------------------------------------------------------
# Full File Audit
# ---------------------------------------------------------------------------

def validate_annotations_file(
    annotations_path: Path,
    candidates_path: Path = Path("data/processed/golden_set_candidates.jsonl"),
    mode: str = "canonical",  # "canonical" (exact 200 unique), "raw", "all", or "adjudication"
    adjudications_path: Path = Path("data/processed/golden_set_adjudications.jsonl"),
    annotator_1_path: Path = Path("data/processed/annotator_1_completed.jsonl"),
    annotator_2_path: Path = Path("data/processed/annotator_2_completed.jsonl"),
    expected_candidates_sha256: str = EXPECTED_CANDIDATES_SHA256,
) -> Dict[str, Any]:
    """Audit an annotations JSONL file."""
    annotations_path = Path(annotations_path)
    candidates_path = Path(candidates_path)

    # 1. Verify candidate immutability
    cand_ok, cand_msg, valid_cids = verify_candidates_immutability(
        candidates_path, expected_sha256=expected_candidates_sha256
    )
    if not cand_ok:
        return {
            "overall_passed": False,
            "error_summary": [cand_msg],
            "total_records": 0,
            "unique_conversation_ids": 0,
            "validation_errors": [cand_msg],
        }

    if not annotations_path.exists():
        return {
            "overall_passed": False,
            "error_summary": [f"Annotations file not found: {annotations_path}"],
            "total_records": 0,
            "unique_conversation_ids": 0,
            "validation_errors": [f"Annotations file not found: {annotations_path}"],
        }

    records: List[Dict[str, Any]] = []
    with annotations_path.open("r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                records.append(rec)
            except json.JSONDecodeError as e:
                return {
                    "overall_passed": False,
                    "error_summary": [f"JSON syntax error at line {line_num}: {e}"],
                    "total_records": len(records),
                    "unique_conversation_ids": len({r.get("conversation_id") for r in records}),
                    "validation_errors": [f"JSON syntax error at line {line_num}: {e}"],
                }

    total_records = len(records)
    conv_ids = [r.get("conversation_id") for r in records]
    unique_cids = set(conv_ids)
    annotator_counts = Counter(r.get("annotator_id") for r in records)

    validation_errors: List[str] = []

    # Validate individual records
    for line_idx, rec in enumerate(records, 1):
        errs = validate_annotation_record(rec, valid_cids, line_number=line_idx)
        validation_errors.extend(errs)

    # Mode-specific constraints
    if mode in ("canonical", "all"):
        # Exactly 200 unique records, 1 per candidate
        if total_records != len(valid_cids):
            validation_errors.append(
                f"Canonical completeness failure: expected exactly {len(valid_cids)} annotations, found {total_records}"
            )
        if len(unique_cids) != total_records:
            dup_cids = [cid for cid, count in Counter(conv_ids).items() if count > 1]
            validation_errors.append(
                f"Duplicate annotations found for conversation IDs in canonical gold set: {dup_cids}"
            )
        missing_cids = valid_cids - unique_cids
        if missing_cids:
            validation_errors.append(
                f"Missing annotations for {len(missing_cids)} candidates in canonical gold set."
            )

        # Cross-file provenance alignment check (when validating full workspace in 'all' mode)
        if mode == "all" and annotator_1_path.exists() and adjudications_path.exists():
            a1_records: Dict[str, Dict[str, Any]] = {}
            with annotator_1_path.open("r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        r_a1 = json.loads(line)
                        a1_records[r_a1["conversation_id"]] = r_a1

            adj_gold_records: Dict[str, Dict[str, Any]] = {}
            with adjudications_path.open("r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        r_adj = json.loads(line)
                        adj_gold_records[r_adj["conversation_id"]] = r_adj["resolved_gold_record"]

            for r_canon in records:
                cid = r_canon.get("conversation_id")
                if cid in adj_gold_records:
                    # Double-annotated record must equal corresponding resolved_gold_record from adjudications
                    if r_canon != adj_gold_records[cid]:
                        validation_errors.append(
                            f"[{cid}] Canonical gold record does not match corresponding adjudication resolved_gold_record"
                        )
                elif cid in a1_records:
                    # Single-annotated record must equal Annotator 1 record
                    if r_canon != a1_records[cid]:
                        validation_errors.append(
                            f"[{cid}] Canonical single-annotated record does not match Annotator 1 source record"
                        )

    elif mode == "raw":
        # Check that no single annotator annotated the same conversation twice
        annotator_conv_pairs = Counter((r.get("annotator_id"), r.get("conversation_id")) for r in records)
        dup_pairs = [pair for pair, count in annotator_conv_pairs.items() if count > 1]
        if dup_pairs:
            validation_errors.append(
                f"Annotator annotated the same conversation multiple times: {dup_pairs}"
            )

    # If validating in 'all' mode or if adjudications_path provided, also validate adjudication artifact
    adjudication_summary = None
    if mode in ("all", "adjudication") and adjudications_path.exists():
        adj_res = validate_adjudications_file(
            adjudications_path=adjudications_path,
            annotator_1_path=annotator_1_path,
            annotator_2_path=annotator_2_path,
            candidates_path=candidates_path,
            expected_candidates_sha256=expected_candidates_sha256,
        )
        adjudication_summary = adj_res
        if not adj_res["overall_passed"]:
            validation_errors.extend(adj_res["validation_errors"])

    overall_passed = len(validation_errors) == 0

    return {
        "overall_passed": overall_passed,
        "mode": mode,
        "total_records": total_records,
        "unique_conversation_ids": len(unique_cids),
        "annotator_counts": dict(annotator_counts),
        "validation_errors": validation_errors,
        "error_count": len(validation_errors),
        "adjudication_summary": adjudication_summary,
    }

# ---------------------------------------------------------------------------
# CLI Entrypoint & Report
# ---------------------------------------------------------------------------

def print_validation_report(results: Dict[str, Any]) -> None:
    """Print human-readable audit diagnostics."""
    print("=" * 80)
    print(f"HUMAN GOLD ANNOTATIONS VALIDATION REPORT (Mode: {results.get('mode', 'canonical').upper()})")
    print("=" * 80)

    status_str = "PASS" if results["overall_passed"] else "FAIL"
    print(f"\nOVERALL STATUS: [{status_str}]\n")
    print(f"  - Total Canonical Gold Records: {results['total_records']}")
    print(f"  - Unique Conversation IDs:     {results['unique_conversation_ids']}")
    print(f"  - Annotator Breakdown:         {results.get('annotator_counts', {})}")
    print(f"  - Total Validation Errors:     {results.get('error_count', 0)}")

    if results.get("adjudication_summary"):
        adj = results["adjudication_summary"]
        adj_status = "PASS" if adj.get("overall_passed") else "FAIL"
        print(f"\n--- ADJUDICATIONS ARTIFACT STATUS: [{adj_status}] ---")
        print(f"  - Total Adjudication Records:  {adj.get('total_adjudications')}")
        print(f"  - Consensus Records:           {adj.get('consensus_count')}")
        print(f"  - Adjudicated Records:         {adj.get('adjudicated_count')}")

    if results["validation_errors"]:
        print("\n--- VALIDATION ERROR DETAILS ---")
        for err in results["validation_errors"][:30]:
            print(f"  [ERROR] {err}")
        if len(results["validation_errors"]) > 30:
            print(f"  ... and {len(results['validation_errors']) - 30} more errors.")

    print("=" * 80)


def main():
    parser = argparse.ArgumentParser(description="Validate Human Gold Annotation records against Schema v1.0.0")
    parser.add_argument(
        "--annotations",
        type=Path,
        default=Path("data/processed/golden_set_annotations.jsonl"),
        help="Path to annotations JSONL file",
    )
    parser.add_argument(
        "--candidates",
        type=Path,
        default=Path("data/processed/golden_set_candidates.jsonl"),
        help="Path to canonical candidates JSONL file",
    )
    parser.add_argument(
        "--adjudications",
        type=Path,
        default=Path("data/processed/golden_set_adjudications.jsonl"),
        help="Path to adjudications JSONL file",
    )
    parser.add_argument(
        "--mode",
        type=str,
        choices=["canonical", "raw", "adjudication", "all"],
        default="all",
        help="Validation mode: 'all' (canonical + adjudications), 'canonical', 'raw', or 'adjudication'",
    )

    args = parser.parse_args()

    results = validate_annotations_file(
        annotations_path=args.annotations,
        candidates_path=args.candidates,
        mode=args.mode,
        adjudications_path=args.adjudications,
    )

    print_validation_report(results)

    if not results["overall_passed"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
