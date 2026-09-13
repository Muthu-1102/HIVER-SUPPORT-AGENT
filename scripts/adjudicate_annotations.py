#!/usr/bin/env python3
"""
Adjudication and Inter-Annotator Agreement Engine for Human Gold Annotations.

Processes completed annotation records (including the 50-item double-annotated subset):
1. Dynamically detects single-annotated vs double-annotated conversations directly from records.
2. Identifies disagreements by comparing actual field values across:
   - Primary label (is_non_intent, primary_intent, non_intent_class)
   - secondary_intents (set comparison)
   - technical_malfunction_scope
   - cross_cutting_flags (set comparison)
3. Computes Inter-Annotator Agreement metrics (Raw Agreement % and Cohen's Kappa).
4. Generates data/processed/golden_set_adjudications.jsonl documenting agreements and resolved disagreements.
5. Generates the canonical consolidated data/processed/golden_set_annotations.jsonl (exactly 200 records).
6. Ingests lead adjudications from provenance data rather than hardcoded resolution maps.
"""

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from sklearn.metrics import cohen_kappa_score

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Frozen Multi-Intent Priority Order Reference
# Priority: 06_login > 04_billing > 07_technical > 05_plan > 03_region > 01_catalog > 02_metadata > 08_feature > 09_artist
# ---------------------------------------------------------------------------
MULTI_INTENT_PRIORITY = [
    "06_login_authentication",
    "04_billing_payment",
    "07_technical_malfunction",
    "05_subscription_plan_management",
    "03_region_availability",
    "01_catalog_content_gap",
    "02_catalog_metadata_error",
    "08_feature_request",
    "09_artist_rights_holder_mgmt",
]


def get_effective_primary_label(rec: Dict[str, Any]) -> str:
    """Return 'non_intent:<class>' if is_non_intent, else substantive primary_intent."""
    if rec.get("is_non_intent"):
        return f"non_intent:{rec.get('non_intent_class')}"
    return str(rec.get("primary_intent"))


def detect_field_differences(
    rec_a: Dict[str, Any], rec_b: Dict[str, Any]
) -> Dict[str, Tuple[Any, Any]]:
    """
    Compare two annotation records across the 4 required dimensions:
    1. Primary label (is_non_intent, primary_intent, non_intent_class)
    2. Secondary intents (set comparison)
    3. Technical malfunction scope
    4. Cross cutting flags (set comparison)

    Returns a dict mapping field name -> (val_a, val_b) for any differences.
    """
    diffs: Dict[str, Tuple[Any, Any]] = {}

    label_a = (rec_a.get("is_non_intent"), rec_a.get("primary_intent"), rec_a.get("non_intent_class"))
    label_b = (rec_b.get("is_non_intent"), rec_b.get("primary_intent"), rec_b.get("non_intent_class"))
    if label_a != label_b:
        diffs["primary_label"] = (label_a, label_b)

    sec_a = set(rec_a.get("secondary_intents") or [])
    sec_b = set(rec_b.get("secondary_intents") or [])
    if sec_a != sec_b:
        diffs["secondary_intents"] = (sorted(list(sec_a)), sorted(list(sec_b)))

    scope_a = rec_a.get("technical_malfunction_scope")
    scope_b = rec_b.get("technical_malfunction_scope")
    if scope_a != scope_b:
        diffs["technical_malfunction_scope"] = (scope_a, scope_b)

    flags_a = set(rec_a.get("cross_cutting_flags") or [])
    flags_b = set(rec_b.get("cross_cutting_flags") or [])
    if flags_a != flags_b:
        diffs["cross_cutting_flags"] = (sorted(list(flags_a)), sorted(list(flags_b)))

    return diffs


