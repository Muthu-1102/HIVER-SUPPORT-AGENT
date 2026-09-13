#!/usr/bin/env python3
"""
Independent Audit Script for Golden Evaluation Set Candidates.

Performs forensic validation against data/processed/golden_set_candidates.jsonl:
- Record count and unique conversation IDs
- Exclusion list compliance
- Substantive intent, non-intent, flag, boundary, escalation, compound, and structural quotas
- Multi-turn conversation floor (>= 70)
- Technical malfunction scope representation (individual, platform_wide, unclear)
- Schema and required metadata fields
- Tweet ID uniqueness within threads
- SHA-256 hash validity and fixed-salt verification

Exit code: 0 on PASS, 1 on any check FAIL.
"""

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

FIXED_SALT = "hiver-golden-set-v1"
HEX_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")

REQUIRED_SCHEMA_FIELDS = [
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
]

QUOTA_SPECIFICATIONS = [
    # Substantive Intent Baselines (108)
    ("intent_baseline_01_catalog_content_gap", 14, "01 Catalog Content Gap"),
    ("intent_baseline_02_catalog_metadata_error", 8, "02 Catalog Metadata Error"),
    ("intent_baseline_03_region_availability", 10, "03 Region Availability"),
    ("intent_baseline_04_billing_payment", 16, "04 Billing & Payment"),
    ("intent_baseline_05_subscription_plan_management", 12, "05 Subscription Plan Mgmt"),
    ("intent_baseline_06_login_authentication", 12, "06 Login & Authentication"),
    ("intent_baseline_07_technical_malfunction_individual", 7, "07 Technical Malfunction (Individual)"),
    ("intent_baseline_07_technical_malfunction_platform_wide", 5, "07 Technical Malfunction (Platform-wide)"),
    ("intent_baseline_07_technical_malfunction_unclear", 4, "07 Technical Malfunction (Unclear Scope)"),
    ("intent_baseline_08_feature_request", 12, "08 Feature Request"),
    ("intent_baseline_09_artist_rights_holder_mgmt", 8, "09 Artist & Rights Holder Mgmt"),
    # Non-Intent Classes (24)
    ("non_intent_insufficient_information", 8, "Non-Intent: Insufficient Information"),
    ("non_intent_out_of_scope_non_support", 8, "Non-Intent: Out of Scope"),
    ("non_intent_no_action_acknowledgment_only", 8, "Non-Intent: No Action / Acknowledgment Only"),
    # Cross-Cutting Flags (12)
    ("flag_prior_interaction_dissatisfaction", 6, "Flag: Prior Interaction Dissatisfaction"),
    ("flag_alternate_channel_request", 6, "Flag: Alternate Channel Request"),
    # Boundary Pairs (16)
    ("boundary_pair_01_02", 3, "Boundary Pair: 01 <-> 02"),
    ("boundary_pair_01_07", 4, "Boundary Pair: 01 <-> 07"),
    ("boundary_pair_06_07", 3, "Boundary Pair: 06 <-> 07"),
    ("boundary_pair_07_08", 3, "Boundary Pair: 07 <-> 08"),
    ("boundary_pair_01_08", 3, "Boundary Pair: 01 <-> 08"),
    # Special Categories
    ("escalation_sensitive", 10, "Escalation Sensitive Patterns"),
    ("compound_multi_intent", 10, "Compound Multi-Intent"),
    ("structural_risk_audit", 6, "Structural Risk / Data Quality Audit"),
    ("unstratified_control", 14, "Unstratified Control Candidates"),
]


def load_exclusions(exclusions_path: Path) -> Set[str]:
    """Load exclusion IDs from the text file."""
    exclusions = set()
    if exclusions_path.exists():
        with exclusions_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    exclusions.add(line)
    return exclusions


