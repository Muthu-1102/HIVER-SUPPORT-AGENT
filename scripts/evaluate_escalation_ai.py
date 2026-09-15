#!/usr/bin/env python3
"""AI-assisted escalation annotation and evaluation for the independent 40-record subset.

This component is intentionally separate from the canonical intent benchmark and from
the existing response-quality judge. It creates two independent AI annotations, sends
only disagreements to a third AI adjudicator, and evaluates the production routing
engine against the adjudicated AI-assisted labels.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from dotenv import dotenv_values

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.spotify_agent.routing_engine import route_conversation

MANIFEST_PATH = PROJECT_ROOT / "data/processed/escalation_annotation_candidates.jsonl"
SOURCE_PATH = PROJECT_ROOT / "data/processed/spotify_conversations.jsonl"
GOLD_PATH = PROJECT_ROOT / "data/processed/golden_set_annotations.jsonl"
OUTPUT_DIR = PROJECT_ROOT / "evaluation"
ANNOTATOR_A_PATH = OUTPUT_DIR / "escalation_ai_annotations_a.jsonl"
ANNOTATOR_B_PATH = OUTPUT_DIR / "escalation_ai_annotations_b.jsonl"
ADJUDICATION_PATH = OUTPUT_DIR / "escalation_ai_adjudications.jsonl"
RESULTS_PATH = OUTPUT_DIR / "escalation_ai_results.json"

SCHEMA_VERSION = "escalation-ai-v1.0.0"
PROMPT_VERSION = "escalation-ai-prompt-v1.0.0"
SELECTION_VERSION = "escalation-workspace-v1"
ALLOWED_DECISIONS = {"yes", "no", "unclear"}
ALLOWED_HANDOFF = {"yes", "no", "unclear"}
ALLOWED_URGENCY = {"low", "normal", "high", "critical", "unclear"}
ALLOWED_TYPES = {
    "security_account_compromise",
    "minor_or_child_account",
    "repeated_or_duplicate_charge",
    "churn_or_cancellation_threat",
    "prior_unresolved_support",
    "privacy_or_secure_channel",
    "other",
    "none",
}

ANNOTATION_FIELDS = {
    "escalation_required",
    "escalation_types",
    "channel_handoff_required",
    "urgency",
    "evidence_quote",
    "is_ambiguous",
    "ambiguity_notes",
    "confidence",
}


def load_jsonl(path: Path) -> List[Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def dump_jsonl(path: Path, records: Iterable[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def source_record_hash(record: Dict[str, Any]) -> str:
    payload = json.dumps(record, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def load_cases() -> List[Dict[str, Any]]:
    manifest = load_jsonl(MANIFEST_PATH)
    source_lines = [line for line in SOURCE_PATH.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    gold_ids = {record["conversation_id"] for record in load_jsonl(GOLD_PATH)}
    cases: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for item in manifest:
        cid = item["conversation_id"]
        if cid in seen:
            raise ValueError(f"Duplicate escalation candidate: {cid}")
        seen.add(cid)
        if cid in gold_ids:
            raise ValueError(f"Escalation candidate overlaps canonical gold: {cid}")
        line_number = int(item["source_line_number"])
        source = json.loads(source_lines[line_number - 1])
        if source.get("conversation_thread_id") != cid:
            raise ValueError(f"Source ID mismatch for {cid}")
        if source_record_hash(source) != item["source_record_sha256"]:
            raise ValueError(f"Source hash mismatch for {cid}")
        cases.append({"manifest": item, "conversation": source})
    if len(cases) != 40:
        raise ValueError(f"Expected 40 escalation cases, found {len(cases)}")
    return cases


def conversation_text(conversation: Dict[str, Any]) -> str:
    lines = []
    for message in conversation.get("ordered_messages", []):
        speaker = "Customer" if message.get("inbound") else "SpotifyCares"
        lines.append(f"{speaker}: {message.get('text', '')}")
    return "\n".join(lines)


def annotation_prompt(case: Dict[str, Any], pass_name: str) -> Tuple[str, str]:
    system = f"""You are an independent escalation annotator. This is pass {pass_name}, {PROMPT_VERSION}.
Annotate only whether the customer case itself requires human escalation. Do not classify intent.
Do not use production routing, target queues, actions, classifier output, canonical gold labels,
or any other annotator output. Treat the complete reconstructed conversation as the evidence.

Human escalation means a specialist or supervisor must be involved rather than routine automated
guidance. High priority alone is not escalation. A private-channel handoff is distinct and may be
yes even when human escalation is no, or vice versa. Use unclear when the conversation does not
support a reliable yes/no decision.