def compute_inter_annotator_agreement(
    double_annotated_pairs: List[Tuple[Dict[str, Any], Dict[str, Any]]]
) -> Dict[str, Any]:
    """Compute raw agreement and Cohen's Kappa for double-annotated conversations directly from records."""
    total_pairs = len(double_annotated_pairs)
    if total_pairs == 0:
        return {
            "total_double_annotated": 0,
            "primary_label_raw_agreement_pct": 0.0,
            "cohens_kappa": 0.0,
            "scope_raw_agreement_pct": 0.0,
            "flags_raw_agreement_pct": 0.0,
            "secondary_raw_agreement_pct": 0.0,
            "full_consensus_count": 0,
            "disagreement_count": 0,
        }

    labels_a = []
    labels_b = []
    primary_matches = 0
    scope_matches = 0
    flag_matches = 0
    secondary_matches = 0
    full_consensus = 0

    for rec_a, rec_b in double_annotated_pairs:
        l_a = get_effective_primary_label(rec_a)
        l_b = get_effective_primary_label(rec_b)
        labels_a.append(l_a)
        labels_b.append(l_b)

        diffs = detect_field_differences(rec_a, rec_b)
        if "primary_label" not in diffs:
            primary_matches += 1
        if "technical_malfunction_scope" not in diffs:
            scope_matches += 1
        if "cross_cutting_flags" not in diffs:
            flag_matches += 1
        if "secondary_intents" not in diffs:
            secondary_matches += 1

        if not diffs:
            full_consensus += 1

    raw_agreement = (primary_matches / total_pairs) * 100.0
    scope_agreement = (scope_matches / total_pairs) * 100.0
    flag_agreement = (flag_matches / total_pairs) * 100.0
    secondary_agreement = (secondary_matches / total_pairs) * 100.0

    # Cohen's Kappa computation
    try:
        kappa = cohen_kappa_score(labels_a, labels_b)
        if kappa is None or str(kappa) == "nan":
            kappa = 1.0 if primary_matches == total_pairs else 0.0
    except Exception:
        kappa = 1.0 if primary_matches == total_pairs else 0.0

    return {
        "total_double_annotated": total_pairs,
        "primary_label_raw_agreement_pct": round(raw_agreement, 2),
        "cohens_kappa": round(float(kappa), 4),
        "scope_raw_agreement_pct": round(scope_agreement, 2),
        "flags_raw_agreement_pct": round(flag_agreement, 2),
        "secondary_raw_agreement_pct": round(secondary_agreement, 2),
        "full_consensus_count": full_consensus,
        "disagreement_count": total_pairs - full_consensus,
    }


def load_lead_adjudications_data(
    lead_adjudications_path: Optional[Path],
) -> Dict[str, Dict[str, Any]]:
    """Load lead adjudicator resolution records from data file."""
    if lead_adjudications_path is None:
        return {}
    path = Path(lead_adjudications_path)
    if not path.exists():
        return {}
    adjudications: Dict[str, Dict[str, Any]] = {}
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rec = json.loads(line)
                adjudications[rec["conversation_id"]] = rec
    return adjudications