def audit_golden_set(
    candidates_path: Path,
    exclusions_path: Path,
    salt: str = FIXED_SALT,
    target_total: int = 200,
    min_multi_turn: int = 70,
) -> Dict[str, Any]:
    """Perform independent forensic audit of candidate dataset."""
    candidates_path = Path(candidates_path)
    exclusions_path = Path(exclusions_path)

    if not candidates_path.exists():
        raise FileNotFoundError(f"Candidates file not found: {candidates_path}")

    exclusions = load_exclusions(exclusions_path)

    records: List[Dict[str, Any]] = []
    with candidates_path.open("r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                records.append(rec)
            except json.JSONDecodeError as e:
                raise ValueError(f"Corrupt JSON at line {line_num}: {e}")

    # 1. Structural & Integrity Checks
    total_records = len(records)
    conversation_ids = [r.get("conversation_id") for r in records]
    unique_ids = set(conversation_ids)
    duplicate_conv_ids = [cid for cid, count in Counter(conversation_ids).items() if count > 1]

    # Check exclusions
    leaked_exclusions = [cid for cid in unique_ids if cid in exclusions]

    # Check schema conformance
    missing_fields_per_record = []
    for idx, r in enumerate(records):
        missing = [f for f in REQUIRED_SCHEMA_FIELDS if f not in r]
        if missing:
            missing_fields_per_record.append((idx, r.get("conversation_id"), missing))

    # Check internal tweet ID uniqueness
    duplicate_tweet_ids = []
    for r in records:
        tids = [m.get("tweet_id") for m in r.get("ordered_messages", []) if "tweet_id" in m]
        if len(tids) != len(set(tids)):
            duplicate_tweet_ids.append(r.get("conversation_id"))

    # Check hash validity and matching
    invalid_hash_format = []
    mismatched_hashes = []
    for r in records:
        cid = r.get("conversation_id", "")
        shash = r.get("sampling_hash", "")
        if not HEX_SHA256_PATTERN.match(shash):
            invalid_hash_format.append((cid, shash))
        expected_hash = hashlib.sha256(f"{cid}{salt}".encode("utf-8")).hexdigest()
        if shash != expected_hash:
            mismatched_hashes.append((cid, shash, expected_hash))

    # Check multi-turn consistency & count
    multi_turn_count = sum(1 for r in records if r.get("is_multi_turn"))
    turn_count_mismatches = [
        r.get("conversation_id")
        for r in records
        if r.get("is_multi_turn") != (r.get("customer_brand_interaction_turn_count", 0) >= 2)
    ]

    # 2. Quota Auditing
    strata_counts = Counter(s for r in records for s in r.get("sampling_strata", []))

    quota_results = []
    all_quotas_passed = True

    for stratum_key, required_quota, label in QUOTA_SPECIFICATIONS:
        actual_count = strata_counts.get(stratum_key, 0)
        shortfall = max(0, required_quota - actual_count)
        if stratum_key == "unstratified_control":
            passed = (actual_count == required_quota)
            if actual_count > required_quota:
                shortfall = actual_count - required_quota
        else:
            passed = actual_count >= required_quota
        if not passed:
            all_quotas_passed = False
        quota_results.append({
            "key": stratum_key,
            "label": label,
            "required": required_quota,
            "actual": actual_count,
            "shortfall": shortfall,
            "passed": passed,
        })

    # Overall Status Evaluation
    overall_passed = (
        total_records == target_total
        and len(unique_ids) == target_total
        and len(duplicate_conv_ids) == 0
        and len(leaked_exclusions) == 0
        and len(missing_fields_per_record) == 0
        and len(duplicate_tweet_ids) == 0
        and len(invalid_hash_format) == 0
        and len(mismatched_hashes) == 0
        and len(turn_count_mismatches) == 0
        and multi_turn_count >= min_multi_turn
        and all_quotas_passed
    )

    audit_summary = {
        "overall_passed": overall_passed,
        "total_records": total_records,
        "target_total": target_total,
        "unique_conversation_ids": len(unique_ids),
        "duplicate_conversation_ids": duplicate_conv_ids,
        "exclusions_checked": len(exclusions),
        "leaked_exclusions": leaked_exclusions,
        "missing_fields_count": len(missing_fields_per_record),
        "missing_fields_details": missing_fields_per_record,
        "duplicate_tweet_ids_in_thread": duplicate_tweet_ids,
        "invalid_hash_format_count": len(invalid_hash_format),
        "mismatched_hashes_count": len(mismatched_hashes),
        "multi_turn_count": multi_turn_count,
        "min_multi_turn_required": min_multi_turn,
        "turn_count_mismatches": turn_count_mismatches,
        "quota_results": quota_results,
    }

    return audit_summary


def print_audit_report(results: Dict[str, Any]) -> None:
    """Print formatted markdown audit report."""
    print("=" * 80)
    print("GOLDEN EVALUATION SET INDEPENDENT FORENSIC AUDIT REPORT")
    print("=" * 80)

    status_str = "PASS" if results["overall_passed"] else "FAIL"
    print(f"\nOVERALL AUDIT STATUS: [{status_str}]\n")

    print("--- 1. DATASET INTEGRITY & SCHEMA CHECKS ---")
    print(f"  - Total Candidates: {results['total_records']} (Target: {results['target_total']}) -> {'PASS' if results['total_records'] == results['target_total'] else 'FAIL'}")
    print(f"  - Unique Conversation IDs: {results['unique_conversation_ids']} (Duplicates: {len(results['duplicate_conversation_ids'])}) -> {'PASS' if len(results['duplicate_conversation_ids']) == 0 else 'FAIL'}")
    print(f"  - Excluded IDs Absent: {len(results['leaked_exclusions']) == 0} (Leaked: {results['leaked_exclusions']}) -> {'PASS' if len(results['leaked_exclusions']) == 0 else 'FAIL'}")
    print(f"  - Schema Integrity: {results['missing_fields_count'] == 0} (Records with missing fields: {results['missing_fields_count']}) -> {'PASS' if results['missing_fields_count'] == 0 else 'FAIL'}")
    print(f"  - Thread Tweet ID Uniqueness: {len(results['duplicate_tweet_ids_in_thread']) == 0} -> {'PASS' if len(results['duplicate_tweet_ids_in_thread']) == 0 else 'FAIL'}")
    print(f"  - Hash Format Valid (SHA-256): {results['invalid_hash_format_count'] == 0} -> {'PASS' if results['invalid_hash_format_count'] == 0 else 'FAIL'}")
    print(f"  - Deterministic Salt Hash Matching: {results['mismatched_hashes_count'] == 0} -> {'PASS' if results['mismatched_hashes_count'] == 0 else 'FAIL'}")
    print(f"  - Multi-Turn Floor (>= {results['min_multi_turn_required']}): Actual {results['multi_turn_count']} ({results['multi_turn_count']/results['total_records']*100:.1f}%) -> {'PASS' if results['multi_turn_count'] >= results['min_multi_turn_required'] else 'FAIL'}")

    print("\n--- 2. SAMPLING STRATA QUOTA AUDIT ---")
    print(f"{'Stratum Name':<50} | {'Required':<8} | {'Actual':<8} | {'Shortfall':<9} | {'Status'}")
    print("-" * 88)
    for q in results["quota_results"]:
        status = "PASS" if q["passed"] else "FAIL"
        print(f"{q['label']:<50} | {q['required']:<8} | {q['actual']:<8} | {q['shortfall']:<9} | {status}")

    print("=" * 80)


def main():
    parser = argparse.ArgumentParser(description="Independent audit for golden evaluation set candidates")
    parser.add_argument(
        "--candidates",
        type=Path,
        default=Path("data/processed/golden_set_candidates.jsonl"),
        help="Path to candidates JSONL file",
    )
    parser.add_argument(
        "--exclusions",
        type=Path,
        default=Path("data/processed/golden_set_exclusions.txt"),
        help="Path to exclusions text file",
    )
    parser.add_argument(
        "--salt",
        type=str,
        default=FIXED_SALT,
        help="Fixed salt for SHA256 verification",
    )

    args = parser.parse_args()

    results = audit_golden_set(
        candidates_path=args.candidates,
        exclusions_path=args.exclusions,
        salt=args.salt,
    )

    print_audit_report(results)

    if not results["overall_passed"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
