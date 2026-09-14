"""Deterministic Golden Set evaluation harness for the Spotify Support Agent.

Evaluates SpotifySupportAgent end-to-end against the 200 canonical
human gold annotations in data/processed/golden_set_annotations.jsonl.

Outputs:
- evaluation/golden_set_results.json
- evaluation/golden_set_error_analysis.jsonl
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.spotify_agent.agent import SpotifySupportAgent
from src.spotify_agent.intent_classifier import (
    NON_INTENT_CLASSES,
    SUBSTANTIVE_INTENTS,
)
GOLDEN_CANDIDATES_PATH = PROJECT_ROOT / "data" / "processed" / "golden_set_candidates.jsonl"
GOLDEN_ANNOTATIONS_PATH = PROJECT_ROOT / "data" / "processed" / "golden_set_annotations.jsonl"
EVALUATION_DIR = PROJECT_ROOT / "evaluation"
RESULTS_JSON_PATH = EVALUATION_DIR / "golden_set_results.json"
ERROR_ANALYSIS_JSONL_PATH = EVALUATION_DIR / "golden_set_error_analysis.jsonl"

ALL_INTENT_LABELS = list(SUBSTANTIVE_INTENTS) + list(NON_INTENT_CLASSES)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    """Load records from a JSONL file in order."""
    records: list[dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line_str = line.strip()
            if line_str:
                records.append(json.loads(line_str))
    return records


def evaluate_agent(
    candidates_path: Path = GOLDEN_CANDIDATES_PATH,
    annotations_path: Path = GOLDEN_ANNOTATIONS_PATH,
    results_path: Path = RESULTS_JSON_PATH,
    error_analysis_path: Path = ERROR_ANALYSIS_JSONL_PATH,
) -> dict[str, Any]:
    """Run end-to-end evaluation and produce deterministic summary and error reports."""
    gold_records = load_jsonl(annotations_path)
    candidates_records = load_jsonl(candidates_path)

    # Index candidates by conversation_id
    candidates_by_id = {c["conversation_id"]: c for c in candidates_records}

    # Verify referential integrity
    gold_ids = [g["conversation_id"] for g in gold_records]
    if len(gold_ids) != len(set(gold_ids)):
        raise ValueError("Duplicate conversation IDs found in gold annotations.")

    agent = SpotifySupportAgent()

    # Sort gold records deterministically by conversation_id
    sorted_gold = sorted(gold_records, key=lambda g: g["conversation_id"])

    total = len(sorted_gold)
    primary_correct = 0
    secondary_correct = 0
    scope_correct = 0
    flags_correct = 0
    non_intent_correct = 0
    full_exact_match = 0

    # Initialize confusion matrix for primary intent
    confusion_matrix: dict[str, dict[str, int]] = {
        gold_lbl: {pred_lbl: 0 for pred_lbl in ALL_INTENT_LABELS}
        for gold_lbl in ALL_INTENT_LABELS
    }

    per_intent_counts: dict[str, dict[str, int]] = {
        lbl: {"gold_count": 0, "correct_count": 0, "predicted_count": 0}
        for lbl in ALL_INTENT_LABELS
    }

    error_analysis_records: list[dict[str, Any]] = []
    detailed_evaluations: list[dict[str, Any]] = []

    for gold in sorted_gold:
        conv_id = gold["conversation_id"]
        candidate = candidates_by_id[conv_id]

        # Run agent through full pipeline
        agent_result = agent.process_conversation(candidate)
        pred_cls = agent_result.classification

        # Extract gold attributes
        gold_primary = gold["primary_intent"]
        gold_secondary = sorted(gold.get("secondary_intents") or [])
        gold_scope = gold.get("technical_malfunction_scope")
        gold_flags = sorted(gold.get("cross_cutting_flags") or [])
        gold_is_non_intent = bool(gold.get("is_non_intent", False))
        gold_non_intent_class = gold.get("non_intent_class")

        # Extract predicted attributes
        pred_primary = pred_cls.primary_intent
        pred_secondary = sorted(pred_cls.secondary_intents)
        pred_scope = pred_cls.technical_malfunction_scope
        pred_flags = sorted(pred_cls.cross_cutting_flags)
        pred_is_non_intent = pred_cls.is_non_intent
        pred_non_intent_class = pred_cls.non_intent_class

        # Update confusion matrix and counts
        if gold_primary in confusion_matrix and pred_primary in confusion_matrix[gold_primary]:
            confusion_matrix[gold_primary][pred_primary] += 1

        if gold_primary in per_intent_counts:
            per_intent_counts[gold_primary]["gold_count"] += 1
        if pred_primary in per_intent_counts:
            per_intent_counts[pred_primary]["predicted_count"] += 1

        # Check field matches
        match_primary = (pred_primary == gold_primary)
        match_secondary = (pred_secondary == gold_secondary)
        match_scope = (pred_scope == gold_scope)
        match_flags = (pred_flags == gold_flags)
        match_non_intent = (pred_is_non_intent == gold_is_non_intent and pred_non_intent_class == gold_non_intent_class)

        if match_primary:
            primary_correct += 1
            if gold_primary in per_intent_counts:
                per_intent_counts[gold_primary]["correct_count"] += 1

        if match_secondary:
            secondary_correct += 1
        if match_scope:
            scope_correct += 1
        if match_flags:
            flags_correct += 1
        if match_non_intent:
            non_intent_correct += 1

        is_full_match = (
            match_primary
            and match_secondary
            and match_scope
            and match_flags
            and match_non_intent
        )

        if is_full_match:
            full_exact_match += 1

        mismatches: list[str] = []
        if not match_primary:
            mismatches.append("primary_intent")
        if not match_secondary:
            mismatches.append("secondary_intents")
        if not match_scope:
            mismatches.append("technical_malfunction_scope")
        if not match_flags:
            mismatches.append("cross_cutting_flags")
        if not match_non_intent:
            mismatches.append("is_non_intent / non_intent_class")

        gold_dict = {
            "primary_intent": gold_primary,
            "secondary_intents": gold_secondary,
            "technical_malfunction_scope": gold_scope,
            "cross_cutting_flags": gold_flags,
            "is_non_intent": gold_is_non_intent,
            "non_intent_class": gold_non_intent_class,
        }

        pred_dict = {
            "primary_intent": pred_primary,
            "secondary_intents": pred_secondary,
            "technical_malfunction_scope": pred_scope,
            "cross_cutting_flags": pred_flags,
            "is_non_intent": pred_is_non_intent,
            "non_intent_class": pred_non_intent_class,
        }

        customer_text = agent_result.conversation.combined_customer_text or (
            agent_result.conversation.root_message.clean_text if agent_result.conversation.root_message else ""
        )

        record_eval = {
            "conversation_id": conv_id,
            "customer_text": customer_text,
            "gold_classification": gold_dict,
            "predicted_classification": pred_dict,
            "mismatched_fields": mismatches,
            "is_full_match": is_full_match,
        }
        detailed_evaluations.append(record_eval)

        if mismatches:
            error_analysis_records.append({
                "conversation_id": conv_id,
                "customer_text": customer_text,
                "gold_classification": gold_dict,
                "predicted_classification": pred_dict,
                "mismatched_fields": mismatches,
            })

    # Compute overall metrics
    metrics = {
        "total_records": total,
        "primary_intent_accuracy": round(primary_correct / total, 4) if total else 0.0,
        "primary_intent_correct": primary_correct,
        "secondary_intents_accuracy": round(secondary_correct / total, 4) if total else 0.0,
        "secondary_intents_correct": secondary_correct,
        "technical_scope_accuracy": round(scope_correct / total, 4) if total else 0.0,
        "technical_scope_correct": scope_correct,
        "cross_cutting_flags_accuracy": round(flags_correct / total, 4) if total else 0.0,
        "cross_cutting_flags_correct": flags_correct,
        "non_intent_accuracy": round(non_intent_correct / total, 4) if total else 0.0,
        "non_intent_correct": non_intent_correct,
        "full_record_exact_match_accuracy": round(full_exact_match / total, 4) if total else 0.0,
        "full_record_exact_match_correct": full_exact_match,
        "total_errors": len(error_analysis_records),
    }

    report_data = {
        "evaluation_dataset": "SpotifyCares Golden Evaluation Set (200 records)",
        "metrics": metrics,
        "per_intent_metrics": per_intent_counts,
        "confusion_matrix": confusion_matrix,
    }

    # Ensure evaluation output directory exists
    results_path.parent.mkdir(parents=True, exist_ok=True)
    error_analysis_path.parent.mkdir(parents=True, exist_ok=True)

    # Write deterministic JSON report
    with open(results_path, "w", encoding="utf-8") as f:
        json.dump(report_data, f, indent=2, sort_keys=True)

    # Write deterministic error analysis JSONL
    with open(error_analysis_path, "w", encoding="utf-8") as f:
        for err in error_analysis_records:
            f.write(json.dumps(err, sort_keys=True) + "\n")

    return report_data


def print_evaluation_summary(report_data: dict[str, Any]) -> None:
    """Print a clean CLI summary of evaluation results."""
    metrics = report_data["metrics"]
    total = metrics["total_records"]

    print("=" * 80)
    print("SPOTIFY SUPPORT AGENT — GOLDEN EVALUATION RESULTS")
    print("=" * 80)
    print(f"Total Evaluated Records:              {total}")
    print(f"Primary Intent Accuracy:              {metrics['primary_intent_accuracy']:.2%} ({metrics['primary_intent_correct']}/{total})")
    print(f"Secondary Intents Exact Match:        {metrics['secondary_intents_accuracy']:.2%} ({metrics['secondary_intents_correct']}/{total})")
    print(f"Technical Malfunction Scope Accuracy: {metrics['technical_scope_accuracy']:.2%} ({metrics['technical_scope_correct']}/{total})")
    print(f"Cross-Cutting Flags Accuracy:         {metrics['cross_cutting_flags_accuracy']:.2%} ({metrics['cross_cutting_flags_correct']}/{total})")
    print(f"Non-Intent Accuracy:                  {metrics['non_intent_accuracy']:.2%} ({metrics['non_intent_correct']}/{total})")
    print(f"Full Record Exact Match Accuracy:     {metrics['full_record_exact_match_accuracy']:.2%} ({metrics['full_record_exact_match_correct']}/{total})")
    print(f"Total Discrepancies / Errors:         {metrics['total_errors']}")
    print("=" * 80)
    print("\nPer-Intent Breakdown:")
    print(f"{'Intent Label':<35} | {'Gold':<6} | {'Pred':<6} | {'Correct':<8} | {'Recall':<8}")
    print("-" * 75)
    for intent, counts in sorted(report_data["per_intent_metrics"].items()):
        gold_c = counts["gold_count"]
        pred_c = counts["predicted_count"]
        corr_c = counts["correct_count"]
        recall = f"{corr_c / gold_c:.1%}" if gold_c > 0 else "N/A"
        print(f"{intent:<35} | {gold_c:<6} | {pred_c:<6} | {corr_c:<8} | {recall:<8}")
    print("=" * 80)


if __name__ == "__main__":
    results = evaluate_agent()
    print_evaluation_summary(results)