Return only JSON with this schema:
{{
  "escalation_required": "yes|no|unclear",
  "escalation_types": ["allowed type values"],
  "channel_handoff_required": "yes|no|unclear",
  "urgency": "low|normal|high|critical|unclear",
  "evidence_quote": "short verbatim quote",
  "is_ambiguous": true,
  "ambiguity_notes": "short explanation or null",
  "confidence": "high|medium|low",
  "rationale": "concise case-based rationale"
}}
Allowed escalation types: {sorted(ALLOWED_TYPES)}.
Use none only with escalation_required=no. Never include production predictions or routing fields.
"""
    user = f"Conversation ID: {case['manifest']['conversation_id']}\n\nConversation:\n{conversation_text(case['conversation'])}"
    return system, user


def adjudication_prompt(case: Dict[str, Any], annotation_a: Dict[str, Any], annotation_b: Dict[str, Any]) -> Tuple[str, str]:
    system = f"""You are a third independent adjudicator for an AI-assisted escalation annotation, {PROMPT_VERSION}.
Use the original conversation and the two independent annotations below. Do not use production routing,
target queues, actions, classifier output, canonical gold labels, or any other external prediction.
If the evidence supports one decision, select it. If it remains genuinely unresolved, select unclear.
Preserve the distinction between human escalation and private channel handoff.

