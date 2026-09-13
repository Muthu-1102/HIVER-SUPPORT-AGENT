# SpotifyCares Intent Discovery Sampling Documentation

## Overview

This document details the deterministic, reproducible sampling strategy used to construct `data/processed/intent_discovery_sample.jsonl` from the canonical Spotify customer support conversation dataset (`data/processed/spotify_conversations.jsonl`).

The sample is specifically designed to support **qualitative intent taxonomy discovery** (Tier 3) without relying on automated LLM labeling or subjective manual selection.

---

## Metadata & Sample Characteristics

* **Source Dataset:** `data/processed/spotify_conversations.jsonl` (28,280 reconstructed conversations, 42.89 MB)
* **Output Sample Path:** `data/processed/intent_discovery_sample.jsonl` (400 conversations, ~0.69 MB)
* **Sample Size:** 400 conversations (exactly within the 300–500 target range)
* **Deterministic Seed & Method:** Fixed Random Seed `42`, combined with SHA-256 deterministic hash sorting per (stratum, topic cluster) cell.
* **Execution Script:** `scripts/create_intent_discovery_sample.py`

---

## Sampling Methodology

To ensure maximum representativeness across issue types, dialogue depths, and interaction patterns, a **Stratified Hybrid Sampling Framework** was employed:

### 1. Structural Depth & Turn Stratification

Conversations are partitioned into three interaction-depth strata based on `customer_brand_interaction_turn_count`:

1. **Single-Turn (1 Turn):** 200 conversations (50.0% quota). Captures simple, direct one-and-done inquiries, quick FAQs, and immediate DM redirects.
2. **Short Multi-Turn (2–3 Turns):** 120 conversations (30.0% quota). Captures initial troubleshooting, clarifying follow-up questions, and basic multi-message resolution paths.
3. **Deep Multi-Turn (4+ Turns):** 80 conversations (20.0% quota). Captures complex, persistent technical issues, recurring complaints, and extended back-and-forth interactions (reaching up to 24 turns).

### 2. Lexical Topic & Vocabulary Stratification

To prevent over-sampling dominant generic queries and guarantee coverage across distinct customer problem domains:
* Customer text from each conversation is vectorized using TF-IDF (`max_features=1000`, English stop-words removed).
* Deterministic K-Means clustering ($K=8$, `random_state=42`) partitions the text feature space into 8 distinct lexical topic clusters (covering Account/Login, Billing/Subscriptions, Playback/Streaming, App/UI Bugs, Offline/Downloads, Device/Bluetooth/CarPlay, Playlists/Library, and DM/Escalations).
* Within each turn stratum, quota allocation is distributed proportionally across all 8 topic clusters.

### 3. Deterministic Selection Mechanism

Within each (Turn Stratum, Topic Cluster) cell, candidates are deterministically ranked by hashing their unique string identifier:
$$\text{Hash Key} = \text{SHA256}(\text{"42\_stratum\_cluster\_"} + \text{conversation\_thread\_id})$$

The top items matching the cell quota are selected. This eliminates any pseudo-random state variance across operating systems or Python runtimes.

---

## Inclusion Criteria

A conversation is eligible for sampling if and only if it satisfies:
1. `contains_customer_and_spotify == True` (contains at least one customer message and at least one SpotifyCares message).
2. Non-empty customer message text.
3. Preserves complete canonical JSON metadata (`conversation_thread_id`, `thread_root_tweet_id`, `ordered_messages`, `conversation_depth`, `customer_brand_interaction_turn_count`, `contains_two_or_more_customer_brand_interaction_turns`, and `reconstruction_flags`).

---

## Sample Composition & Audit

| Metric / Dimension | Sample Value | Percentage |
|---|---|---|
| Total Sample Size | 400 conversations | 100.0% |
| Single-Turn Conversations | 200 conversations | 50.0% |
| Multi-Turn Conversations | 200 conversations | 50.0% |
| Max Dialogue Turn Depth | 24 turns | N/A |
| Account / Email Inquiries | 140 conversations | 35.0% |
| Playback / Streaming Issues | 110 conversations | 27.5% |
| Playlist / Song / Library Issues | 66 conversations | 16.5% |
| Premium / Subscription Queries | 57 conversations | 14.2% |
| App Update / Error / Crash Reports | 42 conversations | 10.5% |
| Offline / Download Queries | 24 conversations | 6.0% |
| Direct Message / Private Escalations | 161 conversations | 40.2% |

---

## Limitations

1. **Qualitative Intent Discovery Focus:** The 400-conversation sample is optimized for inductive intent taxonomy construction and qualitative pattern discovery, not for estimating population-wide intent frequency.
2. **Unobserved Private Outcomes:** Conversations escalating to Twitter Direct Messages (DMs) or email/phone support truncate at the public handoff boundary; private resolution details remain unobserved.
3. **Domain Specificity:** The vocabulary and interaction patterns reflect Spotify's digital audio streaming ecosystem and Twitter's 280-character microblogging format.

---

## Exact Reproduction Command

To reproduce this exact sample deterministically from the canonical dataset, run:

```powershell
python scripts/create_intent_discovery_sample.py --input data/processed/spotify_conversations.jsonl --output data/processed/intent_discovery_sample.jsonl --sample-size 400 --seed 42 --n-clusters 8
```
