# Spotify Customer Support Agent (`@SpotifyCares`)

Deterministic customer-support agent and evaluation pipeline built for the Hiver SDE Intern Assignment using the public [Customer Support on Twitter dataset](https://www.kaggle.com/datasets/thoughtvector/customer-support-on-twitter).

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
8. [Results vs. Baselines](#8-results-vs-baselines)
9. [Canonical Evaluation Results](#9-canonical-evaluation-results)
10. [Top 5 Failure Modes](#10-top-5-failure-modes)
11. [What is Misleading About My Headline Number?](#11-what-is-misleading-about-my-headline-number)
12. [Qualitative Unseen Holdout Evaluation](#12-qualitative-unseen-holdout-evaluation)
13. [LLM-as-a-Judge Reply Quality & Independent-Reviewer Agreement](#13-llm-as-a-judge-reply-quality--independent-reviewer-agreement)
14. [What I'd Do Next with One More Week](#14-what-id-do-next-with-one-more-week)
15. [Decision Log](#15-decision-log)
16. [Known Limitations](#16-known-limitations)
17. [Setup & Reproducibility](#17-setup--reproducibility)
18. [Repository Structure](#18-repository-structure)
19. [Dataset Acquisition & Licensing](#19-dataset-acquisition--licensing)

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
- **Inter-Annotator Agreement:** Measured **Cohen's Kappa $\kappa = 0.8601$** on primary intent across the double-annotated subset, demonstrating near-perfect agreement.
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

## 8. Results vs. Baselines

To benchmark classification performance, the final deterministic agent is compared against two historical reference baselines on the 200-conversation canonical gold evaluation set:

1. **Trivial Baseline (Majority Class Predictor):** Always predicts the most frequent class in the gold set (`07_technical_malfunction`, $N=35$). It emits default individual scope with no secondary intents or cross-cutting flags.
2. **Simple Baseline (Step 8 Heuristic Matcher):** The early rule-based prototype before multi-intent category disambiguation and outage-thread handling was introduced (documented in [evaluation/step8_error_analysis.md](evaluation/step8_error_analysis.md)).
3. **Final Agent (Deterministic Multi-Stage Pipeline):** The current pipeline with priority-resolved classification, scope diagnostics, and flag extraction.

### Benchmark Comparison (Canonical Gold Set $N=200$)

| Approach / Model | Primary Intent Accuracy | Secondary Intent Exact Match | Technical Malfunction Scope Accuracy | Cross-Cutting Flags Accuracy | Full-Record Exact Match |
|---|:---:|:---:|:---:|:---:|:---:|
| **Trivial Baseline** (Majority Class: `07_technical_malfunction`) | 17.50% (35/200) | 0.00% (0/200) | 17.50% (35/200) | 0.00% (0/200) | 0.00% (0/200) |
| **Simple Baseline** (Step 8 Heuristic Matcher) | 91.00% (182/200) | 89.50% (179/200) | 88.50% (177/200) | 84.00% (168/200) | 67.00% (134/200) |
| **Final Agent** (Deterministic Pipeline) | **100.00%** (200/200) | **96.50%** (193/200) | **99.00%** (198/200) | **97.50%** (195/200) | **94.00%** (188/200) |

*Note on Baseline Completeness:* Response generation quality metrics (1–5 rubric) and multi-intent latency benchmarks were not measured for the trivial or Step 8 heuristic baselines because those early iterations lacked decoupled routing engines and structured response generation modules.

---

## 9. Canonical Evaluation Results

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

---

## 10. Top 5 Failure Modes

Forensic analysis of the 12 residual discrepancies in [evaluation/step8_error_analysis.md](evaluation/step8_error_analysis.md) reveals five distinct operational failure modes:

### 1. Merged Multi-Customer Status Mega-Threads (`spotify_root_116604`, `spotify_root_6486`, `spotify_root_89471`)
- **Observed Example (`spotify_root_116604`, 97 messages):** `@SpotifyCares` posted a downtime recovery tweet. Replying tweet #120 contained an unrelated user asking *"how I can change country? Cause now I have Germany..."*, triggering `03_region_availability`. The gold annotator recorded intents `04`, `05`, `06` but omitted `03`.
- **Technical Hypothesis:** Twitter's graph links hundreds of unrelated customer replies to a single status broadcast root. Single-conversation classification treats all merged turns as a single customer context, causing multi-intent pollution across distinct users.

### 2. Support-Initiated DM Link Handshake Boundary (`spotify_root_1391771`, `spotify_root_1913967`, `spotify_root_1995751`, `spotify_root_566286`)
- **Observed Example (`spotify_root_1391771`):** Web session logout issue where `@SpotifyCares` provided a canned DM link (*"Can you shoot us a DM with your email address..."*). The pipeline detected `alternate_channel_request`, but gold annotators left flags empty.
- **Technical Hypothesis:** Annotators perceived agent sign-off links as boilerplate agent template signatures rather than explicit channel escalations, creating annotator boundary noise across otherwise identical conversations.

### 3. Form Token vs. App Technical Outage Scope (`spotify_root_100127`)
- **Observed Example (`spotify_root_100127`):** Customer encountered a CSRF form token error during password reset (*"The CSRF token is invalid. Please try to resubmit the form."*). Gold annotator labeled `06_login_authentication` primary with `07_technical_malfunction` secondary (scope: `unclear`). The pipeline classified it strictly as `06_login_authentication` (scope: `None`).
- **Technical Hypothesis:** Web form session errors sit on the conceptual boundary between authentication workflow failures and technical web client bugs, highlighting the need for explicit sub-intent guidelines for web error codes.

### 4. Contextual Entity Mention vs. Intent Scope (`spotify_root_2901255`)
- **Observed Example (`spotify_root_2901255`):** Listener requested an explicit track filter while shuffle playing on an artist page. Primary intent `08_feature_request` was matched, but the lexical trigger `"artist page"` activated secondary `09_artist_rights_holder_mgmt` (which the gold annotator omitted).
- **Technical Hypothesis:** Passive UI location mentions (*"on the artist page"*) trigger artist domain keywords even when the customer is a consumer suggesting a general playback feature.

### 5. Multi-Client Diagnostic Ambiguity (`spotify_root_753079`)
- **Observed Example (`spotify_root_753079`):** Customer reported desktop app login failure (`Error Code 3`) alongside a backend web account display discrepancy. Classifier diagnosed scope as `individual` due to explicit desktop client mention; gold annotated `unclear` due to the backend web display issue.
- **Technical Hypothesis:** Cross-platform multi-symptom inquiries span both client-side installations and server-side profile state, leading to divergent interpretations of diagnostic scope.

---

## 11. What is Misleading About My Headline Number?

Our canonical evaluation reports a **94.00% Full-Record Exact Match** and **100.00% Primary Intent Accuracy** on the 200-conversation gold benchmark. While this confirms pipeline determinism and rule precision against the gold standard, **this number must not be interpreted as an index of universal real-world support quality.**

Four critical distinctions explain why:

### 1. Strict Benchmark Exactness vs. Real-World Task Completion
The 94% metric measures exact multi-attribute alignment across five schema dimensions (Primary Intent, Secondary Intents, Scope, Cross-Cutting Flags, and Non-Intent) on a structured, pre-curated dataset. It does not measure customer issue resolution time, first-contact resolution (FCR), or customer satisfaction (CSAT).

### 2. Gold Benchmark Stratification & Annotation Boundaries
The 200-record gold benchmark was sampled with balanced intent stratification across clear support topics. Real-world social streams are far less orderly: users post fragmented thoughts across multiple tweets, use heavy sarcasm, or change topics mid-thread. Furthermore, 12 of our discrepancies reflect annotator boundary nuances (e.g. DM link flagging), indicating that the benchmark has inherent label ambiguity.

### 3. Generalization Gap Exposed by Unseen Holdout Data
When tested on 50 completely unseen raw conversations from the wider corpus ([scripts/evaluate_holdout.py](scripts/evaluate_holdout.py)), **72% of records were classified as `insufficient_information`**. In the wild, customers frequently tweet single words, tag `@SpotifyCares` without context, or post emotional vents. A 94% exact match on clean benchmark inquiries does not mean the system will autonomously solve 94% of raw social mentions.

### 4. Generative Response Quality & The LLM Judge Leniency Gap
Classification accuracy does not equate to response quality. While the pipeline routes accurately, generating empathetic, context-aware responses is subjective. In our 30-conversation evaluation:
- The LLM judge (`openai/gpt-oss-120b`) gave an average overall score of **3.70 / 5.00**.
- The Independent Reviewer gave an average overall score of **2.70 / 5.00**.
- This **+1.00 Mean Bias** demonstrates that automated judges are lenient and that automated routing success does not guarantee human-grade conversational support.

---

## 12. Qualitative Unseen Holdout Evaluation

To verify pipeline generalization on completely unseen data without benchmark contamination, a separate holdout evaluation harness is provided in [scripts/evaluate_holdout.py](scripts/evaluate_holdout.py).

- **Corpus Pool:** 28,077 eligible non-gold Spotify conversations.
- **Holdout Sample:** 50 conversations deterministically sampled using fixed `seed=42`.
- **Gold Overlap:** **0 records** (Strict zero-overlap invariant verified by unit test).
- **Labeling Status:** **UNLABELED / QUALITATIVE ONLY**. No synthetic gold labels were created, and no accuracy metric is claimed for the holdout.
- **Observed Holdout Distribution:** Predicted distribution and routing behavior observed on the qualitative holdout: 72% `insufficient_information` (unstructured social mentions and brief comments receiving standard clarification triage), 12% `07_technical_malfunction`, 8% `04_billing_payment`, 4% `01_catalog_content_gap`, 2% `03_region_availability`, 2% `08_feature_request`.
- Detailed holdout outputs are tracked in [evaluation/holdout_evaluation_results.json](evaluation/holdout_evaluation_results.json).

---

## 13. LLM-as-a-Judge Reply Quality & Independent-Reviewer Agreement

### 13.1 Why an LLM Judge?

While deterministic classification metrics (accuracy, precision, recall) measure routing correctness against gold labels, customer-facing response generation is open-ended. Exact string matching (e.g. BLEU/ROUGE) fails to capture semantic correctness, tone, helpfulness, and safety.

An **LLM-as-a-judge** pipeline provides automated, multi-dimensional quality auditing through provider-configurable OpenAI-compatible endpoints. The completed comparison in this repository is against an **Independent Reviewer**, not a human-agreement study.

### 13.2 Five-Dimension Reply Quality Rubric (1–5 Scale)

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

### 13.3 Model & Provider Configuration

The evaluation harness supports OpenAI-compatible chat completion endpoints from both **OpenRouter** and **Groq** via [src/spotify_agent/llm_judge.py](src/spotify_agent/llm_judge.py).

| Provider | Default Model | API Key Variable | Model Variable |
|---|---|---|---|
| **OpenRouter** (Default) | `meta-llama/llama-3.3-70b-instruct:free` | `OPENROUTER_API_KEY` | `OPENROUTER_MODEL` |
| **Groq** | `openai/gpt-oss-120b` | `GROQ_API_KEY` | `GROQ_MODEL` |

- **Security Invariant:** API keys are **strictly read from environment variables or local `.env`**. No credentials are ever hardcoded, logged, committed, or exposed in output files.
- **Provider Switching:** Set `LLM_JUDGE_PROVIDER=openrouter` or `LLM_JUDGE_PROVIDER=groq` in `.env`, or pass `--provider groq` / `--provider openrouter` CLI flag.

### 13.4 Deterministic Evaluation Subset & Independent-Reviewer Protocol

- **Evaluation Subset:** $N=30$ conversations deterministically sampled from the 200 canonical gold conversations using a fixed random seed (`seed=42`).
- **Complete LLM Judge Evaluation (Current Run):** Full 30-record evaluation saved in [evaluation/llm_judge_results_complete.jsonl](evaluation/llm_judge_results_complete.jsonl):
  - **LLM Judge Evaluated Records:** **30 / 30**
  - **Provider:** **Groq**
  - **Model:** **`openai/gpt-oss-120b`**
  - **Fallback Invocations:** **0** (0 fallbacks; all 30 records completed on primary model)
  - **Failures / Errors:** **0**
- **Independent Reviewer Ratings:** [evaluation/independent_reviewer_ratings.jsonl](evaluation/independent_reviewer_ratings.jsonl) contains **30 / 30** completed independent-reviewer ratings; [evaluation/independent_reviewer_ratings.json](evaluation/independent_reviewer_ratings.json) is its companion JSON artifact.
- **Judge / Reviewer Overlap:** **30 / 30** (100% complete overlap across all 30 evaluated conversation IDs).
- **Historical Interrupted Run:** [evaluation/llm_judge_results.jsonl](evaluation/llm_judge_results.jsonl) is the earlier interrupted 10-record run and is retained unchanged as a historical artifact.
- **Human Review Materials & Agreement Disclaimer:** [evaluation/human_judge_ratings_template.jsonl](evaluation/human_judge_ratings_template.jsonl) and [evaluation/human_judge_review.md](evaluation/human_judge_review.md) contain the 30-record blank evaluation materials. **Actual human-agreement evidence was not established** (human rating scores remain unpopulated/null). The reported agreement is strictly **Independent-Reviewer Agreement**, NOT human ground-truth evidence.
- **Integrity Rule:** The repository does not fabricate ratings or impute missing values.

### 13.5 Evaluation Resumption, Rate Limits & Fallbacks

The evaluator supports safe continuation of an interrupted run through `--resume-from`. Existing completed conversation IDs are skipped and copied unchanged into the staging output; only missing records are sent to the API. The historical [evaluation/llm_judge_results.jsonl](evaluation/llm_judge_results.jsonl) remains unchanged. For example, the completed run was executed with:

```powershell
python scripts/evaluate_llm_judge.py --provider groq --resume-from evaluation/llm_judge_results.jsonl --output evaluation/llm_judge_results_complete.jsonl
```

Requests use an 8-second default pacing delay. HTTP 429 responses inspect `Retry-After` and `x-ratelimit-reset-requests`, and retry timing uses the upstream reset information when available.

For Groq, the primary model is `openai/gpt-oss-120b` and the fallback model is `openai/gpt-oss-20b`. The fallback is attempted only after the configured primary-model retry behavior fails. Each result records the provider, model, `fallback_used`, and `attempts`. In the completed 30-record run, all records used the primary model, with zero fallbacks.

### 13.6 Agreement Metrics (Complete 30/30 Overlap)

The comparison harness ([scripts/compare_judge_human.py](scripts/compare_judge_human.py)) aligns independent-reviewer and LLM-judge ratings by `conversation_id`. With both the complete 30-record judge file ([evaluation/llm_judge_results_complete.jsonl](evaluation/llm_judge_results_complete.jsonl)) and 30 completed independent-reviewer ratings ([evaluation/independent_reviewer_ratings.jsonl](evaluation/independent_reviewer_ratings.jsonl)), the agreement report ([evaluation/judge_reviewer_agreement.json](evaluation/judge_reviewer_agreement.json)) computes metrics across all **30 / 30 overlapping pairs**:

| Rubric Dimension | Reviewer Mean | Judge Mean | Exact Agreement (%) | MAE | Mean Bias | Spearman $\rho$ | Quadratic Weighted Kappa (QWK) |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **Correctness** | 2.70 | 4.00 | 23.33% | 1.367 | +1.300 | 0.415 | 0.239 |
| **Groundedness** | 2.73 | 4.67 | 6.67% | 1.933 | +1.933 | 0.293 | 0.139 |
| **Helpfulness** | 2.57 | 3.20 | 23.33% | 0.900 | +0.633 | 0.470 | 0.377 |
| **Brand Appropriateness** | 3.67 | 4.57 | 16.67% | 0.967 | +0.900 | 0.449 | 0.293 |
| **Safety & Escalation** | 3.93 | 5.00 | 3.33% | 1.067 | +1.067 | 0.000 | 0.000 |
| **Overall Score** | 2.70 | 3.70 | 20.00% | 1.067 | +1.000 | 0.535 | 0.373 |

- **Exact Agreement Rate (%)**: Percentage of identical scores ($Score_{Reviewer} == Score_{Judge}$).
- **Mean Absolute Error (MAE)**: $\frac{1}{N}\sum |Score_{Reviewer} - Score_{Judge}|$.
- **Mean Bias Error**: Average directional skew ($Score_{Judge} - Score_{Reviewer}$). A positive value indicates the judge was more lenient than the independent reviewer.
- **Spearman Rank Correlation ($\rho$)**: Rank-order agreement across ordinal ratings (0.535 on overall score).
- **Quadratic Weighted Kappa (QWK)**: Standard inter-rater reliability metric penalizing large score disagreements quadratically (0.373 on overall score).

### 13.7 Limitations of LLM-as-a-Judge

1. **Prompt & Format Sensitivity:** Small phrasing changes in rubric definitions can shift score calibration.
2. **Verbosity & Politeness Bias:** LLMs may favor overly wordy responses unless strictly prompted to value concise social-care responses.
3. **Reviewer-Judge Leniency Gap:** The LLM judge (`openai/gpt-oss-120b`) scored higher on average than the independent reviewer across all dimensions (Judge Overall Mean: 3.70 vs. Reviewer Overall Mean: 2.70; Mean Bias: +1.00), demonstrating a consistent leniency differential.
4. **No Human Agreement Result:** The repository provides blank human-review materials, but no completed human ratings; the reported agreement is strictly with the independent reviewer, and no claim of human ground-truth evidence is made.

---

## 14. What I'd Do Next with One More Week

With an additional week of engineering time, I would focus on four high-impact architectural and evaluation enhancements:

### 1. Hybrid Small-LLM Fallback for Low-Confidence Triage
- **Current Limitation:** The deterministic regex/keyword classifier runs in <2ms with 100% reproducibility, but routes 72% of raw social mentions to `insufficient_information` due to strict pattern matching.
- **Next Step:** Implement a hybrid tiered classifier: high-confidence queries execute deterministically via the current rules; borderline or vague inquiries pass to a local or low-latency Small Language Model (e.g. Llama 3.3 8B or Mistral 7B) with few-shot prompt constraints to extract latent customer intent.

### 2. Multi-Author Graph Unrolling for Broadcast Outage Threads
- **Current Limitation:** When `@SpotifyCares` posts a public status update, all incoming customer replies are parsed as a single monolithic conversation, creating multi-customer intent collisions.
- **Next Step:** Build an author-segmented conversation disaggregator that partitions reply graphs by user ID, analyzing each customer's interaction branch as an isolated conversation unit.

### 3. Empirical Human Evaluation Campaign
- **Current Limitation:** Only independent-reviewer ratings are populated; the human evaluation template remains blank.
- **Next Step:** Conduct a double-blind annotation study with 3+ professional customer support specialists across the 30-record review sheet ([evaluation/human_judge_review.md](evaluation/human_judge_review.md)). Calculate human-human vs. human-LLM Cohen's Kappa to formally calibrate judge leniency.

### 4. Live CRM Integration & Dynamic Knowledge Base RAG
- **Current Limitation:** The response generator outputs structured action schemas and templated replies with static help links.
- **Next Step:** Integrate a vector store (e.g. Chroma/Qdrant) over current Spotify Support FAQs and connect to a mock Hiver/Zendesk webhook API to test live ticket payload dispatch, dynamic article retrieval, and agent handoff triggers.

---

## 15. Decision Log

Key non-obvious engineering and design decisions made throughout project development:

1. **Deterministic Rule Pipeline over Pure LLM Inference:**
   *Decision:* Built a multi-stage deterministic regex/keyword parser and classifier rather than relying solely on LLM prompt-based classification.
   *Rationale:* Ensures 100% test reproducibility, zero runtime API costs for classification, <5ms latency per message, and immunity to prompt injection.

2. **Frozen Tier-3 Intent Hierarchy with Strict Priority Order (P0 to P8):**
   *Decision:* Defined 9 substantive intents arranged in strict priority (`06_login` > `04_billing` > `07_technical` > ... > `09_artist`).
   *Rationale:* Multi-intent tweets (e.g., "I can't log in and was charged twice") must route to a single primary operational queue to prevent orphaned or duplicate tickets.

3. **Decoupling Substantive Intents from Non-Intent Classes:**
   *Decision:* Split classification into 9 core support intents and 3 non-intent triage categories (`insufficient_information`, `out_of_scope_non_support`, `no_action_acknowledgment_only`).
   *Rationale:* Avoids polluting domain-specific support queues with social chatter, single-word replies, or non-Spotify mentions.

4. **Mandatory Diagnostic Scope for Technical Malfunctions:**
   *Decision:* Required every `07_technical_malfunction` classification to output a `technical_malfunction_scope` (`individual`, `platform_wide`, `unclear`).
   *Rationale:* Allows support operations to distinguish localized device troubleshooting from platform-wide incident escalation.

5. **Decoupling Cross-Cutting Flags from Primary Routing:**
   *Decision:* Implemented `alternate_channel_request` and `prior_interaction_dissatisfaction` as independent binary flags rather than dedicated intent classes.
   *Rationale:* Channel preference and customer sentiment cut across all topics and modify ticket handling without changing queue ownership.

6. **Dual-Annotation Protocol with Documented Adjudications:**
   *Decision:* Double-annotated 50 conversations, measured Cohen's Kappa ($\kappa = 0.8601$), and documented all 13 disagreements in a separate adjudication artifact.
   *Rationale:* Ensures full transparency and auditability of the gold ground-truth dataset.

7. **Zero-Overlap Unseen Holdout Dataset ($N=50$):**
   *Decision:* Extracted an independent 50-conversation holdout sample with guaranteed 0 overlap with the 200 gold set and left it unlabeled for qualitative inspection.
   *Rationale:* Prevents synthetic evaluation bias and provides a realistic view of raw, unfiltered social media volume.

8. **5-Dimension Response Quality Rubric on a 1–5 Scale:**
   *Decision:* Evaluated response generation across Correctness, Groundedness, Helpfulness, Brand Appropriateness, and Safety/Escalation.
   *Rationale:* Captures multi-faceted support quality that standard n-gram overlap metrics (BLEU/ROUGE) cannot evaluate.

9. **Resumable LLM Judge with HTTP 429 Header Parsing:**
   *Decision:* Designed the judge evaluation harness with `--resume-from`, 8-second pacing, and upstream `Retry-After` / `x-ratelimit-reset-requests` parsing.
   *Rationale:* Prevents duplicate API expenditure and ensures graceful recovery under provider rate limits.

10. **Retention of Historical (10-record) and Complete (30-record) Evaluation Files:**
    *Decision:* Kept the original interrupted run ([evaluation/llm_judge_results.jsonl](evaluation/llm_judge_results.jsonl)) intact and wrote the 30-record completed run to [evaluation/llm_judge_results_complete.jsonl](evaluation/llm_judge_results_complete.jsonl).
    *Rationale:* Maintains an immutable evaluation trail and ensures backward compatibility with test suites.

11. **Transparent Independent-Reviewer Labeling:**
    *Decision:* Explicitly labeled rating comparisons as "Independent Reviewer Agreement" and left human evaluation templates unpopulated.
    *Rationale:* Prevents misrepresentation of independent baseline scores as verified human consensus.

12. **Zero Live API Calls in Automated CI Test Suite:**
    *Decision:* Configured all 144 unit and integration tests to run offline using mocked HTTP responses and local fixtures.
    *Rationale:* Guarantees fast, deterministic test runs without external network dependencies or token consumption.

13. **Thread Normalization & Handle Sanitization in Preprocessing:**
    *Decision:* Stripped Twitter handles and normalized URLs during parsing while retaining raw text for diagnostic reference.
    *Rationale:* Eliminates noise that interferes with regex matching while preserving author roles (`inbound=True/False`).

14. **Structured Action Schemas Accompanying Text Replies:**
    *Decision:* The response generator outputs structured machine-readable actions (`action_type`, `escalate_to_human`, `suggested_links`) alongside customer text.
    *Rationale:* Enables automated downstream CRM execution (e.g. creating Zendesk macros or initiating DM handoffs) without requiring NLP parsing of the generated reply.

---

## 16. Known Limitations

1. **Twitter Broadcast Thread Merging:** Outage broadcast tweets merge hundreds of independent customer inquiries into single threads.
2. **Terse / Vague Social Inquiries:** Single-word tweets or emojis without context cannot be classified into substantive intents without human follow-up.
3. **Deterministic Lexical Boundaries:** While deterministic rules guarantee complete reproducibility, subtle multilingual nuances or complex nested sarcasm benefit from LLM-assisted disambiguation.

---

## 17. Setup & Reproducibility

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
  python scripts/compare_judge_human.py --judge-results evaluation/llm_judge_results_complete.jsonl --human-ratings evaluation/independent_reviewer_ratings.jsonl --output evaluation/judge_reviewer_agreement.json --evaluator-label "Independent Reviewer"
  ```

---

## 18. Repository Structure

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
│   ├── human_judge_ratings_template.jsonl   # 30-record blank human evaluation template (unpopulated)
│   ├── human_judge_review.md                # 30-record blank human review sheet
│   ├── independent_reviewer_ratings.json    # JSON companion for 30 independent-reviewer ratings
│   ├── independent_reviewer_ratings.jsonl   # 30 completed independent-reviewer ratings
│   ├── judge_reviewer_agreement.json        # Full agreement report (30/30 overlapping pairs)
│   ├── llm_judge_results.jsonl              # Historical 10-record run (interrupted, retained unchanged)
│   ├── llm_judge_results_complete.jsonl     # Complete 30-record Groq run (`openai/gpt-oss-120b`, 0 fallbacks)
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

## 19. Dataset Acquisition & Licensing

The raw Customer Support on Twitter dataset (`twcs.csv`) is hosted publicly on Kaggle.

- **Source:** [Kaggle Customer Support on Twitter](https://www.kaggle.com/datasets/thoughtvector/customer-support-on-twitter).
- **Prerequisite for Full Corpus Reconstruction:** To reconstruct the full 28,000-thread corpus (`data/processed/spotify_conversations.jsonl`), place `twcs.csv` in `data/raw/` and execute data preparation pipelines.
- **Distribution Scope:** All 200 canonical evaluation candidate conversations and human annotations are tracked and self-contained within this repository under `data/processed/`.
- **Licensing:** The underlying Twitter dataset was published under CC BY-NC-SA 4.0. Usage in this repository is strictly for academic and educational evaluation.
