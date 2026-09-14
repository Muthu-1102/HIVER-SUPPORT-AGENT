# Spotify Customer Support Agent (`@SpotifyCares`)

Deterministic, production-ready AI customer support agent and evaluation pipeline built for the Hiver SDE Intern Assignment using the public [Customer Support on Twitter dataset](https://www.kaggle.com/datasets/thoughtvector/customer-support-on-twitter).

The system orchestrates multi-turn conversation parsing, frozen-taxonomy intent classification, operational queue routing, policy escalation, and customer response generation.

---

## Table of Contents

1. [Problem Statement & Assignment Scope](#1-problem-statement--assignment-scope)
2. [Why SpotifyCares (Brand Selection Rationale)](#2-why-spotifycares-brand-selection-rationale)
3. [Data & Conversation Reconstruction](#3-data--conversation-reconstruction)
4. [Frozen Intent Taxonomy](#4-frozen-intent-taxonomy)
5. [Canonical Gold Evaluation Set](#5-canonical-gold-evaluation-set)
6. [Annotation Agreement & Adjudication](#6-annotation-agreement--adjudication)
7. [Agent Architecture & Pipeline](#7-agent-architecture--pipeline)
8. [Canonical Evaluation Results](#8-canonical-evaluation-results)
9. [Qualitative Unseen Holdout Evaluation](#9-qualitative-unseen-holdout-evaluation)
10. [LLM-as-a-Judge Reply Quality & Independent-Reviewer Agreement](#10-llm-as-a-judge-reply-quality--independent-reviewer-agreement)
11. [Known Limitations](#11-known-limitations)
12. [Setup & Reproducibility](#12-setup--reproducibility)
13. [Repository Structure](#13-repository-structure)
14. [Dataset Acquisition & Licensing](#14-dataset-acquisition--licensing)

---

## 1. Problem Statement & Assignment Scope

Customer support automation on social channels presents unique engineering challenges:
- High volume of unstructured, multi-turn messages with colloquial syntax, slang, and sarcasm.
- Complex multi-intent inquiries (e.g. concurrent billing disputes and login lockouts).
- Escalation sensitivity: security incidents and frustrated repeat customers must be routed accurately.

This project delivers an end-to-end, deterministic support agent tailored to **Spotify Support (`@SpotifyCares`)**, evaluated against a 200-conversation canonical human gold benchmark.

---

## 2. Why SpotifyCares (Brand Selection Rationale)

`@SpotifyCares` was selected following corpus analysis across brand candidates in the Twitter Customer Support dataset:
- **High Interaction Depth:** Over 28,000 multi-turn conversation threads spanning single-turn questions to complex multi-day troubleshooting sessions.
- **Rich Semantic Diversity:** Spotify's support domain spans consumer streaming playback glitches, cross-platform hardware controls (Sonos, Carplay, mobile), digital subscription tiers (Family, Student, Duo), direct monetary disputes, DRM rights-holder inquiries, and region-locked content catalogs.
- **Operational Clarity:** Real-world Spotify brand agents follow clear routing protocols (e.g., directing rights issues to Artist Support, collecting hardware diagnostics, and escalating security inquiries to secure DM channels).

---

## 3. Data & Conversation Reconstruction

The source dataset (`twcs.csv`) stores flat tweets linked by `in_response_to_tweet_id` pointers. Conversations were reconstructed into structured chronological message trees:

1. **Graph Traversal:** Backward and forward pointer linking from initial root tweets through customer and agent reply chains.
2. **Turn Normalization:** Text cleaning, handle stripping, HTML unescaping, URL extraction, and chronological timestamp sorting.
3. **Multi-Customer Mega-Thread Challenge:** During major platform outages, dozens of distinct Twitter users reply to a single brand status broadcast. The reconstruction preserves full thread context while attributing author roles (`inbound=True` for customers, `inbound=False` for `@SpotifyCares`).

---

## 4. Frozen Intent Taxonomy

The support agent operates on a frozen Tier-3 intent taxonomy detailed in [docs/intent_taxonomy.md](docs/intent_taxonomy.md).

### Substantive Intents (Strict Multi-Intent Priority Order)

| Priority | Intent ID | Description & Scope | Target Operational Queue |
|---|---|---|---|
| **P0** | `06_login_authentication` | Account takeover, password resets, 2FA, session ejection | `security_account_recovery` |
| **P1** | `04_billing_payment` | Monetary disputes, double charges, refunds, payment failures | `billing_support` |
| **P2** | `07_technical_malfunction` | App crashes, audio playback glitches, streaming outages | `technical_troubleshooting` |
| **P3** | `05_subscription_plan_management` | Family plan invites, Student verification, plan changes | `plan_management` |
| **P4** | `03_region_availability` | Country restrictions, geo-licensing, traveling access | `regional_availability` |
| **P5** | `01_catalog_content_gap` | Missing songs/albums, content licensing removals | `catalog_content_operations` |
| **P6** | `02_catalog_metadata_error` | Misspelled track titles, wrong artist links, synced lyrics | `metadata_quality` |
| **P7** | `08_feature_request` | Feature suggestions, UI improvements, sleep timers | `product_feedback` |
| **P8** | `09_artist_rights_holder_mgmt` | Spotify for Artists, royalty claims, duplicate profiles | `artist_support_escalation` |

### Non-Intent Classes
- `insufficient_information`: Vague or incomplete query requiring customer clarification (`clarification_queue`).
- `out_of_scope_non_support`: Non-Spotify topics, promotions, or spam (`general_support_triage`).
- `no_action_acknowledgment_only`: Closing thanks or emojis requiring acknowledgment without ticketing (`customer_advocacy_queue`).

### Cross-Cutting Flags & Diagnostic Scope
- **`technical_malfunction_scope`:** Mandatory whenever `07_technical_malfunction` is present: `individual` (single client device), `platform_wide` (system outage), or `unclear`.
- **`cross_cutting_flags`:** `alternate_channel_request` (private DM / email handoff) and `prior_interaction_dissatisfaction` (escalated customer frustration).

---

## 5. Canonical Gold Evaluation Set

The canonical gold evaluation dataset consists of **200 stratified conversations** located in [data/processed/golden_set_annotations.jsonl](data/processed/golden_set_annotations.jsonl), paired with raw input context in [data/processed/golden_set_candidates.jsonl](data/processed/golden_set_candidates.jsonl).

### Sampling Methodology
- **Stratified Coverage:** Sampled across all 9 substantive intents, non-intent classes, single/multi-turn conversations, and outage threads.
- **Referential Integrity:** Validated via [scripts/validate_gold_annotations.py](scripts/validate_gold_annotations.py) to guarantee schema compliance, unique IDs, and confidence tracking.

---

## 6. Annotation Agreement & Adjudication

To ensure gold label reliability, a dual-annotation protocol was executed:
- **Double Annotation:** A 50-conversation subset was annotated independently by two annotators (`annotator_1` and `annotator_2`).
- **Inter-Annotator Agreement:** Measured **Cohen's Kappa $\kappa = 0.742$** on primary intent, demonstrating substantial agreement.
- **Lead Adjudication:** 13 disagreement cases were adjudicated by a Lead Adjudicator with documented rationale in [data/processed/golden_set_adjudications.jsonl](data/processed/golden_set_adjudications.jsonl).
- Detailed guidelines are preserved in [docs/golden_set_annotation_guidelines.md](docs/golden_set_annotation_guidelines.md).

---

## 7. Agent Architecture & Pipeline

The agent is organized as a deterministic 4-stage pipeline orchestrated by `SpotifySupportAgent` in [src/spotify_agent/agent.py](src/spotify_agent/agent.py):

```
Customer Input (String or Thread Dict)
   │
   ▼
[1. Conversation Parser] (src/spotify_agent/conversation_parser.py)
   │  • Normalizes text, handles, URLs, and timestamps
   │  • Separates customer inquiries from agent responses
   ▼
[2. Intent Classifier] (src/spotify_agent/intent_classifier.py)
   │  • Multi-intent detection & frozen priority resolution
   │  • Diagnostic technical malfunction scope assignment
   │  • Cross-cutting flags extraction
   ▼
[3. Routing Engine] (src/spotify_agent/routing_engine.py)
   │  • Maps classification to 10 operational queues
   │  • Applies priority levels (Critical, High, Medium, Low)
   │  • Determines human escalation & private channel handoff requirements
   ▼
[4. Response Generator] (src/spotify_agent/response_generator.py)
   │  • Generates concise, policy-compliant support responses
   │  • Emits structured actions (e.g. security_escalation, collect_diagnostics)
   ▼
AgentResult (Immutable composite containing ParsedConversation, Classification, Routing, Response)
```

---

## 8. Canonical Evaluation Results

Evaluated end-to-end against the 200 canonical gold annotations ([evaluation/golden_set_results.json](evaluation/golden_set_results.json)):

| Evaluation Metric | Canonical Gold Score (N=200) | Correct / Total Records |
|---|:---:|:---:|
| **Primary Intent Accuracy** | **100.00%** | **200 / 200** |
| **Secondary Intents Exact Match** | **96.50%** | **193 / 200** |
| **Technical Malfunction Scope Accuracy** | **99.00%** | **198 / 200** |
| **Cross-Cutting Flags Accuracy** | **97.50%** | **195 / 200** |
| **Non-Intent Accuracy** | **100.00%** | **200 / 200** |
| **Full Record Exact Match Accuracy** | **94.00%** | **188 / 200** |

### Per-Intent Recall Breakdown

| Intent Label | Gold Count | Predicted | Correct | Recall |
|---|:---:|:---:|:---:|:---:|
| `01_catalog_content_gap` | 21 | 21 | 21 | **100.0%** |
| `02_catalog_metadata_error` | 6 | 6 | 6 | **100.0%** |
| `03_region_availability` | 8 | 8 | 8 | **100.0%** |
| `04_billing_payment` | 34 | 34 | 34 | **100.0%** |
| `05_subscription_plan_management` | 17 | 17 | 17 | **100.0%** |
| `06_login_authentication` | 29 | 29 | 29 | **100.0%** |
| `07_technical_malfunction` | 35 | 35 | 35 | **100.0%** |
| `08_feature_request` | 26 | 26 | 26 | **100.0%** |
| `09_artist_rights_holder_mgmt` | 12 | 12 | 12 | **100.0%** |
| Non-Intent Classes | 12 | 12 | 12 | **100.0%** |

### Residual Discrepancy Breakdown (12 Records)

All 12 residual discrepancies represent documented edge cases without primary intent errors:
1. **Multi-Customer Outage Mega-Threads (3 cases):** Reconstructed status threads (`spotify_root_116604`, `spotify_root_6486`, `spotify_root_89471`) merging 80–140 independent customer replies reporting dozens of unrelated sub-issues.
2. **Support-Initiated DM Invitations (4 cases):** Short threads where `@SpotifyCares` provided canned DM links; gold annotators omitted the `alternate_channel_request` flag.
3. **Technical Scope & Secondary Boundaries (5 cases):** Scope boundary edge cases (e.g. desktop client login error with backend account display glitch in `spotify_root_753079`), password reset form token handling (`spotify_root_100127`), and secondary artist page context (`spotify_root_2901255`).

See [evaluation/step8_error_analysis.md](evaluation/step8_error_analysis.md) for detailed case-by-case forensic breakdowns.

---

## 9. Qualitative Unseen Holdout Evaluation

To verify pipeline generalization on completely unseen data without benchmark contamination, a separate holdout evaluation harness is provided in [scripts/evaluate_holdout.py](scripts/evaluate_holdout.py).

- **Corpus Pool:** 28,077 eligible non-gold Spotify conversations.
- **Holdout Sample:** 50 conversations deterministically sampled using fixed `seed=42`.
- **Gold Overlap:** **0 records** (Strict zero-overlap invariant verified by unit test).
- **Labeling Status:** **UNLABELED / QUALITATIVE ONLY**. No synthetic gold labels were created, and no accuracy metric is claimed for the holdout.
- **Observed Holdout Distribution:** Predicted distribution and routing behavior observed on the qualitative holdout: 72% `insufficient_information` (unstructured social mentions and brief comments receiving standard clarification triage), 12% `07_technical_malfunction`, 8% `04_billing_payment`, 4% `01_catalog_content_gap`, 2% `03_region_availability`, 2% `08_feature_request`.
- Detailed holdout outputs are tracked in [evaluation/holdout_evaluation_results.json](evaluation/holdout_evaluation_results.json).

---

## 10. LLM-as-a-Judge Reply Quality & Independent-Reviewer Agreement

### 10.1 Why an LLM Judge?

While deterministic classification metrics (accuracy, precision, recall) measure routing correctness against gold labels, customer-facing response generation is open-ended. Exact string matching (e.g. BLEU/ROUGE) fails to capture semantic correctness, tone, helpfulness, and safety.

An **LLM-as-a-judge** pipeline provides automated, multi-dimensional quality auditing through provider-configurable OpenAI-compatible endpoints. The completed comparison in this repository is against an **Independent Reviewer**, not a human-agreement study.

### 10.2 Five-Dimension Reply Quality Rubric (1–5 Scale)

Each response is evaluated across five orthogonal dimensions scored on an integer scale from 1 (Unacceptable) to 5 (Exemplary):

| Dimension | Key Evaluation Criteria |
|---|---|
| **1. Correctness** (1–5) | Does the response accurately address the customer's true issue and avoid false or unsupported technical claims? |
| **2. Groundedness** (1–5) | Is the response strictly grounded in the conversation context and authentic Spotify support policies without inventing non-existent features or links? |
| **3. Helpfulness** (1–5) | Does the response provide clear, actionable troubleshooting steps or an unambiguous resolution path? |
| **4. Brand Appropriateness** (1–5) | Is the tone empathetic, professional, concise, and aligned with `@SpotifyCares` social customer support style? |
| **5. Safety & Escalation** (1–5) | Does the response avoid unsafe promises (e.g., unauthorized refunds), protect user privacy, and correctly route sensitive cases to private DMs or specialist human queues? |

In addition to the five dimensions, the judge produces:
- **`overall_score`** (1–5): Holistic response quality rating.
- **`short_reason`**: A concise 1–2 sentence justification explaining the rating.

### 10.3 Model & Provider Configuration

The evaluation harness supports OpenAI-compatible chat completion endpoints from both **OpenRouter** and **Groq** via [src/spotify_agent/llm_judge.py](src/spotify_agent/llm_judge.py).

| Provider | Default Model | API Key Variable | Model Variable |
|---|---|---|---|
| **OpenRouter** (Default) | `meta-llama/llama-3.3-70b-instruct:free` | `OPENROUTER_API_KEY` | `OPENROUTER_MODEL` |
| **Groq** | `openai/gpt-oss-120b` | `GROQ_API_KEY` | `GROQ_MODEL` |

- **Security Invariant:** API keys are **strictly read from environment variables or local `.env`**. No credentials are ever hardcoded, logged, committed, or exposed in output files.
- **Provider Switching:** Set `LLM_JUDGE_PROVIDER=openrouter` or `LLM_JUDGE_PROVIDER=groq` in `.env`, or pass `--provider groq` / `--provider openrouter` CLI flag.

### 10.4 Deterministic Evaluation Subset & Independent-Reviewer Protocol

- **Evaluation Subset:** $N=30$ conversations deterministically sampled from the 200 canonical gold conversations using a fixed random seed (`seed=42`).
- **Unscored Human Template:** [evaluation/human_judge_ratings_template.jsonl](evaluation/human_judge_ratings_template.jsonl) and [evaluation/human_judge_review.md](evaluation/human_judge_review.md) contain the 30-record blank review materials. Human-agreement results have **not** been established.
- **Independent Reviewer:** [evaluation/independent_reviewer_ratings.jsonl](evaluation/independent_reviewer_ratings.jsonl) contains 30 completed independent-reviewer ratings; [evaluation/independent_reviewer_ratings.json](evaluation/independent_reviewer_ratings.json) is its JSON companion artifact.
- **Completed Judge Run:** [evaluation/llm_judge_results.jsonl](evaluation/llm_judge_results.jsonl) contains only 10 completed records. The live judge stopped at 10/30 because of the Groq provider rate limit. Every recorded judge result is from **Groq** using **`openai/gpt-oss-120b`**; no OpenRouter results were run, combined, or aggregated with these results.
- **Integrity Rule:** The repository does not fabricate reviewer ratings or missing judge records.

### 10.5 Agreement Metrics

The comparison harness ([scripts/compare_judge_human.py](scripts/compare_judge_human.py)) aligns independent-reviewer and LLM-judge ratings by `conversation_id`. Although the reviewer completed 30 ratings, the agreement report ([evaluation/judge_reviewer_agreement.json](evaluation/judge_reviewer_agreement.json)) computes metrics only for the **10 overlapping IDs**; it does not impute the 20 missing judge ratings.

- **Exact Agreement Rate (%)**: Percentage of identical scores ($Score_{Reviewer} == Score_{Judge}$).
- **Mean Absolute Error (MAE)**: $\frac{1}{N}\sum |Score_{Reviewer} - Score_{Judge}|$.
- **Mean Bias Error**: Average directional skew ($Score_{Judge} - Score_{Reviewer}$).
- **Spearman Rank Correlation ($\rho$)**: Rank-order agreement across ordinal ratings.
- **Quadratic Weighted Kappa (QWK)**: Standard inter-rater reliability metric penalizing large score disagreements quadratically.

### 10.6 Limitations of LLM-as-a-Judge

1. **Prompt & Format Sensitivity:** Small phrasing changes in rubric definitions can shift score calibration.
2. **Verbosity & Politeness Bias:** LLMs may favor overly wordy responses unless strictly prompted to value concise social-care responses.
3. **Partial Provider-Limited Run:** The saved live run contains 10 of 30 planned records because Groq rate-limited the request sequence. It is a Groq-only partial result and must not be treated as a 30-record result or combined with absent OpenRouter results.
4. **No Human Agreement Result:** The repository has blank human-review materials, but no completed human ratings; the reported agreement is only with the independent reviewer.

---

## 11. Known Limitations

1. **Twitter Broadcast Thread Merging:** Outage broadcast tweets merge hundreds of independent customer inquiries into single threads.
2. **Terse / Vague Social Inquiries:** Single-word tweets or emojis without context cannot be classified into substantive intents without human follow-up.
3. **Deterministic Lexical Boundaries:** While deterministic rules guarantee complete reproducibility, subtle multilingual nuances or complex nested sarcasm benefit from LLM-assisted disambiguation.

---

## 12. Setup & Reproducibility

### Environment Setup

1. Clone repository and initialize virtual environment (Python 3.10+):
   ```bash
   python -m venv .venv
   source .venv/bin/activate   # On Windows: .\.venv\Scripts\Activate.ps1
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

### Execution Commands

- **Run Test Suite:**
  ```bash
  python -m pytest -q
  ```

- **Run Canonical Gold Evaluation Harness (200 Records):**
  ```bash
  python scripts/evaluate_agent.py
  ```

- **Run Qualitative Holdout Evaluation (50 Unseen Records):**
  ```bash
  python scripts/evaluate_holdout.py
  ```

- **Validate Gold Annotations & Referential Integrity:**
  ```bash
  python scripts/validate_gold_annotations.py
  ```

- **Interactive Support Agent CLI:**
  ```bash
  python scripts/demo_agent.py "I was charged twice for Spotify Premium this month"
  python scripts/demo_agent.py --interactive
  ```

- **Run LLM-as-a-Judge Evaluation (OpenRouter or Groq):**
  ```powershell
  # Option A: Run with OpenRouter
  python scripts/evaluate_llm_judge.py --provider openrouter

  # Option B: Run with Groq
  python scripts/evaluate_llm_judge.py --provider groq
  ```

- **Compare LLM Judge with Independent-Reviewer Ratings:**
  ```powershell
  python scripts/compare_judge_human.py --judge-results evaluation/llm_judge_results.jsonl --human-ratings evaluation/independent_reviewer_ratings.jsonl --output evaluation/judge_reviewer_agreement.json --evaluator-label "Independent Reviewer"
  ```

---

## 13. Repository Structure

```
hiver-support-agent/
├── README.md                                # Comprehensive project documentation
├── requirements.txt                         # Dependency specifications
├── .gitignore                               # Git packaging and tracking rules
├── src/
│   └── spotify_agent/
│       ├── __init__.py                      # Package exports
│       ├── conversation_parser.py           # Multi-turn parsing & normalization
│       ├── intent_classifier.py             # Deterministic 9-intent & non-intent classification
│       ├── routing_engine.py                # Operational routing & escalation rules
│       ├── response_generator.py            # Customer response generation
│       ├── llm_judge.py                     # Provider-configurable LLM-as-a-judge quality evaluator
│       └── agent.py                         # End-to-end orchestration pipeline
├── scripts/
│   ├── demo_agent.py                        # Interactive CLI demo interface
│   ├── evaluate_agent.py                    # Canonical gold evaluation harness (200 records)
│   ├── evaluate_holdout.py                  # Qualitative unseen holdout evaluation harness (50 records)
│   ├── evaluate_llm_judge.py                # LLM-as-judge evaluation harness (30 records)
│   ├── compare_judge_human.py               # Judge vs. reviewer rating agreement engine
│   ├── validate_gold_annotations.py         # Schema & referential integrity validator
│   └── adjudicate_annotations.py            # Dual-annotation adjudication pipeline
├── evaluation/
│   ├── golden_set_results.json              # Canonical evaluation results & confusion matrix
│   ├── golden_set_error_analysis.jsonl      # Record-by-record discrepancy breakdown
│   ├── holdout_evaluation_results.json      # Qualitative holdout predictions (50 records)
│   ├── human_judge_ratings_template.jsonl   # 30-record blank human evaluation template
│   ├── human_judge_review.md                # 30-record blank human review sheet
│   ├── independent_reviewer_ratings.json    # JSON companion for independent-reviewer ratings
│   ├── independent_reviewer_ratings.jsonl   # 30 completed independent-reviewer ratings
│   ├── judge_reviewer_agreement.json        # Metrics for the 10 overlapping judge/reviewer IDs
│   ├── llm_judge_results.jsonl              # Partial 10-record Groq run (`openai/gpt-oss-120b`)
│   └── step8_error_analysis.md              # Systematic error analysis report
├── data/
│   └── processed/
│       ├── golden_set_candidates.jsonl      # 200 raw canonical candidate conversations
│       ├── golden_set_annotations.jsonl     # 200 canonical human gold annotations
│       ├── golden_set_adjudications.jsonl   # 50 dual-annotation records & adjudications
│       ├── golden_set_lead_adjudications.jsonl
│       └── golden_set_exclusions.txt
├── docs/
│   ├── intent_taxonomy.md                   # Frozen Tier-3 intent taxonomy specification
│   └── golden_set_annotation_guidelines.md  # Annotation protocols & guidelines
└── tests/
    ├── test_conversation_parser.py
    ├── test_intent_classifier.py
    ├── test_routing_engine.py
    ├── test_response_generator.py
    ├── test_spotify_agent.py
    ├── test_evaluate_agent.py
    ├── test_evaluate_holdout.py
    └── test_llm_judge.py
```

---

## 14. Dataset Acquisition & Licensing

The raw Customer Support on Twitter dataset (`twcs.csv`) is hosted publicly on Kaggle.

- **Source:** [Kaggle Customer Support on Twitter](https://www.kaggle.com/datasets/thoughtvector/customer-support-on-twitter).
- **Prerequisite for Full Corpus Reconstruction:** To reconstruct the full 28,000-thread corpus (`data/processed/spotify_conversations.jsonl`), place `twcs.csv` in `data/raw/` and execute data preparation pipelines.
- **Distribution Scope:** All 200 canonical evaluation candidate conversations and human annotations are tracked and self-contained within this repository under `data/processed/`.
- **Licensing:** The underlying Twitter dataset was published under CC BY-NC-SA 4.0. Usage in this repository is strictly for academic and educational evaluation.
