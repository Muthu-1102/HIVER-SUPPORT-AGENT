# Hiver Spotify Customer Support Agent

Deterministic, production-ready AI customer-support agent pipeline built for the Hiver SDE Intern Assignment using the Customer Support on Twitter dataset.

The system orchestrates multi-turn conversation parsing, frozen taxonomy intent classification, operational routing, and policy-compliant customer response generation.

---

## Project Structure

```
hiver-support-agent/
├── README.md
├── requirements.txt
├── src/
│   └── spotify_agent/
│       ├── conversation_parser.py   # Multi-turn aggregation & normalization
│       ├── intent_classifier.py     # Deterministic 9-intent & non-intent classifier
│       ├── routing_engine.py        # Operational queue routing & escalation rules
│       ├── response_generator.py    # Policy-compliant response generator
│       └── agent.py                 # End-to-end orchestration pipeline
├── scripts/
│   ├── demo_agent.py                # Interactive & CLI demonstration interface
│   ├── evaluate_agent.py            # Golden set evaluation harness (200 records)
│   ├── validate_gold_annotations.py # Gold annotation schema & integrity validator
│   └── adjudicate_annotations.py    # Lead adjudicator agreement pipeline
├── evaluation/
│   ├── golden_set_results.json      # Full evaluation results & confusion matrix
│   └── step8_error_analysis.md      # Systematic error analysis report
├── data/
│   └── processed/
│       ├── golden_set_candidates.jsonl   # 200 raw candidate conversations
│       └── golden_set_annotations.jsonl  # 200 canonical human gold annotations
├── docs/
│   ├── intent_taxonomy.md                # Frozen Tier-3 intent taxonomy specification
│   └── golden_set_annotation_guidelines.md
└── tests/                                # 100+ pytest unit & integration tests
```

---

## Setup & Environment

1. Activate the Python 3.10+ virtual environment:
   ```powershell
   .\.venv\Scripts\Activate.ps1
   ```

2. Install dependencies:
   ```powershell
   pip install -r requirements.txt
   ```

---

## Running the Spotify Support Agent

### 1. Interactive & Single-Message Demo CLI
Run single customer inquiries directly from the command line:
```powershell
python scripts/demo_agent.py "Why was I charged twice for Spotify Premium this month?"
```

Run in interactive prompt mode:
```powershell
python scripts/demo_agent.py --interactive
```

### 2. Run Test Suite
Execute all unit, integration, and regression tests:
```powershell
python -m pytest -q
```

### 3. Run Golden Set Evaluation Harness
Evaluate the end-to-end agent across all 200 canonical gold annotations:
```powershell
python scripts/evaluate_agent.py
```

### 4. Validate Gold Annotations
Verify the structural schema and referential integrity of the canonical gold dataset:
```powershell
python scripts/validate_gold_annotations.py
```

---

## Evaluation Results

Evaluated end-to-end against the 200 canonical human gold evaluation set (`data/processed/golden_set_annotations.jsonl`):

| Evaluation Metric | Measured Accuracy | Correct / Total |
|---|:---:|:---:|
| **Primary Intent Accuracy** | **100.00%** | 200 / 200 |
| **Secondary Intents Exact Match** | **87.50%** | 175 / 200 |
| **Technical Malfunction Scope Accuracy** | **91.50%** | 183 / 200 |
| **Cross-Cutting Flags Accuracy** | **89.00%** | 178 / 200 |
| **Non-Intent Accuracy** | **100.00%** | 200 / 200 |
| **Full Record Exact Match Accuracy** | **73.50%** | 147 / 200 |

### Per-Intent Recall Breakdown

| Intent ID & Name | Gold Count | Predicted | Correct | Recall |
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
| Non-Intent Classes (`insufficient_info`, `out_of_scope`, `ack`) | 12 | 12 | 12 | **100.0%** |
