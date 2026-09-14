"""Compare LLM Judge evaluations against independent-reviewer ratings.

Reads LLM-as-judge outputs and reviewer ratings, aligns them by conversation_id,
and computes standard agreement metrics:
1. Exact Agreement Rate (%)
2. Mean Absolute Error (MAE)
3. Mean Bias Error (Judge - Reviewer)
4. Spearman Rank Correlation (rho)
5. Pearson Correlation (r)
6. Cohen's Kappa / Quadratic Weighted Kappa (QWK)

Integrity constraints:
- NEVER fabricates reviewer ratings.
- If reviewer ratings are absent or incomplete, clearly reports the missing count
  and halts without claiming agreement.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.spotify_agent.llm_judge import RUBRIC_DIMENSIONS

EVALUATION_DIR = PROJECT_ROOT / "evaluation"
DEFAULT_JUDGE_RESULTS = EVALUATION_DIR / "llm_judge_results.jsonl"
DEFAULT_REVIEWER_RATINGS = EVALUATION_DIR / "independent_reviewer_ratings.jsonl"
DEFAULT_REVIEWER_TEMPLATE = EVALUATION_DIR / "human_judge_ratings_template.jsonl"

ALL_SCORE_FIELDS = list(RUBRIC_DIMENSIONS) + ["overall_score"]


def load_jsonl(path: Path) -> List[Dict[str, Any]]:
    """Load JSONL file records into a list."""
    if not path.exists():
        return []
    records: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line_str = line.strip()
            if line_str:
                records.append(json.loads(line_str))
    return records


def calculate_mean_absolute_error(reviewer: List[int], judge: List[int]) -> float:
    """Calculate Mean Absolute Error between reviewer and judge ratings."""
    if not reviewer:
        return 0.0
    return sum(abs(r - j) for r, j in zip(reviewer, judge)) / len(reviewer)


def calculate_mean_bias(reviewer: List[int], judge: List[int]) -> float:
    """Calculate Mean Bias Error (Judge - Reviewer)."""
    if not reviewer:
        return 0.0
    return sum(j - r for r, j in zip(reviewer, judge)) / len(reviewer)


def calculate_exact_agreement(reviewer: List[int], judge: List[int]) -> float:
    """Calculate exact match percentage (0.0 to 100.0)."""
    if not reviewer:
        return 0.0
    matches = sum(1 for r, j in zip(reviewer, judge) if r == j)
    return (matches / len(reviewer)) * 100.0


def calculate_pearson_correlation(x: List[float], y: List[float]) -> Optional[float]:
    """Calculate Pearson correlation coefficient r."""
    n = len(x)
    if n < 2:
        return None
    mean_x = sum(x) / n
    mean_y = sum(y) / n
    var_x = sum((xi - mean_x) ** 2 for xi in x)
    var_y = sum((yi - mean_y) ** 2 for yi in y)
    if var_x == 0 or var_y == 0:
        return 1.0 if x == y else 0.0
    cov = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y))
    return cov / math.sqrt(var_x * var_y)


def _rank_values(arr: List[float]) -> List[float]:
    """Compute average fractional ranks for tied values."""
    indexed = sorted(enumerate(arr), key=lambda item: item[1])
    ranks = [0.0] * len(arr)
    i = 0
    while i < len(indexed):
        j = i
        while j < len(indexed) and indexed[j][1] == indexed[i][1]:
            j += 1
        avg_rank = (i + 1 + j) / 2.0
        for k in range(i, j):
            ranks[indexed[k][0]] = avg_rank
        i = j
    return ranks


def calculate_spearman_correlation(x: List[int], y: List[int]) -> Optional[float]:
    """Calculate Spearman rank correlation rho."""
    if len(x) < 2:
        return None
    ranks_x = _rank_values([float(val) for val in x])
    ranks_y = _rank_values([float(val) for val in y])
    return calculate_pearson_correlation(ranks_x, ranks_y)


def calculate_quadratic_weighted_kappa(
    reviewer: List[int],
    judge: List[int],
    min_rating: int = 1,
    max_rating: int = 5,
) -> Optional[float]:
    """Calculate Quadratic Weighted Cohen's Kappa for ordinal ratings (1-5)."""
    n = len(reviewer)
    if n < 2:
        return None

    num_categories = max_rating - min_rating + 1
    observed = [[0.0] * num_categories for _ in range(num_categories)]
    for r, j in zip(reviewer, judge):
        r_idx = max(0, min(num_categories - 1, r - min_rating))
        j_idx = max(0, min(num_categories - 1, j - min_rating))
        observed[r_idx][j_idx] += 1.0

    # Marginal sums
    hist_r = [sum(observed[i][j] for j in range(num_categories)) for i in range(num_categories)]
    hist_j = [sum(observed[i][j] for i in range(num_categories)) for j in range(num_categories)]

    # Expected matrix
    expected = [[(hist_r[i] * hist_j[j]) / float(n) for j in range(num_categories)] for i in range(num_categories)]

    # Quadratic weights: w_ij = 1 - ((i - j)^2 / (num_categories - 1)^2)
    # Distance weights: d_ij = ((i - j)^2 / (num_categories - 1)^2)
    denom_weight = (num_categories - 1) ** 2
    weighted_obs = 0.0
    weighted_exp = 0.0

    for i in range(num_categories):
        for j in range(num_categories):
            weight = ((i - j) ** 2) / denom_weight
            weighted_obs += weight * observed[i][j]
            weighted_exp += weight * expected[i][j]

    if weighted_exp == 0.0:
        return 1.0 if weighted_obs == 0.0 else 0.0

    return 1.0 - (weighted_obs / weighted_exp)


