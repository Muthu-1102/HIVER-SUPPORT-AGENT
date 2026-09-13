#!/usr/bin/env python3
"""
Canonical Builder Script for SpotifyCares Human Gold Annotations.

Ingests authoritative completed blind annotation files:
- data/processed/annotator_1_completed.jsonl (200 records)
- data/processed/annotator_2_completed.jsonl (50 double-annotation records)

Executes the approved adjudication workflow:
1. Dynamically detects disagreements across primary_label, secondary_intents, technical_malfunction_scope, and cross_cutting_flags.
2. Computes empirical inter-annotator agreement metrics (raw % and Cohen's Kappa).
3. Resolves double-annotated consensus and applies lead-adjudicator resolutions.
4. Generates data/processed/golden_set_adjudications.jsonl (50 records).
5. Generates data/processed/golden_set_annotations.jsonl (canonical 200 records).
"""

import argparse
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.adjudicate_annotations import (
    process_adjudications_from_annotators,
    compute_inter_annotator_agreement,
    detect_field_differences,
)


def build_canonical_gold_set(
    annotator_1_path: Path = Path("data/processed/annotator_1_completed.jsonl"),
    annotator_2_path: Path = Path("data/processed/annotator_2_completed.jsonl"),
    candidates_path: Path = Path("data/processed/golden_set_candidates.jsonl"),
    adjudications_path: Path = Path("data/processed/golden_set_adjudications.jsonl"),
    annotations_path: Path = Path("data/processed/golden_set_annotations.jsonl"),
    lead_adjudications_path: Path = Path("data/processed/golden_set_lead_adjudications.jsonl"),
):
    print("=" * 80)
    print("BUILDING CANONICAL GOLD ANNOTATIONS FROM COMPLETED ANNOTATOR FILES")
    print("=" * 80)
    print(f"Annotator 1 Path:       {annotator_1_path}")
    print(f"Annotator 2 Path:       {annotator_2_path}")
    print(f"Candidates Path:        {candidates_path}")
    print(f"Lead Adjudications In:  {lead_adjudications_path}")
    print(f"Adjudications Out:      {adjudications_path}")
    print(f"Annotations Out:        {annotations_path}")
    print("=" * 80)

    results = process_adjudications_from_annotators(
        annotator_1_path=annotator_1_path,
        annotator_2_path=annotator_2_path,
        candidates_path=candidates_path,
        output_adjudications_path=adjudications_path,
        output_consolidated_path=annotations_path,
        lead_adjudications_path=lead_adjudications_path,
    )

    print("\n--- CANONICAL BUILD SUMMARY ---")
    print(f"Total Candidate Conversations:    {results['total_candidates']}")
    print(f"Canonical Gold Records Written:   {results['canonical_gold_records']}")
    print(f"Double-Annotated Records Audited: {results['double_annotated_count']}")
    print(f"Adjudication Records Written:     {results['adjudications_written']}")

    metrics = results["agreement_metrics"]
    print("\n--- INTER-ANNOTATOR AGREEMENT METRICS ---")
    print(f"  - Primary Label Raw Agreement:   {metrics['primary_label_raw_agreement_pct']}%")
    print(f"  - Cohen's Kappa (κ):             {metrics['cohens_kappa']}")
    print(f"  - Scope Raw Agreement:           {metrics['scope_raw_agreement_pct']}%")
    print(f"  - Flags Raw Agreement:           {metrics['flags_raw_agreement_pct']}%")
    print(f"  - Secondary Raw Agreement:       {metrics['secondary_raw_agreement_pct']}%")
    print(f"  - Full Consensus Count:          {metrics['full_consensus_count']}")
    print(f"  - Disagreements Adjudicated:     {metrics['disagreement_count']}")
    print("=" * 80)

    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build canonical gold annotations and adjudication records.")
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
        "--output-annotations",
        type=Path,
        default=Path("data/processed/golden_set_annotations.jsonl"),
        help="Output path for final canonical gold annotations JSONL",
    )

    args = parser.parse_args()

    build_canonical_gold_set(
        annotator_1_path=args.annotator_1,
        annotator_2_path=args.annotator_2,
        candidates_path=args.candidates,
        adjudications_path=args.output_adjudications,
        annotations_path=args.output_annotations,
        lead_adjudications_path=args.lead_adjudications,
    )
