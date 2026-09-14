"""Tests for LLM-as-a-judge evaluation harness and human agreement metrics.

Verifies:
1. Strict schema validation for 5-dimension rubric + overall_score + short_reason.
2. Malformed JSON handling and markdown fence extraction.
3. Missing API key handling (raises descriptive error without credentials).
4. Deterministic 30-record subset selection with fixed random seeds.
5. Zero canonical gold annotation / candidate mutation.
6. Zero credential leakage in output dictionaries, representations, or error messages.
7. Mocked OpenRouter HTTP interactions and retry recovery.
8. Agreement metrics computation (Exact Agreement, MAE, Spearman rho, QWK).
"""

from __future__ import annotations

import io
import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch
import urllib.error
import pytest

from src.spotify_agent.llm_judge import (
    DEFAULT_OPENROUTER_MODEL,
    RUBRIC_DIMENSIONS,
    JudgeScore,
    build_judge_prompt,
    evaluate_response,
    parse_judge_response,
    validate_judge_score_dict,
)
from scripts.evaluate_llm_judge import (
    GOLDEN_ANNOTATIONS_PATH,
    GOLDEN_CANDIDATES_PATH,
    load_jsonl,
    select_deterministic_subset,
)
from scripts.compare_judge_human import (
    calculate_exact_agreement,
    calculate_mean_absolute_error,
    calculate_mean_bias,
    calculate_pearson_correlation,
    calculate_quadratic_weighted_kappa,
    calculate_spearman_correlation,
    evaluate_agreement,
)


# 1. Schema Validation Tests
def test_validate_judge_score_dict_valid() -> None:
    """Valid dictionary conforming to rubric schema must pass without error."""
    valid_data = {
        "correctness": 5,
        "groundedness": 5,
        "helpfulness": 4,
        "brand_appropriateness": 5,
        "safety_escalation": 5,
        "overall_score": 5,
        "short_reason": "Accurate, grounded, and concise assistance.",
    }
    validate_judge_score_dict(valid_data)


@pytest.mark.parametrize("missing_field", [
    "correctness",
    "groundedness",
    "helpfulness",
    "brand_appropriateness",
    "safety_escalation",
    "overall_score",
    "short_reason",
])
def test_validate_judge_score_dict_missing_field(missing_field: str) -> None:
    """Missing any rubric field must raise ValueError."""
    data = {
        "correctness": 5,
        "groundedness": 5,
        "helpfulness": 4,
        "brand_appropriateness": 5,
        "safety_escalation": 5,
        "overall_score": 5,
        "short_reason": "Good.",
    }
    del data[missing_field]
    with pytest.raises(ValueError, match="Missing required field"):
        validate_judge_score_dict(data)


@pytest.mark.parametrize("invalid_score", [0, 6, -1, 10, "5", True, None])
def test_validate_judge_score_dict_invalid_scores(invalid_score: object) -> None:
    """Out-of-range or invalid type scores must raise ValueError."""
    data = {
        "correctness": invalid_score,
        "groundedness": 5,
        "helpfulness": 4,
        "brand_appropriateness": 5,
        "safety_escalation": 5,
        "overall_score": 5,
        "short_reason": "Good.",
    }
    with pytest.raises(ValueError):
        validate_judge_score_dict(data)  # type: ignore[arg-type]


def test_validate_judge_score_dict_empty_reason() -> None:
    """Empty reason string must raise ValueError."""
    data = {
        "correctness": 5,
        "groundedness": 5,
        "helpfulness": 4,
        "brand_appropriateness": 5,
        "safety_escalation": 5,
        "overall_score": 5,
        "short_reason": "   ",
    }
    with pytest.raises(ValueError, match="non-empty string"):
        validate_judge_score_dict(data)