def evaluate_agreement(
    reviewer_records: List[Dict[str, Any]],
    judge_records: List[Dict[str, Any]],
    evaluator_label: str = "Reviewer",
) -> Dict[str, Any]:
    """Compare ratings and compile multi-dimensional agreement statistics."""
    judge_by_id = {r["conversation_id"]: r for r in judge_records if "conversation_id" in r}

    completed_reviewer: List[Dict[str, Any]] = []
    missing_reviewer_count = 0

    for reviewer_record in reviewer_records:
        conv_id = reviewer_record.get("conversation_id")
        if not conv_id:
            continue
        # Check if all required dimensions are filled with non-null numbers
        is_complete = True
        for field in ALL_SCORE_FIELDS:
            val = reviewer_record.get(field)
            if val is None or not isinstance(val, (int, float)):
                is_complete = False
                break
        if is_complete:
            completed_reviewer.append(reviewer_record)
        else:
            missing_reviewer_count += 1

    total_candidates = len(reviewer_records)
    n_completed = len(completed_reviewer)

    report: Dict[str, Any] = {
        "evaluator_label": evaluator_label,
        "total_records_in_evaluator_file": total_candidates,
        "total_records_in_reviewer_file": total_candidates,
        "completed_ratings_count": n_completed,
        "completed_reviewer_ratings_count": n_completed,
        "missing_ratings_count": missing_reviewer_count,
        "missing_reviewer_ratings_count": missing_reviewer_count,
        "is_agreement_evaluable": n_completed > 0,
        "dimensions": {},
    }

    if n_completed == 0:
        return report

    # Extract paired vectors for each dimension
    paired_ids = []
    for reviewer_record in completed_reviewer:
        conv_id = reviewer_record["conversation_id"]
        if conv_id in judge_by_id:
            paired_ids.append(conv_id)

    report["matched_conversations_count"] = len(paired_ids)

    for field in ALL_SCORE_FIELDS:
        reviewer_vals: List[int] = []
        judge_vals: List[int] = []
        for conv_id in paired_ids:
            reviewer_val = int(next(r[field] for r in completed_reviewer if r["conversation_id"] == conv_id))
            j_val = int(judge_by_id[conv_id][field])
            reviewer_vals.append(reviewer_val)
            judge_vals.append(j_val)

        exact_acc = calculate_exact_agreement(reviewer_vals, judge_vals)
        mae = calculate_mean_absolute_error(reviewer_vals, judge_vals)
        bias = calculate_mean_bias(reviewer_vals, judge_vals)
        spearman = calculate_spearman_correlation(reviewer_vals, judge_vals)
        qwk = calculate_quadratic_weighted_kappa(reviewer_vals, judge_vals)

        report["dimensions"][field] = {
            "evaluator_mean": sum(reviewer_vals) / len(reviewer_vals) if reviewer_vals else 0.0,
            "reviewer_mean": sum(reviewer_vals) / len(reviewer_vals) if reviewer_vals else 0.0,
            "judge_mean": sum(judge_vals) / len(judge_vals) if judge_vals else 0.0,
            "exact_agreement_pct": round(exact_acc, 2),
            "mean_absolute_error": round(mae, 3),
            "mean_bias": round(bias, 3),
            "spearman_rho": round(spearman, 3) if spearman is not None else None,
            "quadratic_weighted_kappa": round(qwk, 3) if qwk is not None else None,
        }

    return report


