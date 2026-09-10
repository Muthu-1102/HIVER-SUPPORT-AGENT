# Dataset analysis scripts

Run from the repository root.

First-stage profile (if its script is available in the checkout):

```powershell
python scripts/profile_dataset.py
```

Second-stage candidate analysis:

```powershell
python scripts/analyze_brand_candidates.py
```

The second-stage analysis streams `data/raw/twcs.csv` twice and uses temporary,
deleted SQLite indexes. It writes `data/processed/brand_candidate_analysis.csv`
and `docs/brand_candidate_analysis.md`.