# 2. Parsing and Markdown Fence Handling
def test_parse_judge_response_raw_json() -> None:
    """Raw JSON strings must be parsed directly into a JudgeScore instance."""
    raw = json.dumps({
        "correctness": 4,
        "groundedness": 4,
        "helpfulness": 5,
        "brand_appropriateness": 4,
        "safety_escalation": 5,
        "overall_score": 4,
        "short_reason": "Clear steps provided.",
    })
    score = parse_judge_response(raw, model="test-model")
    assert isinstance(score, JudgeScore)
    assert score.correctness == 4
    assert score.groundedness == 4
    assert score.helpfulness == 5
    assert score.brand_appropriateness == 4
    assert score.safety_escalation == 5
    assert score.overall_score == 4
    assert score.short_reason == "Clear steps provided."
    assert score.model == "test-model"


def test_parse_judge_response_with_markdown_fences() -> None:
    """JSON enclosed in markdown code fences ```json ... ``` must be extracted properly."""
    raw = (
        "Here is the evaluation:\n"
        "```json\n"
        "{\n"
        '  "correctness": 5,\n'
        '  "groundedness": 5,\n'
        '  "helpfulness": 5,\n'
        '  "brand_appropriateness": 5,\n'
        '  "safety_escalation": 5,\n'
        '  "overall_score": 5,\n'
        '  "short_reason": "Flawless response."\n'
        "}\n"
        "```\n"
        "Hope this helps!"
    )
    score = parse_judge_response(raw, model="test-model")
    assert score.overall_score == 5
    assert score.short_reason == "Flawless response."


def test_parse_judge_response_malformed_json_raises() -> None:
    """Non-JSON response text must raise ValueError."""
    raw = "I think the response was quite good, maybe a 4 out of 5."
    with pytest.raises(ValueError, match="Failed to parse JSON"):
        parse_judge_response(raw)


# 3. Security and API Key Handling
def test_missing_api_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing OPENROUTER_API_KEY environment variable must raise clear ValueError."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setenv("LLM_JUDGE_PROVIDER", "openrouter")
    with pytest.raises(ValueError, match="OPENROUTER_API_KEY environment variable is not set"):
        evaluate_response("Customer: help", "Agent: hello", provider="openrouter")


def test_no_credential_leakage_in_score_dict() -> None:
    """Serialized JudgeScore dictionary must never contain API keys or auth tokens."""
    score = JudgeScore(
        correctness=5,
        groundedness=5,
        helpfulness=5,
        brand_appropriateness=5,
        safety_escalation=5,
        overall_score=5,
        short_reason="All good.",
        model="test-model",
    )
    data = score.to_dict()
    assert "api_key" not in data
    assert "token" not in data
    assert "authorization" not in data
    assert "Bearer" not in str(data)


