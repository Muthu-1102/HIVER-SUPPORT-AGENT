# SpotifyCares Customer Support Intent Taxonomy

## 1. Taxonomy Overview

This document establishes the official, frozen **Tier 3 Customer Support Intent Taxonomy** for the SpotifyCares AI Customer-Support Agent. 

The taxonomy is designed to categorize inbound customer inquiries, guide automated response generation, govern human escalation routing, and provide a standardized label space for evaluation.

### Taxonomy Architecture
* **9 Substantive Customer Intents:** Core actionable support categories.
* **3 Non-Intent Output Classes:** Operational handling for non-support or un-actionable messages.
* **2 Cross-Cutting Flags:** Secondary metadata attributes governing escalation and routing overrides.
* **1 Technical Malfunction Scope Sub-Flag:** Diagnostic classification for technical issues.

---

## 2. The 9 Substantive Intents Summary

| Intent ID & Name | Scope / Focus Area | Operational Weight |
|---|---|---|
| `01_catalog_content_gap` | Missing songs, albums, artists, or podcasts on Spotify | Core Support |
| `02_catalog_metadata_error` | Mislabeled tracks, incorrect artist credits, lyric sync errors | Thin Operational |
| `03_region_availability` | Country restrictions, geo-licensing blocks, travel playback | Core Support |
| `04_billing_payment` | Charges, invoices, payment method failures, promo credits | Core Support |
| `05_subscription_plan_management` | Upgrades/downgrades, Family Plan invites, Student verification | Core Support |
| `06_login_authentication` | Password resets, account lockouts, compromised/hacked accounts | Core Support (High Priority) |
| `07_technical_malfunction` | App crashes, buffering, playback errors, device connectivity | Core Support (Diagnostic) |
| `08_feature_request` | Product feedback, UI/UX suggestions, feature requests | Product Feedback |
| `09_artist_rights_holder_mgmt` | Spotify for Artists verification, royalty routing, profile edits | Thin Operational |

---

## 3–8. Substantive Intent Specifications

### `01_catalog_content_gap`
* **Exact Definition:** Inquiries regarding the absence, missing availability, or expected release date of specific tracks, albums, discographies, podcasts, or explicit/clean versions on Spotify.
* **Inclusion Criteria:** Requests asking why an artist/album is missing, asking when a song will be added, reporting unavailable tracks in a public playlist.
* **Exclusion Criteria:** Songs greyed out due to geographical travel/location restrictions (`03_region_availability`); mislabeled track titles (`02_catalog_metadata_error`).
* **Boundary Rules:** If missing content is tied to a specific foreign country or region block, assign `03_region_availability`.
* **Representative Examples:**
  * *"Why is Young Thug's new album not on Spotify yet?"*
  * *"Is Patek Water by Future available on Spotify?"*
* **Routing Implications:** Automated content-search lookup; return direct track/artist URI or standard content availability status response.

### `02_catalog_metadata_error`
* **Exact Definition:** Reports of incorrect, corrupted, or misattributed metadata on existing Spotify content.
* **Inclusion Criteria:** Misspelled song titles, wrong album artwork, incorrect artist mapping (two artists merged into one profile), out-of-sync or incorrect lyrics.
* **Exclusion Criteria:** Missing songs (`01_catalog_content_gap`); artist requesting verification/ownership of profile (`09_artist_rights_holder_mgmt`).
* **Boundary Rules:** Retained as a thin operational intent specifically for metadata correction tickets.
* **Representative Examples:**
  * *"The song title for track 4 on this album is misspelled."*
  * *"Lyrics for this song are totally out of sync with the audio."*
* **Routing Implications:** Log metadata bug ticket for content operations team; respond with metadata reporting confirmation.

### `03_region_availability`
* **Exact Definition:** Questions or complaints regarding geographical licensing restrictions, regional content blocks, or playback changes when traveling across countries.
* **Inclusion Criteria:** "Song greyed out in my country", account region change inquiries, travel playback limits.
* **Exclusion Criteria:** General missing content with no regional aspect (`01_catalog_content_gap`); billing address changes (`04_billing_payment`).
* **Boundary Rules:** If user mentions moving countries or local country catalog differences, assign `03_region_availability`.
* **Representative Examples:**
  * *"Why is this album greyed out in the UK?"*
  * *"I moved from US to Philippines and my saved songs are unavailable."*
* **Routing Implications:** Provide country licensing explanation and guide user on updating country settings in account profile.

### `04_billing_payment`
* **Exact Definition:** Inquiries regarding monetary charges, payment processing, invoices, duplicate billing, refund requests, or promotional partner credits.
* **Inclusion Criteria:** Unrecognized charges, failed payment attempts, Capital One / partner promo cash-back credit inquiries, invoice requests.
* **Exclusion Criteria:** Changing plan type (`05_subscription_plan_management`); student status verification failures (`05_subscription_plan_management`).
* **Boundary Rules:** Monetary disputes and transaction questions belong here. If user wants to switch from Individual to Family plan, use `05_subscription_plan_management`.
* **Representative Examples:**
  * *"Why was I charged twice this month?"*
  * *"How long does the 50% credit card promo cash back take to post?"*
