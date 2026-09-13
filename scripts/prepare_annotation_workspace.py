#!/usr/bin/env python3
"""
Human Gold Annotation Workspace Preparation Utility.

Prepares the annotation workspace for human annotators:
1. Loads the 200 candidates from data/processed/golden_set_candidates.jsonl without modifying the file.
2. Deterministically selects exactly 50 candidates (25%) for independent double annotation using:
   SHA256(conversation_id + "hiver-double-annotation-v1")
3. Exports the 50 double-annotation conversation IDs to:
   data/processed/double_annotation_conversation_ids.txt
4. Generates empty annotation templates (with all gold labels set to null):
   - data/processed/annotator_1_workspace.jsonl (all 200 candidate templates)
   - data/processed/annotator_2_workspace.jsonl (50 double-annotation candidate templates)
5. Provides a merge utility to assemble completed annotator workspaces into
   data/processed/golden_set_raw_annotations.jsonl for adjudication.
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

DOUBLE_ANNOTATION_SALT = "hiver-double-annotation-v1"
DOUBLE_ANNOTATION_TARGET = 50


def compute_double_annotation_hash(conversation_id: str, salt: str = DOUBLE_ANNOTATION_SALT) -> str:
    """Compute deterministic hash for double-annotation sampling."""
    return hashlib.sha256(f"{conversation_id}{salt}".encode("utf-8")).hexdigest()


def select_double_annotation_subset(
    candidate_records: List[Dict[str, Any]],
    target_count: int = DOUBLE_ANNOTATION_TARGET,
    salt: str = DOUBLE_ANNOTATION_SALT,
) -> List[Dict[str, Any]]:
    """Deterministically rank and select 50 candidate records for double annotation."""
    ranked = sorted(
        candidate_records,
        key=lambda r: compute_double_annotation_hash(r["conversation_id"], salt),
    )
    return ranked[:target_count]


def create_empty_annotation_template(
    conversation_id: str, annotator_id: str
) -> Dict[str, Any]:
    """Create a blank annotation record template conforming to Schema v1.0.0."""
    return {
        "conversation_id": conversation_id,
        "annotator_id": annotator_id,
        "annotation_timestamp": None,
        "is_non_intent": None,
        "primary_intent": None,
        "secondary_intents": [],
        "non_intent_class": None,
        "technical_malfunction_scope": None,
        "cross_cutting_flags": [],
        "is_ambiguous": False,
        "ambiguity_category": None,
        "ambiguity_notes": None,
        "confidence": None,
        "evidence_quote": None,
        "schema_version": "1.0.0",
    }


def prepare_annotation_workspace(
    candidates_path: Path,
    output_double_ids_path: Path,
    output_annotator_1_path: Path,
    output_annotator_2_path: Path,
    salt: str = DOUBLE_ANNOTATION_SALT,
    target_double_count: int = DOUBLE_ANNOTATION_TARGET,
) -> Dict[str, Any]:
    """Initialize blank workspaces and double-annotation tracking list."""
    candidates_path = Path(candidates_path)
    output_double_ids_path = Path(output_double_ids_path)
    output_annotator_1_path = Path(output_annotator_1_path)
    output_annotator_2_path = Path(output_annotator_2_path)

    output_double_ids_path.parent.mkdir(parents=True, exist_ok=True)
    output_annotator_1_path.parent.mkdir(parents=True, exist_ok=True)
    output_annotator_2_path.parent.mkdir(parents=True, exist_ok=True)

    if not candidates_path.exists():
        raise FileNotFoundError(f"Candidates file not found: {candidates_path}")

    candidate_records: List[Dict[str, Any]] = []
    with candidates_path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                candidate_records.append(json.loads(line))

    total_candidates = len(candidate_records)
    if total_candidates != 200:
        raise ValueError(f"Expected 200 candidates, found {total_candidates}")

    # Deterministic double-annotation selection
    double_subset = select_double_annotation_subset(
        candidate_records, target_count=target_double_count, salt=salt
    )
    double_cids = [r["conversation_id"] for r in double_subset]

    # 1. Write double-annotation IDs list
    with output_double_ids_path.open("w", encoding="utf-8") as f:
        f.write("# Deterministically Selected 50 Double-Annotation Candidate IDs (25%)\n")
        f.write(f"# Salt: {salt}\n")
        for cid in double_cids:
            f.write(f"{cid}\n")

    # 2. Write Annotator 1 Workspace (200 blank templates)
    annotator_1_templates = [
        create_empty_annotation_template(r["conversation_id"], "annotator_1")
        for r in candidate_records
    ]
    with output_annotator_1_path.open("w", encoding="utf-8") as f:
        for t in annotator_1_templates:
            f.write(json.dumps(t, ensure_ascii=False) + "\n")

    # 3. Write Annotator 2 Workspace (50 blank templates for double annotation)
    annotator_2_templates = [
        create_empty_annotation_template(cid, "annotator_2")
        for cid in double_cids
    ]
    with output_annotator_2_path.open("w", encoding="utf-8") as f:
        for t in annotator_2_templates:
            f.write(json.dumps(t, ensure_ascii=False) + "\n")

    return {
        "total_candidates": total_candidates,
        "annotator_1_templates": len(annotator_1_templates),
        "annotator_2_templates": len(annotator_2_templates),
        "double_annotation_cids": double_cids,
    }


def merge_annotator_workspaces(
    annotator_1_path: Path,
    annotator_2_path: Path,
    output_raw_path: Path,
) -> int:
    """Merge completed Annotator 1 and Annotator 2 workspaces into golden_set_raw_annotations.jsonl."""
    annotator_1_path = Path(annotator_1_path)
    annotator_2_path = Path(annotator_2_path)
    output_raw_path = Path(output_raw_path)

    merged_records = []
    if annotator_1_path.exists():
        with annotator_1_path.open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    merged_records.append(json.loads(line))

    if annotator_2_path.exists():
        with annotator_2_path.open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    merged_records.append(json.loads(line))

    output_raw_path.parent.mkdir(parents=True, exist_ok=True)
    with output_raw_path.open("w", encoding="utf-8") as f:
        for r in merged_records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    return len(merged_records)


def main():
    parser = argparse.ArgumentParser(description="Prepare Human Gold Annotation Workspace")
    parser.add_argument(
        "--candidates",
        type=Path,
        default=Path("data/processed/golden_set_candidates.jsonl"),
        help="Path to golden set candidates JSONL file",
    )
    parser.add_argument(
        "--output-double-ids",
        type=Path,
        default=Path("data/processed/double_annotation_conversation_ids.txt"),
        help="Output path for double-annotation IDs list",
    )
    parser.add_argument(
        "--output-annotator-1",
        type=Path,
        default=Path("data/processed/annotator_1_workspace.jsonl"),
        help="Output path for Annotator 1 blank workspace",
    )
    parser.add_argument(
        "--output-annotator-2",
        type=Path,
        default=Path("data/processed/annotator_2_workspace.jsonl"),
        help="Output path for Annotator 2 blank workspace (50 items)",
    )
    parser.add_argument(
        "--merge",
        action="store_true",
        help="Merge completed annotator workspaces into golden_set_raw_annotations.jsonl",
    )
    parser.add_argument(
        "--output-raw",
        type=Path,
        default=Path("data/processed/golden_set_raw_annotations.jsonl"),
        help="Output path when merging into raw annotations",
    )

    args = parser.parse_args()

    if args.merge:
        count = merge_annotator_workspaces(
            annotator_1_path=args.output_annotator_1,
            annotator_2_path=args.output_annotator_2,
            output_raw_path=args.output_raw,
        )
        print(f"Successfully merged {count} completed annotations into {args.output_raw}")
        return

    results = prepare_annotation_workspace(
        candidates_path=args.candidates,
        output_double_ids_path=args.output_double_ids,
        output_annotator_1_path=args.output_annotator_1,
        output_annotator_2_path=args.output_annotator_2,
    )

    print("=" * 80)
    print("HUMAN GOLD ANNOTATION WORKSPACE PREPARATION REPORT")
    print("=" * 80)
    print(f"Total Candidates Loaded: {results['total_candidates']}")
    print(f"Annotator 1 Workspace Generated: {results['annotator_1_templates']} templates -> {args.output_annotator_1}")
    print(f"Annotator 2 Workspace Generated: {results['annotator_2_templates']} templates -> {args.output_annotator_2}")
    print(f"Double-Annotation IDs Saved: {len(results['double_annotation_cids'])} IDs -> {args.output_double_ids}")
    print("=" * 80)


if __name__ == "__main__":
    main()