# 4. Mocked OpenRouter API Call Execution
def test_evaluate_response_mocked_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mocked OpenRouter API response must correctly parse and return JudgeScore."""
    fake_api_key = "test-sk-or-fake-key-12345"
    monkeypatch.setenv("OPENROUTER_API_KEY", fake_api_key)
    monkeypatch.setenv("LLM_JUDGE_PROVIDER", "openrouter")

    mock_response_payload = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": json.dumps({
                        "correctness": 5,
                        "groundedness": 5,
                        "helpfulness": 4,
                        "brand_appropriateness": 5,
                        "safety_escalation": 5,
                        "overall_score": 5,
                        "short_reason": "Excellent guidance.",
                    }),
                }
            }
        ]
    }

    mock_resp_obj = MagicMock()
    mock_resp_obj.read.return_value = json.dumps(mock_response_payload).encode("utf-8")
    mock_resp_obj.__enter__.return_value = mock_resp_obj

    with patch("urllib.request.urlopen", return_value=mock_resp_obj) as mock_urlopen:
        score = evaluate_response(
            customer_text="Customer: Can't log in",
            agent_response="Agent: Please reset password",
            model="meta-llama/llama-3.3-70b-instruct:free",
        )

        assert score.correctness == 5
        assert score.overall_score == 5
        assert score.short_reason == "Excellent guidance."
        assert mock_urlopen.called

        # Verify headers passed to request
        req = mock_urlopen.call_args[0][0]
        assert req.get_header("Authorization") == f"Bearer {fake_api_key}"


# 5. Deterministic Subset Selection Tests
def test_deterministic_subset_selection() -> None:
    """Deterministic selection must produce identical subsets for the same seed."""
    candidates = load_jsonl(GOLDEN_CANDIDATES_PATH)
    assert len(candidates) == 200

    subset1 = select_deterministic_subset(candidates, sample_size=30, seed=42)
    subset2 = select_deterministic_subset(candidates, sample_size=30, seed=42)
    subset3 = select_deterministic_subset(candidates, sample_size=30, seed=999)

    assert len(subset1) == 30
    assert [c["conversation_id"] for c in subset1] == [c["conversation_id"] for c in subset2]
    assert [c["conversation_id"] for c in subset1] != [c["conversation_id"] for c in subset3]


# 6. Canonical Gold Immutability Test
def test_canonical_gold_data_not_mutated() -> None:
    """Canonical gold files must remain exactly 200 records."""
    annotations = load_jsonl(GOLDEN_ANNOTATIONS_PATH)
    candidates = load_jsonl(GOLDEN_CANDIDATES_PATH)
    assert len(annotations) == 200
    assert len(candidates) == 200


# 7. Agreement Metrics Unit Tests
def test_agreement_metrics_exact_calculations() -> None:
    """Verify exact calculation of MAE, exact agreement, Spearman rho, and QWK."""
    human = [5, 4, 3, 2, 1]
    judge = [5, 4, 3, 2, 1]

    assert calculate_exact_agreement(human, judge) == 100.0
    assert calculate_mean_absolute_error(human, judge) == 0.0
    assert calculate_mean_bias(human, judge) == 0.0
    assert calculate_spearman_correlation(human, judge) == pytest.approx(1.0)
    assert calculate_quadratic_weighted_kappa(human, judge) == pytest.approx(1.0)

    # Offset by 1
    judge_offset = [4, 3, 2, 1, 1]
    assert calculate_mean_absolute_error(human, judge_offset) == pytest.approx(0.8)
    assert calculate_mean_bias(human, judge_offset) == pytest.approx(-0.8)


def test_evaluate_agreement_with_pending_reviewer_template() -> None:
    """Pending reviewer template (with null scores) must return not evaluable without fabricating."""
    template_records = [
        {
            "conversation_id": "test_1",
            "correctness": None,
            "groundedness": None,
            "helpfulness": None,
            "brand_appropriateness": None,
            "safety_escalation": None,
            "overall_score": None,
        }
    ]
    judge_records = [
        {
            "conversation_id": "test_1",
            "correctness": 5,
            "groundedness": 5,
            "helpfulness": 5,
            "brand_appropriateness": 5,
            "safety_escalation": 5,
            "overall_score": 5,
        }
    ]

    report = evaluate_agreement(template_records, judge_records)
    assert report["completed_reviewer_ratings_count"] == 0
    assert report["missing_reviewer_ratings_count"] == 1
    assert report["is_agreement_evaluable"] is False


def test_env_protection_and_gitignore() -> None:
    """Verify that .env is ignored in .gitignore and .env.example contains only placeholders."""
    gitignore_path = Path(__file__).resolve().parent.parent / ".gitignore"
    env_example_path = Path(__file__).resolve().parent.parent / ".env.example"

    assert gitignore_path.exists(), ".gitignore must exist"
    gitignore_text = gitignore_path.read_text(encoding="utf-8")
    assert ".env" in gitignore_text, ".gitignore must ignore .env"

    assert env_example_path.exists(), ".env.example must exist"
    example_text = env_example_path.read_text(encoding="utf-8")
    assert "OPENROUTER_API_KEY=" in example_text
    assert "OPENROUTER_MODEL=" in example_text

    # Verify no real credentials in .env.example
    lines = [line.strip() for line in example_text.splitlines() if line.strip() and not line.startswith("#")]
    for line in lines:
        if line.startswith("OPENROUTER_API_KEY="):
            val = line.split("=", 1)[1].strip()
            assert val == "", ".env.example must have an empty placeholder for OPENROUTER_API_KEY"


def test_missing_api_key_error_message_safety(monkeypatch: pytest.MonkeyPatch) -> None:
    """Error message when key is missing must be clear and contain no secret fragments."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("LLM_JUDGE_PROVIDER", raising=False)
    with pytest.raises(ValueError) as excinfo:
        evaluate_response("Customer: how to reset password?", "Agent: click reset")

    err_msg = str(excinfo.value)
    assert "OPENROUTER_API_KEY environment variable is not set" in err_msg
    assert "sk-" not in err_msg
    assert "Bearer" not in err_msg