* **Routing Implications:** High-priority financial handling; route to billing support bot or human agent if charge refund is requested.

### `05_subscription_plan_management`
* **Exact Definition:** Inquiries regarding subscription tiers (Free, Premium Individual, Premium Family, Duo, Student), plan modifications, member invitations, and student eligibility verification.
* **Inclusion Criteria:** Upgrading/downgrading plans, adding/removing Family Plan members, SheerID student verification issues, changing Family Plan address.
* **Exclusion Criteria:** Disputing a credit card charge (`04_billing_payment`); account login failure (`06_login_authentication`).
* **Boundary Rules:** Modifying plan structure or account membership falls under `05_subscription_plan_management`.
* **Representative Examples:**
  * *"How do I add a family member to my Premium Family account?"*
  * *"My SheerID student verification link expired, can I get a new one?"*
* **Routing Implications:** Automated workflow for plan management links, SheerID verification guide, or Family Plan management steps.

### `06_login_authentication`
* **Exact Definition:** Issues preventing a user from logging into their Spotify account, password reset failures, email address updates, or compromised/hacked account recovery.
* **Inclusion Criteria:** Forgotten password/username, 2FA code not received, "Account hacked / email changed without permission", Facebook social login disconnects.
* **Exclusion Criteria:** App crashing after successful login (`07_technical_malfunction`); billing address updates (`04_billing_payment`).
* **Boundary Rules:** Critical security intent. Hacked account claims require immediate security workflow triggering.
* **Representative Examples:**
  * *"I can't log in and my email was changed without my consent!"*
  * *"Password reset link is not arriving in my inbox."*
* **Routing Implications:** High-priority security containment; trigger automated account recovery flow or immediate human agent security escalation.

### `07_technical_malfunction`
* **Exact Definition:** Errors, bugs, crashes, audio quality issues, playback freezes, offline download failures, or hardware connectivity problems (Bluetooth, CarPlay, Sonos, desktop app).
* **Inclusion Criteria:** App crashing on launch, music buffering constantly, offline songs un-downloading, Bluetooth track control failure.
* **Exclusion Criteria:** Mislabeled song title (`02_catalog_metadata_error`); missing track in library (`01_catalog_content_gap`).
* **Boundary Rules:** All technical and hardware bugs belong here. Technical malfunction scope MUST be evaluated via the mandatory sub-flag (`individual`, `platform_wide`, `unclear`). Do NOT split into separate intent categories.
* **Representative Examples:**
  * *"Spotify keeps crashing every time I open it on iOS 17."*
  * *"Is Spotify down right now? Nothing is loading for anyone."*
* **Routing Implications:** Diagnostic troubleshooting tree (clear cache, reinstall, check status). Outage responses governed by the technical malfunction scope policy.

### `08_feature_request`
* **Exact Definition:** Suggestions, product ideas, UX/UI feedback, or requests for functionality not currently present in Spotify applications.
* **Inclusion Criteria:** Requesting folder creation on mobile app, asking for light mode, suggesting new equalizer presets, requesting lyrics return.
* **Exclusion Criteria:** Reporting broken existing feature (`07_technical_malfunction`); missing song (`01_catalog_content_gap`).
* **Boundary Rules:** Ideas for *new* features or design improvements.
* **Representative Examples:**
  * *"Please add playlist folder creation on the mobile app!"*
  * *"It would be great if we could customize the app icon on Android."*
* **Routing Implications:** Log to product feedback pipeline; respond with community idea board link and thank-you acknowledgment.

### `09_artist_rights_holder_mgmt`
* **Exact Definition:** Inquiries from music creators, artists, managers, or label representatives regarding artist profile ownership, Spotify for Artists access, claims, or royalty routing.
* **Inclusion Criteria:** Claiming artist profile on Spotify for Artists, updating artist avatar/bio, reporting copyright infringement / DMCA takedown.
* **Exclusion Criteria:** Customer asking for an artist's song (`01_catalog_content_gap`); listener reporting wrong track metadata (`02_catalog_metadata_error`).
* **Boundary Rules:** Retained as a thin operational intent specifically for creator and rights-holder communications.
* **Representative Examples:**
  * *"How do I verify my artist profile on Spotify for Artists?"*
  * *"I am a rights holder and need to submit a DMCA takedown notice."*
* **Routing Implications:** Direct routing to Spotify for Artists portal and creator support specialized team.

---

## 9. The 3 Non-Intent Output Classes

1. `insufficient_information`:
   * **Definition:** Messages lacking actionable detail or context to classify into a substantive intent (e.g., *"Help me"*, *"It's broken"*).
   * **Handling:** Prompt customer for specific details (device, error message, account handle).
