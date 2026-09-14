"""Deterministic LLM-as-a-judge evaluation harness for Spotify Support Agent.

Samples a deterministic subset (default N=30, seed=42) from the 200 canonical
gold conversations, runs the deterministic SpotifySupportAgent to generate
support replies, evaluates each reply across the 5-dimension rubric using
OpenRouter, and saves the structured results to evaluation/llm_judge_results.jsonl.

Security:
- API key is ONLY read from the OPENROUTER_API_KEY environment variable.
- Model is configurable via the OPENROUTER_MODEL environment variable or --model flag.
- Never mutates canonical gold data.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import random
import sys
from typing import Any, Dict, List, Optional

import time
from typing import Any, Dict, List, Optional, Set

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.spotify_agent.agent import SpotifySupportAgent
from src.spotify_agent.llm_judge import (
    DEFAULT_GROQ_FALLBACK_MODEL,
    DEFAULT_GROQ_MODEL,
    DEFAULT_OPENROUTER_MODEL,
    RUBRIC_DIMENSIONS,
    JudgeScore,
    evaluate_response,
    resolve_judge_config,
)

GOLDEN_CANDIDATES_PATH = PROJECT_ROOT / "data" / "processed" / "golden_set_candidates.jsonl"
GOLDEN_ANNOTATIONS_PATH = PROJECT_ROOT / "data" / "processed" / "golden_set_annotations.jsonl"
EVALUATION_DIR = PROJECT_ROOT / "evaluation"
DEFAULT_OUTPUT_PATH = EVALUATION_DIR / "llm_judge_results.jsonl"
DEFAULT_STAGING_OUTPUT_PATH = EVALUATION_DIR / "llm_judge_results_complete.jsonl"
DEFAULT_TEMPLATE_PATH = EVALUATION_DIR / "human_judge_ratings_template.jsonl"


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


def select_deterministic_subset(
    records: List[Dict[str, Any]],
    sample_size: int = 30,
    seed: int = 42,
) -> List[Dict[str, Any]]:
    """Deterministically sample N records using fixed seed and sorted IDs."""
    sorted_records = sorted(records, key=lambda r: str(r.get("conversation_id", "")))
    rng = random.Random(seed)
    return rng.sample(sorted_records, min(sample_size, len(sorted_records)))


def extract_customer_and_historical_text(candidate: Dict[str, Any]) -> tuple[str, Optional[str]]:
    """Extract inbound customer inquiry and historical Spotify response context."""
    ordered_messages = candidate.get("ordered_messages", [])
    inbound_texts = []
    brand_texts = []

    for msg in ordered_messages:
        text = msg.get("text", "").strip()
        if msg.get("inbound", True):
            inbound_texts.append(f"Customer: {text}")
        else:
            author = msg.get("author_id", "SpotifyCares")
            brand_texts.append(f"{author}: {text}")

    customer_text = "\n".join(inbound_texts) if inbound_texts else "Customer inquiry"
    historical_context = "\n".join(brand_texts) if brand_texts else None
    return customer_text, historical_context


def generate_human_template(
    sample_candidates: List[Dict[str, Any]],
    agent: SpotifySupportAgent,
    template_path: Path = DEFAULT_TEMPLATE_PATH,
) -> None:
    """Generate blank template for human annotator evaluation."""
    template_path.parent.mkdir(parents=True, exist_ok=True)
    with open(template_path, "w", encoding="utf-8") as f:
        for candidate in sample_candidates:
            conv_id = candidate["conversation_id"]
            customer_text, historical_context = extract_customer_and_historical_text(candidate)
            agent_result = agent.process_conversation(candidate)

            record = {
                "conversation_id": conv_id,
                "customer_text": customer_text,
                "historical_context": historical_context,
                "generated_response": agent_result.text,
                "predicted_intent": agent_result.classification.primary_intent,
                "target_queue": agent_result.target_queue,
                "correctness": None,
                "groundedness": None,
                "helpfulness": None,
                "brand_appropriateness": None,
                "safety_escalation": None,
                "overall_score": None,
                "human_notes": "",
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def run_llm_judge_evaluation(
    sample_size: int = 30,
    seed: int = 42,
    model: Optional[str] = None,
    fallback_model: Optional[str] = None,
    provider: Optional[str] = None,
    output_path: Optional[Path] = None,
    resume_from: Optional[Path] = None,
    template_path: Path = DEFAULT_TEMPLATE_PATH,
    inter_request_delay: float = 8.0,
    dry_run: bool = False,
) -> List[Dict[str, Any]]:
    """Run end-to-end LLM judge evaluation on deterministic gold subset with resumption support."""
    candidates = load_jsonl(GOLDEN_CANDIDATES_PATH)
    sample_candidates = select_deterministic_subset(candidates, sample_size=sample_size, seed=seed)

    agent = SpotifySupportAgent()

    # Generate or refresh human rating template with identical sample items
    generate_human_template(sample_candidates, agent, template_path)
    print(f"[Template] Human rating template written to: {template_path}")

    # Resolve config
    resolved_provider, _, _, chosen_model = resolve_judge_config(provider=provider, model=model)
    effective_fallback = fallback_model
    if effective_fallback is None and resolved_provider == "groq":
        effective_fallback = DEFAULT_GROQ_FALLBACK_MODEL

    # Determine existing completed records if resume_from is provided
    existing_by_id: Dict[str, Dict[str, Any]] = {}
    if resume_from and resume_from.exists():
        for r in load_jsonl(resume_from):
            if "conversation_id" in r:
                existing_by_id[r["conversation_id"]] = r

    # Partition sample into existing (skipped) and pending
    skipped_records: List[Dict[str, Any]] = []
    pending_candidates: List[Dict[str, Any]] = []

    for candidate in sample_candidates:
        cid = candidate["conversation_id"]
        if cid in existing_by_id:
            skipped_records.append(existing_by_id[cid])
        else:
            pending_candidates.append(candidate)

    # Set default output path
    actual_output = output_path
    if actual_output is None:
        actual_output = DEFAULT_STAGING_OUTPUT_PATH if resume_from else DEFAULT_OUTPUT_PATH

    print(f"\n[LLM Judge Config]")
    print(f"  - Provider               : {resolved_provider}")
    print(f"  - Primary Model          : {chosen_model}")
    print(f"  - Fallback Model         : {effective_fallback or 'None'}")
    print(f"  - Inter-Request Delay    : {inter_request_delay}s")
    print(f"  - Total Sample Size      : {len(sample_candidates)}")
    print(f"  - Resumed Existing (Skip): {len(skipped_records)}")
    print(f"  - Pending New Calls      : {len(pending_candidates)}")
    print(f"  - Output Target Path     : {actual_output}")

    if skipped_records:
        print(f"\n[Skipped Conversation IDs ({len(skipped_records)})]:")
        for idx, rec in enumerate(skipped_records, 1):
            print(f"   {idx:>2}. {rec['conversation_id']} (Model: {rec.get('model', 'unknown')})")

    if pending_candidates:
        print(f"\n[Pending Conversation IDs ({len(pending_candidates)})]:")
        for idx, cand in enumerate(pending_candidates, 1):
            print(f"   {idx:>2}. {cand['conversation_id']}")

    if dry_run:
        print(f"\n[Dry-run] Completed plan verification. Skipping live LLM calls.")
        return skipped_records

    results: List[Dict[str, Any]] = []
    actual_output.parent.mkdir(parents=True, exist_ok=True)

    # In live run, first write existing records into staging output file (with fallback_used defaulted if legacy)
    with open(actual_output, "w", encoding="utf-8") as f_out:
        for rec in skipped_records:
            entry = dict(rec)
            if "fallback_used" not in entry:
                entry["fallback_used"] = False
            if "attempts" not in entry:
                entry["attempts"] = 1
            f_out.write(json.dumps(entry, ensure_ascii=False) + "\n")
            f_out.flush()
            results.append(entry)

        # Then evaluate pending records sequentially with delay
        for idx, candidate in enumerate(pending_candidates, start=1):
            conv_id = candidate["conversation_id"]
            customer_text, historical_context = extract_customer_and_historical_text(candidate)

            agent_result = agent.process_conversation(candidate)
            generated_response = agent_result.text

            print(
                f"[{idx}/{len(pending_candidates)}] (Overall {len(results)+1}/{len(sample_candidates)}) "
                f"Grading {conv_id}...",
                end=" ",
                flush=True,
            )

            score: JudgeScore = evaluate_response(
                customer_text=customer_text,
                agent_response=generated_response,
                historical_context=historical_context,
                model=chosen_model,
                fallback_model=effective_fallback,
                provider=resolved_provider,
            )

            result_entry = {
                "conversation_id": conv_id,
                "sampling_seed": seed,
                "provider": resolved_provider,
                "model": score.model,
                "fallback_used": score.fallback_used,
                "attempts": score.attempts,
                "customer_text": customer_text,
                "historical_context": historical_context,
                "generated_response": generated_response,
                "primary_intent_predicted": agent_result.classification.primary_intent,
                "target_queue": agent_result.target_queue,
                "action": agent_result.action,
                "correctness": score.correctness,
                "groundedness": score.groundedness,
                "helpfulness": score.helpfulness,
                "brand_appropriateness": score.brand_appropriateness,
                "safety_escalation": score.safety_escalation,
                "overall_score": score.overall_score,
                "short_reason": score.short_reason,
                "evaluated_at": datetime.now(timezone.utc).isoformat(),
            }

            f_out.write(json.dumps(result_entry, ensure_ascii=False) + "\n")
            f_out.flush()
            results.append(result_entry)
            print(f"Done (Model: {score.model} | Overall: {score.overall_score}/5 | Fallback: {score.fallback_used})")

            # Pacing delay between live API calls
            if idx < len(pending_candidates) and inter_request_delay > 0:
                time.sleep(inter_request_delay)

    # Compute and print summary
    if results:
        print("\n" + "=" * 60)
        print(f"LLM-as-Judge Evaluation Summary (N={len(results)})")
        print("=" * 60)
        models_used = set(r.get("model", "unknown") for r in results)
        print(f"Models Used: {', '.join(sorted(models_used))}")
        for dim in RUBRIC_DIMENSIONS:
            avg_dim = sum(r[dim] for r in results) / len(results)
            print(f"  - {dim:<25}: {avg_dim:.2f} / 5.00")
        avg_overall = sum(r["overall_score"] for r in results) / len(results)
        print(f"  - {'overall_score':<25}: {avg_overall:.2f} / 5.00")
        print("=" * 60)
        print(f"Completed results written to: {actual_output}")

    return results


def main() -> None:
    """CLI entrypoint for evaluate_llm_judge."""
    parser = argparse.ArgumentParser(description="Evaluate SpotifySupportAgent responses with LLM Judge (OpenRouter or Groq).")
    parser.add_argument("--sample-size", type=int, default=30, help="Number of records to evaluate (default: 30)")
    parser.add_argument("--seed", type=int, default=42, help="Deterministic random seed (default: 42)")
    parser.add_argument("--provider", type=str, default=None, choices=["openrouter", "groq"], help="LLM Provider ('openrouter' or 'groq')")
    parser.add_argument("--model", type=str, default=None, help="Primary model identifier")
    parser.add_argument("--fallback-model", type=str, default=None, help="Fallback model identifier (default: openai/gpt-oss-20b on Groq)")
    parser.add_argument("--output", type=Path, default=None, help="Path for JSONL results output")
    parser.add_argument("--resume-from", type=Path, default=None, help="Path to existing JSONL results to resume and skip completed IDs")
    parser.add_argument("--delay", type=float, default=8.0, help="Inter-request delay in seconds (default: 8.0s)")
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE_PATH, help="Path for human ratings template")
    parser.add_argument("--dry-run", action="store_true", help="Generate template and sample plan without calling live LLM API")

    args = parser.parse_args()

    run_llm_judge_evaluation(
        sample_size=args.sample_size,
        seed=args.seed,
        model=args.model,
        fallback_model=args.fallback_model,
        provider=args.provider,
        output_path=args.output,
        resume_from=args.resume_from,
        template_path=args.template,
        inter_request_delay=args.delay,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