def print_agreement_report(report: Dict[str, Any], label: str = "Reviewer") -> None:
    """Print a clean formatted comparison report."""
    print("=" * 75)
    print(f"LLM-as-Judge vs. {label} Rating Agreement Evaluation")
    print("=" * 75)
    print(f"Total reviewer records       : {report['total_records_in_reviewer_file']}")
    print(f"Completed {label} ratings (N): {report['completed_reviewer_ratings_count']}")
    print(f"Missing / unrated records    : {report['missing_reviewer_ratings_count']}")

    if not report["is_agreement_evaluable"] or report.get("matched_conversations_count", 0) == 0:
        print(f"\n[STATUS: PENDING {label.upper()} RATINGS]")
        print(f"{label} ratings have not been completed yet (scores are null).")
        print("=" * 75)
        return

    n_matched = report["matched_conversations_count"]
    print(f"Aligned Judge-{label} pairs (N): {n_matched}")
    print("-" * 75)
    print(f"{'Dimension':<24} | {label[:6]:<6} | {'Judge':<6} | {'Exact%':<7} | {'MAE':<6} | {'Spearman':<8} | {'QWK':<6}")
    print("-" * 75)

    for field, metrics in report["dimensions"].items():
        spearman_str = f"{metrics['spearman_rho']:.3f}" if metrics['spearman_rho'] is not None else "N/A"
        qwk_str = f"{metrics['quadratic_weighted_kappa']:.3f}" if metrics['quadratic_weighted_kappa'] is not None else "N/A"
        print(
            f"{field:<24} | "
            f"{metrics['reviewer_mean']:<6.2f} | "
            f"{metrics['judge_mean']:<6.2f} | "
            f"{metrics['exact_agreement_pct']:<6.1f}% | "
            f"{metrics['mean_absolute_error']:<6.2f} | "
            f"{spearman_str:<8} | "
            f"{qwk_str:<6}"
        )
    print("=" * 75)


def main() -> None:
    """CLI entrypoint for compare_judge_human."""
    parser = argparse.ArgumentParser(description="Compare LLM Judge evaluation against reviewer ratings.")
    parser.add_argument("--judge-results", type=Path, default=DEFAULT_JUDGE_RESULTS, help="Path to LLM judge results JSONL")
    parser.add_argument("--reviewer-ratings", "--human-ratings", dest="reviewer_ratings", type=Path, default=DEFAULT_REVIEWER_RATINGS, help="Path to completed reviewer ratings JSONL; --human-ratings is a backward-compatible alias")
    parser.add_argument("--template", type=Path, default=DEFAULT_REVIEWER_TEMPLATE, help="Fallback rating template path if reviewer ratings are absent")
    parser.add_argument("--output", type=Path, default=None, help="Optional path to output agreement JSON report")
    parser.add_argument("--evaluator-label", type=str, default="Reviewer", help="Label for evaluator entity (e.g. 'Independent Reviewer')")

    args = parser.parse_args()

    # Prefer completed reviewer ratings; otherwise use the blank rating template.
    reviewer_path = args.reviewer_ratings if args.reviewer_ratings.exists() else args.template
    reviewer_records = load_jsonl(reviewer_path)
    judge_records = load_jsonl(args.judge_results)

    label = args.evaluator_label
    if "independent" in str(reviewer_path).lower() or "reviewer" in str(reviewer_path).lower():
        if label == "Reviewer":
            label = "Independent Reviewer"

    report = evaluate_agreement(reviewer_records, judge_records, evaluator_label=label)
    print_agreement_report(report, label=label)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        print(f"\nAgreement report saved to: {args.output}")


if __name__ == "__main__":
    main()