2. `out_of_scope_non_support`:
   * **Definition:** Social media chatter, general memes, non-support brand mentions, or off-topic banter (e.g., *"Masaya ako"*, *"I love music"*).
   * **Handling:** Light social engagement or no automated ticket creation.
3. `no_action_acknowledgment_only`:
   * **Definition:** Customer closing statements, thank-you notes, or confirmation messages where the support issue has already been resolved (e.g., *"Thanks that fixed it!"*, *"Awesome, got it"*).
   * **Handling:** Polite closing acknowledgment; close ticket without escalation.

---

## 10. The 2 Cross-Cutting Flags

1. `prior_interaction_dissatisfaction`:
   * **Definition:** Indicates customer frustration with previous unresolved support attempts (e.g., *"I've sent 5 messages and no one replied"*, *"Third time reaching out!"*).
   * **Escalation Policy Override:** Overrides standard intent routing and **forces immediate human agent escalation**.
2. `alternate_channel_request`:
   * **Definition:** Indicates customer preference or agent instruction to move to a private channel (Direct Message, Email, Web Form).
   * **Routing Policy Override:** Routes directly to private channel handoff workflow (e.g., generating secure DM link).

---

## 11. Technical Malfunction Scope Sub-Flag

Every message categorized under `07_technical_malfunction` must be tagged with a scope sub-flag:
* `individual`: Issue is localized to a single user's device or network.
* `platform_wide`: System-wide outage affecting a large population.
* `unclear`: Scope cannot be determined from customer text alone.

### Outage & Automation Policy
* **`unclear` scope MUST NOT be treated as a verified outage.**
* Automated platform-wide outage responses are permitted **ONLY when live service status is independently verified** via real-time monitoring infrastructure.

---

## 12. Multi-Intent Policy

When a customer message contains multiple distinct intents:
1. **Primary Intent Assignment:** Select the most urgent actionable intent (Priority order: `06_login` > `04_billing` > `07_technical` > `05_plan` > `03_region` > `01_catalog` > `02_metadata` > `08_feature` > `09_artist`).
2. **Secondary Intent Tagging:** Retain secondary intents as metadata tags to enable multi-part response generation.

---

## 13. Insufficient-Information Policy

* Do not guess customer intent on ambiguous inputs.
* If message contains fewer than required context signals, emit `insufficient_information` and trigger diagnostic clarification prompt.

---

## 14. Out-of-Scope Policy

* Messages without support intent (social chatter, general brand mentions) emit `out_of_scope_non_support`.
* Prevents unnecessary ticket creation in support CRM.

---

## 15. Known Ambiguity Cases

* **Capital One 50% Credit Promo:** Involves both credit card promo timing (`04_billing_payment`) and Family Plan configuration (`05_subscription_plan_management`).
* **Greyed Out Songs:** Distinguish general missing content (`01_catalog_content_gap`) from country licensing blocks (`03_region_availability`).

---

## 16. Human-Review Decisions

* Thin operational intents `02_catalog_metadata_error` and `09_artist_rights_holder_mgmt` are explicitly retained to support specialized operational routing.
* Do NOT split `07_technical_malfunction` into separate intent classes; represent technical scope via the sub-flag attribute.

---

## 17. Data-Integrity Audit Findings

An empirical data-integrity audit of the reconstructed SpotifyCares dataset was conducted using [`scripts/audit_taxonomy_data_integrity.py`](file:///d:/Projects/Hiver/HIVER-SUPPORT-AGENT/scripts/audit_taxonomy_data_integrity.py).

### Target Thread Analysis:

1. **`spotify_root_784880`**:
   * **Structural Status:** **Structurally Impaired / Contaminated.**
   * **Finding:** Contains third-party support agent crosstalk. Anonymized user `142798` (Capital One support agent) responds with agent signoffs (`^IP`, `^DH`). Because non-Spotify accounts are categorized as `inbound: true`, Capital One agent replies are misclassified as customer turns.
   * **Retrieval Grounding Assessment:** **Unsuitable / High-Risk** in full form. If used for retrieval grounding, it must be sliced to include only messages from `784875` onward (direct customer query regarding Family Plan name change under `05_subscription_plan_management`).

2. **`spotify_root_904057`**:
   * **Structural Status:** **Partially Valid / Multi-Phase.**
   * **Finding:** Turns 0–1 contain non-support Tagalog social chatter ("Masaya ako") and third-party handle `148611`. Turns 2–5 form a clean interaction where customer requests track "Patek Water" by Young Thug & Future and Spotify provides the track link (`01_catalog_content_gap`).
   * **Retrieval Grounding Assessment:** **Requires Truncation.** Turns 2–5 are valid retrieval grounding for `01_catalog_content_gap`, but Turns 0–1 must be pruned before vector indexing to avoid polluting intent embeddings with social chatter.