Return only JSON with the same fields as the annotations plus rationale and adjudication_basis:
escalation_required, escalation_types, channel_handoff_required, urgency, evidence_quote,
is_ambiguous, ambiguity_notes, confidence, rationale, adjudication_basis.
"""
    user = (
        f"Conversation ID: {case['manifest']['conversation_id']}\n\n"
        f"Original conversation:\n{conversation_text(case['conversation'])}\n\n"
        f"Independent annotation A:\n{json.dumps(annotation_a, ensure_ascii=False, sort_keys=True)}\n\n"
        f"Independent annotation B:\n{json.dumps(annotation_b, ensure_ascii=False, sort_keys=True)}"
    )
    return system, user


def resolve_provider(provider: Optional[str], model: Optional[str], api_key: Optional[str]) -> Tuple[str, str, str, str]:
    env = {**dotenv_values(PROJECT_ROOT / ".env"), **os.environ}
    selected = (provider or env.get("LLM_JUDGE_PROVIDER") or ("groq" if env.get("GROQ_API_KEY") else "openrouter")).lower()
    if selected == "groq":
        key = api_key or env.get("GROQ_API_KEY")
        endpoint = "https://api.groq.com/openai/v1/chat/completions"
        chosen_model = model or env.get("GROQ_MODEL") or env.get("LLM_JUDGE_MODEL") or "openai/gpt-oss-120b"
    elif selected == "openrouter":
        key = api_key or env.get("OPENROUTER_API_KEY")
        endpoint = "https://openrouter.ai/api/v1/chat/completions"
        chosen_model = model or env.get("OPENROUTER_MODEL") or env.get("LLM_JUDGE_MODEL") or "openai/gpt-4o-mini"
    else:
        raise ValueError(f"Unsupported provider: {selected}")
    if not key:
        raise ValueError(f"No API key configured for provider {selected}")
    return selected, endpoint, str(key), str(chosen_model)


def call_model(
    system: str,
    user: str,
    provider: str,
    endpoint: str,
    api_key: str,
    model: str,
    temperature: float,
    max_attempts: int = 3,
) -> Dict[str, Any]:
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": temperature,
        "response_format": {"type": "json_object"},
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    if provider == "openrouter":
        headers["HTTP-Referer"] = "https://github.com/spotify-support-agent"
        headers["X-Title"] = "Spotify Escalation AI-Assisted Evaluation"
    last_error: Optional[Exception] = None
    for attempt in range(1, max_attempts + 1):
        request = Request(endpoint, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
        try:
            with urlopen(request, timeout=90) as response:
                body = json.loads(response.read().decode("utf-8"))
            choices = body.get("choices")
            if not choices:
                raise RuntimeError(f"Provider returned no choices: {json.dumps(body, ensure_ascii=False)[:500]}")
            message = choices[0].get("message", {})
            content = message.get("content")
            if content is None:
                raise RuntimeError(f"Provider returned no message content: {json.dumps(body, ensure_ascii=False)[:500]}")
            if isinstance(content, list):
                content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
            try:
                return json.loads(content)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Model returned non-JSON content: {str(content)[:300]}") from exc
        except HTTPError as exc:
            response_body = exc.read().decode("utf-8", errors="replace")[:500]
            last_error = RuntimeError(f"Model HTTP {exc.code}: {response_body}")
        except (URLError, TimeoutError, RuntimeError, ValueError) as exc:
            last_error = exc
        if attempt < max_attempts:
            time.sleep(2 ** (attempt - 1))
    raise RuntimeError(f"Model request failed after {max_attempts} attempts: {last_error}") from last_error


def validate_annotation(data: Dict[str, Any]) -> Dict[str, Any]:
    missing = ANNOTATION_FIELDS - data.keys()
    if missing:
        raise ValueError(f"Missing annotation fields: {sorted(missing)}")
    if data["escalation_required"] not in ALLOWED_DECISIONS:
        raise ValueError("Invalid escalation_required")
    if data["channel_handoff_required"] not in ALLOWED_HANDOFF:
        raise ValueError("Invalid channel_handoff_required")
    if data["urgency"] not in ALLOWED_URGENCY:
        raise ValueError("Invalid urgency")
    if not isinstance(data["escalation_types"], list) or not set(data["escalation_types"]).issubset(ALLOWED_TYPES):
        raise ValueError("Invalid escalation_types")
    if data["escalation_required"] == "no" and data["escalation_types"] != ["none"]:
        raise ValueError("No escalation must use escalation_types=['none']")
    if data["escalation_required"] == "yes" and (not data["escalation_types"] or data["escalation_types"] == ["none"]):
        raise ValueError("Yes escalation requires a specific type")
    if not isinstance(data["is_ambiguous"], bool):
        raise ValueError("is_ambiguous must be boolean")
    if data["confidence"] not in {"high", "medium", "low"}:
        raise ValueError("Invalid confidence")
    if not isinstance(data["evidence_quote"], str) or not data["evidence_quote"].strip():
        raise ValueError("evidence_quote must be non-empty")
    return data


def make_output_record(case: Dict[str, Any], annotation: Dict[str, Any], annotator: str, provider: str, model: str, temperature: float) -> Dict[str, Any]:
    clean = validate_annotation(annotation)
    return {
        "conversation_id": case["manifest"]["conversation_id"],
        "source_provenance": case["manifest"],
        "conversation": case["conversation"],
        "annotator_id": annotator,
        "annotation_timestamp": datetime.now(timezone.utc).isoformat(),
        "provider": provider,
        "model": model,
        "prompt_version": PROMPT_VERSION,
        "temperature": temperature,
        "schema_version": SCHEMA_VERSION,
        **clean,
    }


def independent_agreement(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    fields = ["escalation_required", "escalation_types", "channel_handoff_required", "urgency"]
    return all(a.get(field) == b.get(field) for field in fields)


def resolve_annotation_pair(
    case: Dict[str, Any],
    annotation_a: Dict[str, Any],
    annotation_b: Dict[str, Any],
    adjudicator: Callable[[Dict[str, Any], Dict[str, Any], Dict[str, Any]], Dict[str, Any]],
) -> Tuple[Dict[str, Any], str]:
    """Preserve agreement or invoke a third-party adjudicator for disagreement."""
    if independent_agreement(annotation_a, annotation_b):
        agreed = {field: annotation_a[field] for field in ANNOTATION_FIELDS}
        agreed["rationale"] = annotation_a.get("rationale") or "Both independent annotations agreed on the case-level decision."
        return agreed, "independent_annotations_agree"
    final = adjudicator(case, annotation_a, annotation_b)
    validated = validate_annotation(final)
    if not str(validated.get("rationale", "")).strip():
        raise ValueError("Third adjudicator must provide a rationale")
    return validated, "third_ai_adjudication"


def binary_metrics(rows: List[Dict[str, Any]], label_field: str, prediction_field: str) -> Dict[str, Any]:
    determinate = [r for r in rows if r[label_field] in {"yes", "no"}]
    matrix = {"actual_yes_pred_yes": 0, "actual_yes_pred_no": 0, "actual_no_pred_yes": 0, "actual_no_pred_no": 0}
    for row in determinate:
        actual, predicted = row[label_field], row[prediction_field]
        matrix[f"actual_{actual}_pred_{predicted}"] += 1
    tp = matrix["actual_yes_pred_yes"]
    fp = matrix["actual_no_pred_yes"]
    fn = matrix["actual_yes_pred_no"]
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = (2 * precision * recall / (precision + recall)) if precision is not None and recall is not None and precision + recall else None
    return {"evaluated_count": len(determinate), "excluded_unclear_count": len(rows) - len(determinate), "confusion_matrix": matrix, "precision": precision, "recall": recall, "f1": f1}


def categorical_agreement(rows: List[Dict[str, Any]], label_field: str, prediction_field: str) -> Dict[str, Any]:
    determinate = [r for r in rows if r[label_field] != "unclear"]
    correct = sum(r[label_field] == r[prediction_field] for r in determinate)
    return {"evaluated_count": len(determinate), "excluded_unclear_count": len(rows) - len(determinate), "agreement_count": correct, "agreement_rate": correct / len(determinate) if determinate else None}


def evaluate_routing(adjudicated: List[Dict[str, Any]]) -> Dict[str, Any]:
    rows = []
    for record in adjudicated:
        decision = route_conversation(record["conversation"])
        predicted_urgency = decision.priority if decision.priority in ALLOWED_URGENCY else "unclear"
        rows.append({
            "conversation_id": record["conversation_id"],
            "escalation_required": record["escalation_required"],
            "predicted_escalation_required": "yes" if decision.requires_human_escalation else "no",
            "channel_handoff_required": record["channel_handoff_required"],
            "predicted_channel_handoff_required": "yes" if decision.requires_channel_handoff else "no",
            "urgency": record["urgency"],
            "predicted_urgency": predicted_urgency,
        })
    return {
        "escalation": binary_metrics(rows, "escalation_required", "predicted_escalation_required"),
        "channel_handoff": binary_metrics(rows, "channel_handoff_required", "predicted_channel_handoff_required"),
        "urgency": categorical_agreement(rows, "urgency", "predicted_urgency"),
        "per_record_predictions": rows,
    }


def annotate_pass(cases: List[Dict[str, Any]], annotator: str, provider: str, endpoint: str, api_key: str, model: str, temperature: float, sleep_seconds: float) -> List[Dict[str, Any]]:
    records = []
    for index, case in enumerate(cases):
        system, user = annotation_prompt(case, annotator)
        output = call_model(system, user, provider, endpoint, api_key, model, temperature)
        records.append(make_output_record(case, output, annotator, provider, model, temperature))
        if sleep_seconds and index + 1 < len(cases):
            time.sleep(sleep_seconds)
    return records


def run(args: argparse.Namespace) -> Dict[str, Any]:
    cases = load_cases()
    provider, endpoint, api_key, model = resolve_provider(args.provider, args.model, args.api_key)
    a_records = annotate_pass(cases, "ai_annotator_a", provider, endpoint, api_key, model, args.temperature, args.delay)
    b_records = annotate_pass(cases, "ai_annotator_b", provider, endpoint, api_key, model, args.temperature, args.delay)
    dump_jsonl(ANNOTATOR_A_PATH, a_records)
    dump_jsonl(ANNOTATOR_B_PATH, b_records)
    by_b = {r["conversation_id"]: r for r in b_records}
    adjudications = []
    for a in a_records:
        b = by_b[a["conversation_id"]]
        case = next(c for c in cases if c["manifest"]["conversation_id"] == a["conversation_id"])
        def call_adjudicator(current_case: Dict[str, Any], current_a: Dict[str, Any], current_b: Dict[str, Any]) -> Dict[str, Any]:
            system, user = adjudication_prompt(current_case, current_a, current_b)
            return call_model(system, user, provider, endpoint, api_key, model, args.temperature)

        final, basis = resolve_annotation_pair(case, a, b, call_adjudicator)
        adjudications.append({
            "conversation_id": a["conversation_id"],
            "source_provenance": case["manifest"],
            "conversation": case["conversation"],
            "annotation_a": a,
            "annotation_b": b,
            "final_annotation": final,
            "final_rationale": final.get("rationale"),
            "adjudication_basis": basis,
            "adjudication_timestamp": datetime.now(timezone.utc).isoformat(),
            "provider": provider,
            "model": model,
            "prompt_version": PROMPT_VERSION,
            "temperature": args.temperature,
            "schema_version": SCHEMA_VERSION,
        })
    dump_jsonl(ADJUDICATION_PATH, adjudications)
    final_rows = [{**r["final_annotation"], "conversation_id": r["conversation_id"], "conversation": r["conversation"]} for r in adjudications]
    routing = evaluate_routing(final_rows)
    report = {
        "evaluation_type": "AI-assisted escalation evaluation; not human ground truth",
        "selection_version": SELECTION_VERSION,
        "prompt_version": PROMPT_VERSION,
        "provider": provider,
        "model": model,
        "temperature": args.temperature,
        "record_count": len(cases),
        "annotator_a_count": len(a_records),
        "annotator_b_count": len(b_records),
        "agreement_count": sum(independent_agreement(a, by_b[a["conversation_id"]]) for a in a_records),
        "disagreement_count": sum(not independent_agreement(a, by_b[a["conversation_id"]]) for a in a_records),
        "adjudicated_case_count": sum(r["adjudication_basis"] == "third_ai_adjudication" for r in adjudications),
        "routing_evaluation": routing,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    RESULTS_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the independent AI-assisted escalation evaluation")
    parser.add_argument("--provider", choices=["groq", "openrouter"], default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--delay", type=float, default=0.0)
    args = parser.parse_args()
    report = run(args)
    print(json.dumps({k: report[k] for k in ["provider", "model", "record_count", "agreement_count", "disagreement_count", "adjudicated_case_count", "routing_evaluation"]}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
