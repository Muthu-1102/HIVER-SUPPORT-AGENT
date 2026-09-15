import json
from pathlib import Path

from scripts.evaluate_escalation_ai import (
    ANNOTATION_FIELDS,
    binary_metrics,
    independent_agreement,
    load_cases,
    resolve_annotation_pair,
    validate_annotation,
)


def test_escalation_workspace_has_40_cases_and_no_gold_overlap():
    cases = load_cases()
    assert len(cases) == 40
    gold_ids = {json.loads(line)["conversation_id"] for line in Path("data/processed/golden_set_annotations.jsonl").read_text(encoding="utf-8-sig").splitlines() if line.strip()}
    assert not ({case["manifest"]["conversation_id"] for case in cases} & gold_ids)


def test_blank_annotation_workspaces_are_complete_and_unlabeled():
    expected_ids = [case["manifest"]["conversation_id"] for case in load_cases()]
    for filename in [
        "data/processed/escalation_annotator_1_workspace.jsonl",
        "data/processed/escalation_annotator_2_workspace.jsonl",
    ]:
        records = [json.loads(line) for line in Path(filename).read_text(encoding="utf-8-sig").splitlines() if line.strip()]
        assert [record["conversation_id"] for record in records] == expected_ids
        assert all(record["escalation_required"] is None for record in records)


def test_annotation_schema_validation():
    record = {
        "escalation_required": "no",
        "escalation_types": ["none"],
        "channel_handoff_required": "no",
        "urgency": "normal",
        "evidence_quote": "No escalation evidence.",
        "is_ambiguous": False,
        "ambiguity_notes": None,
        "confidence": "high",
    }
    assert set(validate_annotation(record)) == ANNOTATION_FIELDS


def test_annotation_passes_are_independent_records():
    a = {"escalation_required": "yes", "escalation_types": ["other"], "channel_handoff_required": "no", "urgency": "high"}
    b = dict(a)
    assert independent_agreement(a, b)
    b["escalation_required"] = "no"
    assert not independent_agreement(a, b)


def test_adjudication_preserves_agreement_without_calling_third_annotator():
    case = {"manifest": {"conversation_id": "case-1"}}
    a = {"escalation_required": "no", "escalation_types": ["none"], "channel_handoff_required": "no", "urgency": "normal", "evidence_quote": "none", "is_ambiguous": False, "ambiguity_notes": None, "confidence": "high", "rationale": "No case-level escalation evidence."}
    calls = []
    final, basis = resolve_annotation_pair(case, a, dict(a), lambda *_: calls.append(True))
    assert basis == "independent_annotations_agree"
    assert all(final[field] == a[field] for field in ANNOTATION_FIELDS)
    assert final["rationale"] == a["rationale"]
    assert calls == []


def test_adjudication_invokes_third_annotator_only_on_disagreement():
    case = {"manifest": {"conversation_id": "case-1"}}
    a = {"escalation_required": "yes", "escalation_types": ["other"], "channel_handoff_required": "no", "urgency": "high", "evidence_quote": "issue", "is_ambiguous": False, "ambiguity_notes": None, "confidence": "medium", "rationale": "The case needs specialist review."}
    b = dict(a)
    b["escalation_required"] = "no"
    b["escalation_types"] = ["none"]
    calls = []
    final, basis = resolve_annotation_pair(case, a, b, lambda *_: (calls.append(True) or {**a, "escalation_required": "unclear", "escalation_types": ["other"], "rationale": "The evidence remains ambiguous."}))
    assert basis == "third_ai_adjudication"
    assert final["escalation_required"] == "unclear"
    assert calls == [True]


def test_zero_positive_metrics_are_none_not_fabricated():
    rows = [
        {"escalation_required": "no", "predicted_escalation_required": "no"},
        {"escalation_required": "unclear", "predicted_escalation_required": "yes"},
    ]
    metrics = binary_metrics(rows, "escalation_required", "predicted_escalation_required")
    assert metrics["evaluated_count"] == 1
    assert metrics["confusion_matrix"]["actual_no_pred_no"] == 1
    assert metrics["precision"] is None
    assert metrics["recall"] is None
    assert metrics["f1"] is None
