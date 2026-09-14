"""Deterministic Holdout Evaluation Harness for the Spotify Support Agent.

Evaluates SpotifySupportAgent on unseen conversations from the reconstructed
Spotify corpus (data/processed/spotify_conversations.jsonl) that are strictly
excluded from the 200 canonical gold annotations.

This evaluation is UNLABELED / QUALITATIVE: it demonstrates generalization
and stability across unseen conversations without creating synthetic gold labels.

Outputs:
- evaluation/holdout_evaluation_results.json
"""

from __future__ import annotations

import json
from pathlib import Path
import random
import sys
from typing import Any, Dict, List, Optional, Set

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.spotify_agent.agent import SpotifySupportAgent
from src.spotify_agent.intent_classifier import (
    NON_INTENT_CLASSES,
    SUBSTANTIVE_INTENTS,
)

CORPUS_PATH = PROJECT_ROOT / "data" / "processed" / "spotify_conversations.jsonl"
GOLDEN_ANNOTATIONS_PATH = PROJECT_ROOT / "data" / "processed" / "golden_set_annotations.jsonl"
EVALUATION_DIR = PROJECT_ROOT / "evaluation"
HOLDOUT_RESULTS_PATH = EVALUATION_DIR / "holdout_evaluation_results.json"

DEFAULT_SAMPLE_SIZE = 50
DEFAULT_SEED = 42


def load_canonical_gold_ids(annotations_path: Path = GOLDEN_ANNOTATIONS_PATH) -> set[str]:
    """Load canonical gold conversation IDs to guarantee strict exclusion."""
    gold_ids: set[str] = set()
    with open(annotations_path, "r", encoding="utf-8") as f:
        for line in f:
            line_str = line.strip()
            if line_str:
                data = json.loads(line_str)
                gold_ids.add(data["conversation_id"])
    return gold_ids


def extract_eligible_holdout_conversations(
    corpus_path: Path = CORPUS_PATH,
    gold_ids: Optional[set[str]] = None,
) -> list[dict[str, Any]]:
    """Extract eligible conversations from the full corpus that are not in the gold set."""
    if gold_ids is None:
        gold_ids = load_canonical_gold_ids()

    eligible: list[dict[str, Any]] = []
    with open(corpus_path, "r", encoding="utf-8") as f:
        for line in f:
            line_str = line.strip()
            if not line_str:
                continue
            rec = json.loads(line_str)
            root_id = rec.get("thread_root_tweet_id")
            if root_id is None:
                continue
            cid = f"spotify_root_{root_id}"

            # Strict exclusion of canonical gold set
            if cid in gold_ids:
                continue

            # Eligibility: contains customer + spotify interaction and at least 2 turns
            if not rec.get("contains_customer_and_spotify", False):
                continue
            messages = rec.get("ordered_messages", [])
            if len(messages) < 2:
                continue

            rec["conversation_id"] = cid
            eligible.append(rec)

    # Sort deterministically by conversation_id prior to sampling
    eligible.sort(key=lambda r: r["conversation_id"])
    return eligible


def sample_holdout_conversations(
    eligible_records: list[dict[str, Any]],
    sample_size: int = DEFAULT_SAMPLE_SIZE,
    seed: int = DEFAULT_SEED,
) -> list[dict[str, Any]]:
    """Deterministically sample a fixed number of holdout conversations."""
    if sample_size > len(eligible_records):
        raise ValueError(f"Requested sample size {sample_size} exceeds eligible pool {len(eligible_records)}")

    rng = random.Random(seed)
    sampled = rng.sample(eligible_records, sample_size)
    sampled.sort(key=lambda r: r["conversation_id"])
    return sampled


