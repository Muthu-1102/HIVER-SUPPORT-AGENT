# Human Gold Annotation Guidelines & Protocol (Schema v1.0.0)

## 1. Objectives & Purpose

This document establishes the official **Human Gold Annotation Protocol** for the 200 SpotifyCares Golden Evaluation Set candidates (`data/processed/golden_set_candidates.jsonl`).

The goal of this phase is to produce gold-standard human-verified labels that serve as the authoritative evaluation benchmark for:
* Customer intent classification
* Multi-intent detection
* Outage vs. individual diagnostic scope routing
* Escalation and private-channel handoff flag triggers
* Non-support / un-actionable message filtering

> [!IMPORTANT]
> **Taxonomy Freeze Compliance:**
> Annotators must strictly adhere to the frozen label space defined in [`docs/intent_taxonomy.md`](file:///d:/Projects/Hiver/HIVER-SUPPORT-AGENT/docs/intent_taxonomy.md).
> Under no circumstances may annotators invent new intent classes, modify scope options, or create custom escalation levels (such as AUTO/CONDITIONAL/ESCALATE).

---

## 2. Unit of Annotation

* **Unit:** The **entire reconstructed conversation thread** (`ordered_messages` containing customer inquiries, follow-up messages, and SpotifyCares agent responses).
* **Contextual Grounding:** While the primary customer issue is typically introduced in the root inbound message, annotators must review subsequent turns to evaluate multi-turn clarification, multi-intent emergence, and customer dissatisfaction signals.

---

## 3. Frozen Taxonomy Reference

### 3.1. Substantive Customer Intents (9)

| Intent ID & Name | Scope / Summary |
|---|---|
| `01_catalog_content_gap` | Missing songs, unreleased tracks/albums, podcast availability, removed content. |
| `02_catalog_metadata_error` | Mislabeled tracks, incorrect artist credits, out-of-sync lyrics, wrong artwork. |
| `03_region_availability` | Country restrictions, geo-licensing blocks, greyed-out tracks abroad, travel limits. |
| `04_billing_payment` | Direct charges, invoices, duplicate payments, refund requests, partner promo credits. |
| `05_subscription_plan_management` | Plan changes (Family, Duo, Student), member invites, SheerID verification. |
| `06_login_authentication` | Password resets, 2FA errors, account lockouts, compromised/hacked accounts. |
| `07_technical_malfunction` | App crashes, buffering, streaming errors, offline download failures, Bluetooth/hardware. |
| `08_feature_request` | Suggestions for new features, UI/UX requests, community product ideas. |
| `09_artist_rights_holder_mgmt` | Spotify for Artists access, profile verification, DMCA notices, creator royalties. |

### 3.2. Non-Intent Output Classes (3)

| Class | Definition |
|---|---|
| `insufficient_information` | Inbound message lacks sufficient detail to determine a substantive intent (e.g., *"Help me"*, *"I have a question"*). |
| `out_of_scope_non_support` | Social banter, memes, general music praise, playlist sharing without support issues. |
| `no_action_acknowledgment_only` | Closing statements, thank-you notes, and confirmations after issue resolution. |

### 3.3. Technical Malfunction Scopes (3)

Mandatory whenever `07_technical_malfunction` is present (as primary or secondary); strictly `null` otherwise.

| Scope | Definition |
|---|---|
| `individual` | Problem is localized to a specific user's device, OS version, hardware, or local network. |
| `platform_wide` | System-wide outage, server downtime, or widespread service disruption affecting all users. |
| `unclear` | Playback/app error reported without device or platform-wide context. |

### 3.4. Cross-Cutting Flags (2)

Independent boolean flags that govern escalation routing without replacing the primary intent:

| Flag | Trigger Criteria |
|---|---|
| `prior_interaction_dissatisfaction` | Customer explicitly expresses frustration about previous unacknowledged or unresolved support contacts (e.g., *"Third time messaging you!"*, *"Still no reply for days"*). |
| `alternate_channel_request` | Customer or agent requests/initiates transition to a private communication channel (Twitter DM, email, web form). |

---

## 4. Annotation Decision Flowchart

```
                          [ Inbound Conversation ]
                                     |
                +--------------------+--------------------+
                |                                         |
     [ Is it a support inquiry? ]              [ Not actionable / Social ]
                |                                         |
     +----------+----------+                   +----------+----------+
     |                     |                   |                     |
[ Sufficient Context ]  [ Vague / No Info ] [ Social Banter ]  [ Closing Thanks ]
     |                     |                   |                     |
(Substantive Intent) (insufficient_info) (out_of_scope)  (no_action_ack)
     |
     +--> 1. Select Primary Intent (Highest Actionability)
     +--> 2. Tag Secondary Intents (if compound inquiry)
     +--> 3. If Intent 07 present -> Tag Scope (individual | platform_wide | unclear)
     +--> 4. Tag Flags (prior_interaction_dissatisfaction, alternate_channel_request)
     +--> 5. Record Ambiguity & Evidence Quote
```

---

## 5. Decision Rules & Disambiguation Boundaries

1. **Catalog Gap (`01`) vs. Region Block (`03`):**
   * If customer asks why a track is missing generally -> `01_catalog_content_gap`.
   * If customer mentions country-specific licensing or moving/traveling -> `03_region_availability`.
2. **Metadata Error (`02`) vs. Content Gap (`01`) vs. Technical Glitch (`07`):**
   * Song title misspelled or wrong artist listed -> `02_catalog_metadata_error`.
   * Song missing from album/artist profile -> `01_catalog_content_gap`.
   * Song plays the wrong audio file due to caching/streaming bug -> `07_technical_malfunction`.
3. **Login (`06`) vs. Technical Bug (`07`):**
   * Issues with credentials, passwords, 2FA, or compromised account -> `06_login_authentication`.
   * App crashing immediately upon launch before login screen -> `07_technical_malfunction`.
4. **Multi-Intent Priority Order:**
   When multiple intents are present, assign the primary intent by operational urgency:
   $$\text{06\_login} > \text{04\_billing} > \text{07\_technical} > \text{05\_plan} > \text{03\_region} > \text{01\_catalog} > \text{02\_metadata} > \text{08\_feature} > \text{09\_artist}$$
   Secondary intents are recorded in `secondary_intents`.

---

## 6. Schema v1.0.0 Specification

Every line in the gold annotation JSONL files must adhere to the following JSON schema:

```json
{
  "conversation_id": "spotify_root_855",
  "annotator_id": "annotator_1",
  "annotation_timestamp": "2026-09-13T12:00:00Z",
  "is_non_intent": false,
  "primary_intent": "07_technical_malfunction",
  "secondary_intents": [],
  "non_intent_class": null,
  "technical_malfunction_scope": "individual",
  "cross_cutting_flags": [],
  "is_ambiguous": false,
  "ambiguity_category": null,
  "ambiguity_notes": null,
  "confidence": "high",
  "evidence_quote": "shuffle and repeat button just don't fucking work on iOS app",
  "schema_version": "1.0.0"
}
```

---

## 7. Double-Annotation & Adjudication Protocol

### 7.1. Double-Annotation Sampling Frame
* **Subset Size:** Exactly **50 candidates (25.0%)** must be independently annotated by two annotators (`annotator_1` and `annotator_2`).
* **Blinded Protocol:** Annotator 1 and Annotator 2 annotate the double-annotated subset independently without access to each other's labels.

### 7.2. Agreement Calculation
* Inter-annotator agreement is computed via [`scripts/adjudicate_annotations.py`](file:///d:/Projects/Hiver/HIVER-SUPPORT-AGENT/scripts/adjudicate_annotations.py):
  * **Raw Agreement Percentage:** Proportion of pairs where `primary_intent` (or non-intent class) matches.
  * **Cohen's Kappa ($\kappa$):** Chance-adjusted inter-annotator reliability metric.

### 7.3. Disagreement Resolution & Adjudication
1. **Consensus Items:** Where Annotator 1 and Annotator 2 agree on primary intent, scope, and flags, the record is automatically promoted to the canonical gold set with `annotator_id: "consensus"`.
2. **Discrepancy Items:** Where Annotator 1 and Annotator 2 disagree, a designated Lead Adjudicator reviews the thread and records an adjudication entry (`annotator_id: "adjudicator"`) with explicit `adjudication_reasoning`.
3. **Canonical Output:** [`data/processed/golden_set_annotations.jsonl`](file:///d:/Projects/Hiver/HIVER-SUPPORT-AGENT/data/processed/golden_set_annotations.jsonl) contains exactly one authoritative gold record per candidate (200 records total).

---

## 8. Annotation Workspace Preparation & Execution

### 8.1. Initialize Blank Annotator Workspaces
Run the workspace preparation utility:
```powershell
python scripts/prepare_annotation_workspace.py
```
This generates:
1. `data/processed/annotator_1_workspace.jsonl`: 200 blank template records for Annotator 1.
2. `data/processed/annotator_2_workspace.jsonl`: 50 blank template records for Annotator 2 (independent double annotation).
3. `data/processed/double_annotation_conversation_ids.txt`: Deterministic list of the 50 double-annotation conversation IDs.

### 8.2. Annotator Execution
* **Annotator 1:** Annotates all 200 items in `data/processed/annotator_1_workspace.jsonl`.
* **Annotator 2:** Independently annotates the 50 items in `data/processed/annotator_2_workspace.jsonl` without viewing Annotator 1's work.

### 8.3. Merge & Adjudicate
Once human annotation is complete:
```powershell
# 1. Merge completed workspaces into raw annotations
python scripts/prepare_annotation_workspace.py --merge

# 2. Run adjudication and compute inter-annotator agreement
python scripts/adjudicate_annotations.py --raw-annotations data/processed/golden_set_raw_annotations.jsonl

# 3. Validate canonical consolidated gold annotations
python scripts/validate_gold_annotations.py --annotations data/processed/golden_set_annotations.jsonl --mode canonical
```