def process_adjudications_from_annotators(
    annotator_1_path: Path = Path("data/processed/annotator_1_completed.jsonl"),
    annotator_2_path: Path = Path("data/processed/annotator_2_completed.jsonl"),
    candidates_path: Path = Path("data/processed/golden_set_candidates.jsonl"),
    output_adjudications_path: Path = Path("data/processed/golden_set_adjudications.jsonl"),
    output_consolidated_path: Path = Path("data/processed/golden_set_annotations.jsonl"),
    lead_adjudications_path: Optional[Path] = Path("data/processed/golden_set_lead_adjudications.jsonl"),
    min_double_annotation_count: int = 50,
) -> Dict[str, Any]:
    """
    Directly adjudicate from Annotator 1 and Annotator 2 completed files:
    1. Compares all overlapping candidate records field by field.
    2. Dynamically detects full consensus vs disagreements.
    3. Resolves consensus with 'annotator_id: consensus'.
    4. Resolves disagreements using authoritative lead adjudicator data records with 'annotator_id: adjudicator'.
    5. Builds the 50-record adjudication artifact and 200-record canonical gold annotations artifact.
    """
    annotator_1_path = Path(annotator_1_path)
    annotator_2_path = Path(annotator_2_path)
    candidates_path = Path(candidates_path)
    output_adjudications_path = Path(output_adjudications_path)
    output_consolidated_path = Path(output_consolidated_path)

    lead_adjudications = load_lead_adjudications_data(lead_adjudications_path)

    output_adjudications_path.parent.mkdir(parents=True, exist_ok=True)
    output_consolidated_path.parent.mkdir(parents=True, exist_ok=True)

    # 1. Load candidate IDs in order
    candidate_cids: List[str] = []
    with candidates_path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                candidate_cids.append(json.loads(line)["conversation_id"])

    # 2. Load Annotator 1 records
    a1_by_cid: Dict[str, Dict[str, Any]] = {}
    with annotator_1_path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rec = json.loads(line)
                a1_by_cid[rec["conversation_id"]] = rec

    # 3. Load Annotator 2 records
    a2_by_cid: Dict[str, Dict[str, Any]] = {}
    if annotator_2_path.exists():
        with annotator_2_path.open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    rec = json.loads(line)
                    a2_by_cid[rec["conversation_id"]] = rec

    double_annotated_pairs: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []
    adjudication_records: List[Dict[str, Any]] = []
    canonical_gold_records: List[Dict[str, Any]] = []
    unresolved_disagreements: List[Dict[str, Any]] = []

    for cid in candidate_cids:
        if cid not in a1_by_cid:
            raise RuntimeError(f"Candidate {cid} missing from Annotator 1 records!")

        r1 = a1_by_cid[cid]

        if cid in a2_by_cid:
            # Double annotated item
            r2 = a2_by_cid[cid]
            double_annotated_pairs.append((r1, r2))

            # Dynamically detect field differences
            field_diffs = detect_field_differences(r1, r2)
            has_disagreement = bool(field_diffs)

            if not has_disagreement:
                # Full consensus
                consensus_gold = dict(r1)
                consensus_gold["annotator_id"] = "consensus"
                canonical_gold_records.append(consensus_gold)

                adjudication_records.append({
                    "conversation_id": cid,
                    "annotator_a": r1.get("annotator_id", "annotator_1"),
                    "annotator_a_record": r1,
                    "annotator_b": r2.get("annotator_id", "annotator_2"),
                    "annotator_b_record": r2,
                    "has_disagreement": False,
                    "disagreement_fields": [],
                    "field_differences": {},
                    "resolved_by": "consensus",
                    "resolved_gold_record": consensus_gold,
                    "adjudication_reasoning": "Full consensus between Annotator 1 and Annotator 2 across all fields.",
                })
            else:
                # Disagreement detected from actual differences
                if cid in lead_adjudications:
                    adj_gold = lead_adjudications[cid]
                    canonical_gold_records.append(adj_gold)

                    adjudication_records.append({
                        "conversation_id": cid,
                        "annotator_a": r1.get("annotator_id", "annotator_1"),
                        "annotator_a_record": r1,
                        "annotator_b": r2.get("annotator_id", "annotator_2"),
                        "annotator_b_record": r2,
                        "has_disagreement": True,
                        "disagreement_fields": list(field_diffs.keys()),
                        "field_differences": {k: {"annotator_1": v[0], "annotator_2": v[1]} for k, v in field_diffs.items()},
                        "resolved_by": "adjudicator",
                        "resolved_gold_record": adj_gold,
                        "adjudication_reasoning": adj_gold.get("adjudication_reasoning", "Resolved by lead adjudicator."),
                    })
                else:
                    unresolved_disagreements.append({
                        "conversation_id": cid,
                        "field_differences": field_diffs,
                        "annotator_1_record": r1,
                        "annotator_2_record": r2,
                    })
        else:
            # Single annotation (Annotator 1)
            canonical_gold_records.append(r1)

    # Check for unresolved disagreements
    if unresolved_disagreements:
        err_msg = [
            f"FAIL: {len(unresolved_disagreements)} double-annotation disagreements lack lead adjudicator resolution:"
        ]
        for d in unresolved_disagreements:
            err_msg.append(f"  - [{d['conversation_id']}] Differences in: {list(d['field_differences'].keys())}")
        raise RuntimeError("\n".join(err_msg))

    agreement_metrics = compute_inter_annotator_agreement(double_annotated_pairs)

    # Write output files
    with output_adjudications_path.open("w", encoding="utf-8") as f:
        for r in adjudication_records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    with output_consolidated_path.open("w", encoding="utf-8") as f:
        for r in canonical_gold_records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    return {
        "total_candidates": len(candidate_cids),
        "canonical_gold_records": len(canonical_gold_records),
        "double_annotated_count": len(double_annotated_pairs),
        "agreement_metrics": agreement_metrics,
        "adjudications_written": len(adjudication_records),
    }


