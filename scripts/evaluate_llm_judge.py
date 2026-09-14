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
DEFAULT_TEMPLATE_PATH = EVALUATION_DIR / "human_judge_ratings_template.jsonl"


def load_jsonl(path: Path) -> List[Dict[str, Any]]:
    """Load JSONL file records into a list."""
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
    provider: Optional[str] = None,
    output_path: Path = DEFAULT_OUTPUT_PATH,
    template_path: Path = DEFAULT_TEMPLATE_PATH,
    dry_run: bool = False,
) -> List[Dict[str, Any]]:
    """Run end-to-end LLM judge evaluation on deterministic gold subset."""
    candidates = load_jsonl(GOLDEN_CANDIDATES_PATH)
    sample_candidates = select_deterministic_subset(candidates, sample_size=sample_size, seed=seed)

    agent = SpotifySupportAgent()

    # Generate or refresh human rating template with identical 30 items
    generate_human_template(sample_candidates, agent, template_path)
    print(f"[Template] Human rating template written to: {template_path}")

    if dry_run:
        print(f"[Dry-run] Sampled {len(sample_candidates)} records (seed={seed}). Skipping live LLM calls.")
        return []

    resolved_provider, _, _, chosen_model = resolve_judge_config(provider=provider, model=model)
    print(f"[LLM Judge] Evaluating {len(sample_candidates)} conversations using provider: {resolved_provider} | model: {chosen_model}")

    results: List[Dict[str, Any]] = []
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f_out:
        for idx, candidate in enumerate(sample_candidates, start=1):
            conv_id = candidate["conversation_id"]
            customer_text, historical_context = extract_customer_and_historical_text(candidate)

            agent_result = agent.process_conversation(candidate)
            generated_response = agent_result.text

            print(f"[{idx}/{len(sample_candidates)}] Grading conversation {conv_id}...", end=" ", flush=True)

            score: JudgeScore = evaluate_response(
                customer_text=customer_text,
                agent_response=generated_response,
                historical_context=historical_context,
                model=chosen_model,
                provider=resolved_provider,
            )

            result_entry = {
                "conversation_id": conv_id,
                "sampling_seed": seed,
                "provider": resolved_provider,
                "model": score.model,
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
            print(f"Done (Overall: {score.overall_score}/5)")

    # Compute and print summary
    if results:
        print("\n" + "=" * 60)
        print(f"LLM-as-Judge Evaluation Summary (N={len(results)})")
        print("=" * 60)
        for dim in RUBRIC_DIMENSIONS:
            avg_dim = sum(r[dim] for r in results) / len(results)
            print(f"  - {dim:<25}: {avg_dim:.2f} / 5.00")
        avg_overall = sum(r["overall_score"] for r in results) / len(results)
        print(f"  - {'overall_score':<25}: {avg_overall:.2f} / 5.00")
        print("=" * 60)
        print(f"Results saved to: {output_path}")

    return results


def main() -> None:
    """CLI entrypoint for evaluate_llm_judge."""
    parser = argparse.ArgumentParser(description="Evaluate SpotifySupportAgent responses with LLM Judge (OpenRouter or Groq).")
    parser.add_argument("--sample-size", type=int, default=30, help="Number of records to evaluate (default: 30)")
    parser.add_argument("--seed", type=int, default=42, help="Deterministic random seed (default: 42)")
    parser.add_argument("--provider", type=str, default=None, choices=["openrouter", "groq"], help="LLM Provider ('openrouter' or 'groq')")
    parser.add_argument("--model", type=str, default=None, help="Model identifier (default from provider env or defaults)")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH, help="Path for JSONL results output")
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE_PATH, help="Path for human ratings template")
    parser.add_argument("--dry-run", action="store_true", help="Generate template and sample without calling LLM API")

    args = parser.parse_args()

    run_llm_judge_evaluation(
        sample_size=args.sample_size,
        seed=args.seed,
        model=args.model,
        provider=args.provider,
        output_path=args.output,
        template_path=args.template,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