def evaluate_holdout(
    corpus_path: Path = CORPUS_PATH,
    annotations_path: Path = GOLDEN_ANNOTATIONS_PATH,
    results_path: Path = HOLDOUT_RESULTS_PATH,
    sample_size: int = DEFAULT_SAMPLE_SIZE,
    seed: int = DEFAULT_SEED,
) -> dict[str, Any]:
    """Execute qualitative generalization evaluation on strictly unseen holdout records."""
    gold_ids = load_canonical_gold_ids(annotations_path)
    eligible = extract_eligible_holdout_conversations(corpus_path, gold_ids)
    sampled = sample_holdout_conversations(eligible, sample_size=sample_size, seed=seed)

    agent = SpotifySupportAgent()

    primary_intent_dist: dict[str, int] = {k: 0 for k in list(SUBSTANTIVE_INTENTS) + list(NON_INTENT_CLASSES)}
    technical_scope_dist: dict[str, int] = {"individual": 0, "platform_wide": 0, "unclear": 0, "none": 0}
    flags_dist: dict[str, int] = {
        "alternate_channel_request": 0,
        "prior_interaction_dissatisfaction": 0,
        "no_flags": 0,
    }
    queue_dist: dict[str, int] = {}

    eval_records: list[dict[str, Any]] = []

    for rec in sampled:
        cid = rec["conversation_id"]
        # Double check exclusion invariant
        if cid in gold_ids:
            raise RuntimeError(f"Contamination error: Gold ID {cid} found in holdout sample!")

        res = agent.process_conversation(rec)
        cls = res.classification
        routing = res.routing
        resp = res.response

        # Primary distribution
        prim_key = cls.primary_intent if cls.primary_intent else str(cls.non_intent_class)
        primary_intent_dist[prim_key] = primary_intent_dist.get(prim_key, 0) + 1

        # Scope distribution
        scope_key = cls.technical_malfunction_scope if cls.technical_malfunction_scope else "none"
        technical_scope_dist[scope_key] = technical_scope_dist.get(scope_key, 0) + 1

        # Flags distribution
        if cls.cross_cutting_flags:
            for f in cls.cross_cutting_flags:
                flags_dist[f] = flags_dist.get(f, 0) + 1
        else:
            flags_dist["no_flags"] += 1

        # Queue distribution
        queue_dist[routing.target_queue] = queue_dist.get(routing.target_queue, 0) + 1

        # Collect preview text
        cust_preview = ""
        for m in rec.get("ordered_messages", []):
            if m.get("inbound", False):
                cust_preview = m.get("text", "")[:120]
                break

        eval_records.append({
            "conversation_id": cid,
            "message_count": len(rec.get("ordered_messages", [])),
            "customer_inquiry_preview": cust_preview,
            "predicted_primary_intent": cls.primary_intent,
            "predicted_secondary_intents": list(cls.secondary_intents),
            "predicted_technical_scope": cls.technical_malfunction_scope,
            "predicted_cross_cutting_flags": list(cls.cross_cutting_flags),
            "predicted_is_non_intent": cls.is_non_intent,
            "predicted_non_intent_class": cls.non_intent_class,
            "confidence": cls.confidence,
            "target_queue": routing.target_queue,
            "action": routing.action,
            "priority": routing.priority,
            "requires_human_escalation": resp.requires_human_escalation,
            "requires_channel_handoff": resp.requires_channel_handoff,
            "response_preview": resp.text[:120] + "..." if len(resp.text) > 120 else resp.text,
        })

    summary: dict[str, Any] = {
        "evaluation_type": "UNLABELED / QUALITATIVE GENERALIZATION HOLDOUT",
        "description": "Generalization evaluation on unseen Spotify conversations strictly excluded from canonical gold annotations.",
        "sampling_seed": seed,
        "eligible_corpus_count": len(eligible),
        "sampled_holdout_count": len(sampled),
        "canonical_gold_overlap_count": 0,
        "predicted_primary_intent_distribution": {k: v for k, v in primary_intent_dist.items() if v > 0},
        "predicted_technical_scope_distribution": technical_scope_dist,
        "predicted_cross_cutting_flags_distribution": flags_dist,
        "predicted_target_queue_distribution": queue_dist,
        "holdout_evaluations": eval_records,
    }

    results_path.parent.mkdir(parents=True, exist_ok=True)
    with open(results_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    return summary


def print_holdout_report(summary: dict[str, Any]) -> None:
    """Print a clean summary of holdout evaluation results."""
    print("=" * 80)
    print("SPOTIFY SUPPORT AGENT — UNLABELED HOLDOUT GENERALIZATION REPORT")
    print("=" * 80)
    print(f"Evaluation Mode:               {summary['evaluation_type']}")
    print(f"Eligible Corpus Conversations: {summary['eligible_corpus_count']:,}")
    print(f"Sampled Holdout Count:         {summary['sampled_holdout_count']}")
    print(f"Sampling Seed:                 {summary['sampling_seed']}")
    print(f"Canonical Gold Set Overlap:    {summary['canonical_gold_overlap_count']} (Strict Zero Overlap)")
    print("=" * 80)
    print("\nPredicted Primary Intent Distribution across Holdout:")
    print(f"{'Intent Label':<35} | {'Count':<6} | {'Share (%)':<10}")
    print("-" * 57)
    for intent, count in sorted(summary["predicted_primary_intent_distribution"].items(), key=lambda x: -x[1]):
        share = (count / summary["sampled_holdout_count"]) * 100.0
        print(f"{intent:<35} | {count:<6} | {share:>8.1f}%")
    print("-" * 57)

    print("\nPredicted Technical Scope Distribution:")
    for scope, count in summary["predicted_technical_scope_distribution"].items():
        print(f"  - {scope:<15}: {count}")

    print("\nPredicted Cross-Cutting Flags Distribution:")
    for flag, count in summary["predicted_cross_cutting_flags_distribution"].items():
        print(f"  - {flag:<35}: {count}")

    print("\nSample Holdout Predictions (First 5 records):")
    for r in summary["holdout_evaluations"][:5]:
        clean_inquiry = r['customer_inquiry_preview'].encode('ascii', 'replace').decode('ascii')
        print(f"  * [{r['conversation_id']}] ({r['message_count']} msgs)")
        print(f"    Inquiry:  \"{clean_inquiry}\"")
        print(f"    Pred:     Primary={r['predicted_primary_intent']}, Sec={r['predicted_secondary_intents']}, Scope={r['predicted_technical_scope']}, Flags={r['predicted_cross_cutting_flags']}")
        print(f"    Routing:  Queue={r['target_queue']} | Action={r['action']}")
        print()
    print("=" * 80)


if __name__ == "__main__":
    report = evaluate_holdout()
    print_holdout_report(report)