def process_adjudications(
    raw_annotations_path: Path,
    candidates_path: Path,
    output_adjudications_path: Path,
    output_consolidated_path: Path,
    min_double_annotation_count: int = 50,
) -> Dict[str, Any]:
    """Adjudicate raw annotations file (backward-compatible entrypoint)."""
    raw_annotations_path = Path(raw_annotations_path)
    candidates_path = Path(candidates_path)
    output_adjudications_path = Path(output_adjudications_path)
    output_consolidated_path = Path(output_consolidated_path)

    output_adjudications_path.parent.mkdir(parents=True, exist_ok=True)
    output_consolidated_path.parent.mkdir(parents=True, exist_ok=True)

    if not raw_annotations_path.exists():
        raise FileNotFoundError(f"Raw annotations file not found: {raw_annotations_path}")

    # Load candidate IDs
    candidate_cids = []
    with candidates_path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                candidate_cids.append(json.loads(line)["conversation_id"])

    # Load raw annotations grouped by conversation_id
    annotations_by_cid: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    with raw_annotations_path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rec = json.loads(line)
                annotations_by_cid[rec["conversation_id"]].append(rec)

    double_annotated_pairs = []
    adjudication_records = []
    canonical_gold_records = []
    unresolved_disagreements = []

    for cid in candidate_cids:
        recs = annotations_by_cid.get(cid, [])
        if not recs:
            raise RuntimeError(f"Missing annotation for candidate: {cid}")

        primary_annotators = [r for r in recs if r.get("annotator_id") not in ("adjudicator", "consensus")]
        adjudicator_recs = [r for r in recs if r.get("annotator_id") == "adjudicator"]

        if len(primary_annotators) == 1:
            canonical_gold_records.append(primary_annotators[0])
        elif len(primary_annotators) >= 2:
            rec_a = primary_annotators[0]
            rec_b = primary_annotators[1]
            double_annotated_pairs.append((rec_a, rec_b))

            field_diffs = detect_field_differences(rec_a, rec_b)
            has_disagreement = bool(field_diffs)

            if not has_disagreement:
                final_rec = dict(rec_a)
                final_rec["annotator_id"] = "consensus"
                canonical_gold_records.append(final_rec)

                adjudication_records.append({
                    "conversation_id": cid,
                    "annotator_a": rec_a["annotator_id"],
                    "annotator_a_record": rec_a,
                    "annotator_b": rec_b["annotator_id"],
                    "annotator_b_record": rec_b,
                    "has_disagreement": False,
                    "disagreement_fields": [],
                    "field_differences": {},
                    "resolved_by": "consensus",
                    "resolved_gold_record": final_rec,
                    "adjudication_reasoning": "Full consensus between Annotator 1 and Annotator 2 across all fields.",
                })
            else:
                if adjudicator_recs:
                    adj_rec = adjudicator_recs[0]
                    canonical_gold_records.append(adj_rec)
                    adjudication_records.append({
                        "conversation_id": cid,
                        "annotator_a": rec_a["annotator_id"],
                        "annotator_a_record": rec_a,
                        "annotator_b": rec_b["annotator_id"],
                        "annotator_b_record": rec_b,
                        "has_disagreement": True,
                        "disagreement_fields": list(field_diffs.keys()),
                        "field_differences": {k: {"annotator_1": v[0], "annotator_2": v[1]} for k, v in field_diffs.items()},
                        "resolved_by": adj_rec["annotator_id"],
                        "resolved_gold_record": adj_rec,
                        "adjudication_reasoning": adj_rec.get("adjudication_reasoning", adj_rec.get("evidence_quote", "Resolved by lead adjudicator.")),
                    })
                else:
                    unresolved_disagreements.append({
                        "conversation_id": cid,
                        "field_differences": field_diffs,
                        "annotator_a": rec_a["annotator_id"],
                        "annotator_b": rec_b["annotator_id"],
                    })

    if unresolved_disagreements:
        err_msg = [f"FAIL: {len(unresolved_disagreements)} double-annotation disagreements lack adjudicator resolution:"]
        for d in unresolved_disagreements:
            err_msg.append(f"  - [{d['conversation_id']}] Differences in: {list(d['field_differences'].keys())}")
        raise RuntimeError("\n".join(err_msg))

    agreement_metrics = compute_inter_annotator_agreement(double_annotated_pairs)

    with output_adjudications_path.open("w", encoding="utf-8") as f:
        for r in adjudication_records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    with output_consolidated_path.open("w", encoding="utf-8") as f:
        for r in canonical_gold_records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    return {
        "total_candidates": len(candidate_cids),
        "canonical_gold_records": len(canonical_gold_records),
        "double_annotated_count": len(double_annotated_pairs),
        "agreement_metrics": agreement_metrics,
        "adjudications_written": len(adjudication_records),
    }