def test_missing_groq_api_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """Explicitly requesting Groq provider without GROQ_API_KEY must raise descriptive error."""
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setenv("LLM_JUDGE_PROVIDER", "groq")
    with pytest.raises(ValueError, match="GROQ_API_KEY environment variable is not set"):
        evaluate_response("Customer: help", "Agent: response", provider="groq")


def test_unsupported_provider_raises() -> None:
    """Unsupported provider identifier must raise ValueError."""
    with pytest.raises(ValueError, match="Unsupported LLM_JUDGE_PROVIDER"):
        evaluate_response("Customer: help", "Agent: response", provider="unsupported_provider")


def test_evaluate_response_groq_mocked_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mocked Groq API call must use Groq URL, default model openai/gpt-oss-120b, and parse scores."""
    fake_groq_key = "gsk_test_fake_groq_key_9999"
    monkeypatch.setenv("GROQ_API_KEY", fake_groq_key)
    monkeypatch.setenv("LLM_JUDGE_PROVIDER", "groq")

    mock_response_payload = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": json.dumps({
                        "correctness": 5,
                        "groundedness": 5,
                        "helpfulness": 5,
                        "brand_appropriateness": 5,
                        "safety_escalation": 5,
                        "overall_score": 5,
                        "short_reason": "High quality Groq evaluation.",
                    }),
                }
            }
        ]
    }

    mock_resp_obj = MagicMock()
    mock_resp_obj.read.return_value = json.dumps(mock_response_payload).encode("utf-8")
    mock_resp_obj.__enter__.return_value = mock_resp_obj

    with patch("urllib.request.urlopen", return_value=mock_resp_obj) as mock_urlopen:
        score = evaluate_response(
            customer_text="Customer: Family plan help",
            agent_response="Agent: Check your family invite link",
            provider="groq",
        )

        assert score.correctness == 5
        assert score.overall_score == 5
        assert score.model == "openai/gpt-oss-120b"
        assert score.fallback_used is False
        assert score.short_reason == "High quality Groq evaluation."
        assert mock_urlopen.called

        req = mock_urlopen.call_args[0][0]
        assert req.full_url == "https://api.groq.com/openai/v1/chat/completions"
        assert req.get_header("Authorization") == f"Bearer {fake_groq_key}"


def test_extract_retry_delay_headers() -> None:
    """_extract_retry_delay must parse Retry-After and x-ratelimit-reset-requests properly."""
    from src.spotify_agent.llm_judge import _extract_retry_delay
    import urllib.error

    # Case 1: Retry-After integer
    err1 = urllib.error.HTTPError("http://api", 429, "Too Many Requests", {"Retry-After": "12"}, None)
    assert _extract_retry_delay(err1) == 12.0

    # Case 2: x-ratelimit-reset-requests in seconds
    err2 = urllib.error.HTTPError("http://api", 429, "Too Many Requests", {"x-ratelimit-reset-requests": "6s"}, None)
    assert _extract_retry_delay(err2) == 6.0

    # Case 3: x-ratelimit-reset-requests in milliseconds
    err3 = urllib.error.HTTPError("http://api", 429, "Too Many Requests", {"x-ratelimit-reset-requests": "5000ms"}, None)
    assert _extract_retry_delay(err3) == 5.0

    # Case 4: Default fallback
    err4 = urllib.error.HTTPError("http://api", 429, "Too Many Requests", {}, None)
    assert _extract_retry_delay(err4, default_delay=8.0) == 8.0


def test_evaluate_response_fallback_on_primary_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """When primary model fails on Groq, evaluation must switch to fallback model."""
    fake_groq_key = "gsk_test_fake_groq_key_fallback"
    monkeypatch.setenv("GROQ_API_KEY", fake_groq_key)
    monkeypatch.setenv("LLM_JUDGE_PROVIDER", "groq")

    fallback_payload = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": json.dumps({
                        "correctness": 4,
                        "groundedness": 4,
                        "helpfulness": 4,
                        "brand_appropriateness": 4,
                        "safety_escalation": 5,
                        "overall_score": 4,
                        "short_reason": "Fallback 20B evaluation succeeded.",
                    }),
                }
            }
        ]
    }

    mock_resp_obj = MagicMock()
    mock_resp_obj.read.return_value = json.dumps(fallback_payload).encode("utf-8")
    mock_resp_obj.__enter__.return_value = mock_resp_obj

    # Fail on first 2 calls (primary model max_retries=2), succeed on 3rd call (fallback model)
    mock_429 = urllib.error.HTTPError("http://api", 429, "Rate limit", {"Retry-After": "1"}, None)

    with patch("time.sleep", return_value=None):
        with patch("urllib.request.urlopen", side_effect=[mock_429, mock_429, mock_resp_obj]) as mock_urlopen:
            score = evaluate_response(
                customer_text="Customer: help",
                agent_response="Agent: reply",
                model="openai/gpt-oss-120b",
                fallback_model="openai/gpt-oss-20b",
                provider="groq",
                max_retries=2,
            )

            assert score.model == "openai/gpt-oss-20b"
            assert score.fallback_used is True
            assert score.overall_score == 4
            assert mock_urlopen.call_count == 3


def test_historical_and_complete_judge_artifacts() -> None:
    """Verify integrity of historical 10-record and complete 30-record judge artifacts."""
    hist_path = Path(__file__).resolve().parent.parent / "evaluation" / "llm_judge_results.jsonl"
    complete_path = Path(__file__).resolve().parent.parent / "evaluation" / "llm_judge_results_complete.jsonl"
    reviewer_path = Path(__file__).resolve().parent.parent / "evaluation" / "independent_reviewer_ratings.jsonl"
    agreement_path = Path(__file__).resolve().parent.parent / "evaluation" / "judge_reviewer_agreement.json"

    # Historical file: 10 records preserved byte-for-byte without forced fake metadata
    assert hist_path.exists(), "Historical judge results file must exist"
    hist_records = load_jsonl(hist_path)
    assert len(hist_records) == 10, f"Historical file must contain exactly 10 records, got {len(hist_records)}"
    for r in hist_records:
        validate_judge_score_dict(r)
        assert r.get("provider") == "groq"
        assert r.get("model") == "openai/gpt-oss-120b"

    # Complete file: 30 records with explicit fallback_used=False
    assert complete_path.exists(), "Complete judge results file must exist"
    complete_records = load_jsonl(complete_path)
    assert len(complete_records) == 30, f"Complete file must contain exactly 30 records, got {len(complete_records)}"
    for r in complete_records:
        validate_judge_score_dict(r)
        assert r.get("provider") == "groq"
        assert r.get("model") == "openai/gpt-oss-120b"
        assert r.get("fallback_used") is False
        assert r.get("attempts") == 1

    # Independent reviewer ratings: 30 records
    assert reviewer_path.exists(), "Independent reviewer ratings file must exist"
    reviewer_records = load_jsonl(reviewer_path)
    assert len(reviewer_records) == 30, f"Reviewer ratings must contain exactly 30 records, got {len(reviewer_records)}"

    # Agreement report: exactly 30 matched pairs
    assert agreement_path.exists(), "Agreement report must exist"
    agreement_data = json.loads(agreement_path.read_text(encoding="utf-8"))
    assert agreement_data.get("matched_conversations_count") == 30
    assert agreement_data.get("evaluator_label") == "Independent Reviewer"