def main():
    parser = argparse.ArgumentParser(description="Adjudication and Agreement Analysis for Gold Annotations")
    parser.add_argument(
        "--annotator-1",
        type=Path,
        default=Path("data/processed/annotator_1_completed.jsonl"),
        help="Path to Annotator 1 completed annotations JSONL",
    )
    parser.add_argument(
        "--annotator-2",
        type=Path,
        default=Path("data/processed/annotator_2_completed.jsonl"),
        help="Path to Annotator 2 completed annotations JSONL",
    )
    parser.add_argument(
        "--candidates",
        type=Path,
        default=Path("data/processed/golden_set_candidates.jsonl"),
        help="Path to candidates JSONL file",
    )
    parser.add_argument(
        "--lead-adjudications",
        type=Path,
        default=Path("data/processed/golden_set_lead_adjudications.jsonl"),
        help="Path to lead adjudications input JSONL",
    )
    parser.add_argument(
        "--output-adjudications",
        type=Path,
        default=Path("data/processed/golden_set_adjudications.jsonl"),
        help="Output path for adjudication records JSONL",
    )
    parser.add_argument(
        "--output-consolidated",
        type=Path,
        default=Path("data/processed/golden_set_annotations.jsonl"),
        help="Output path for final canonical gold annotations JSONL",
    )

    args = parser.parse_args()

    results = process_adjudications_from_annotators(
        annotator_1_path=args.annotator_1,
        annotator_2_path=args.annotator_2,
        candidates_path=args.candidates,
        lead_adjudications_path=args.lead_adjudications,
        output_adjudications_path=args.output_adjudications,
        output_consolidated_path=args.output_consolidated,
    )

    print("=" * 80)
    print("GOLD SET ANNOTATION ADJUDICATION & AGREEMENT REPORT")
    print("=" * 80)
    print(f"Total Candidates: {results['total_candidates']}")
    print(f"Consolidated Gold Records Written: {results['canonical_gold_records']}")
    print(f"Double-Annotated Records: {results['double_annotated_count']}")
    print("\nInter-Annotator Agreement Metrics:")
    for k, v in results["agreement_metrics"].items():
        print(f"  - {k}: {v}")
    print("=" * 80)


if __name__ == "__main__":
    main()
