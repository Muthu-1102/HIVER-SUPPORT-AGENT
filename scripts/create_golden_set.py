#!/usr/bin/env python3
"""
Deterministic Golden Evaluation Set Candidate-Generation Pipeline.

Generates data/processed/golden_set_candidates.jsonl containing ~200 candidate threads
stratified across frozen taxonomy intents, non-intent classes, cross-cutting flags,
boundary pairs, escalation cases, compound intents, and structural audit risks.

Fixed Salt: hiver-golden-set-v1
Deterministic Ranking: SHA256(conversation_id + fixed_salt)
"""

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

FIXED_SALT = "hiver-golden-set-v1"

# ---------------------------------------------------------------------------
# Lexical & Pattern Detectors
# ---------------------------------------------------------------------------

PATTERNS = {
    "01_catalog_content_gap": re.compile(
        r"\b(not on spotify|missing (song|track|album|artist|podcast|ep)|add (this|the|.*) to spotify|"
        r"put (it|this|.*) on spotify|when will .* (be on|come to) spotify|why (isn\'?t|is .*) not on spotify|"
        r"catalog gap|removed from spotify|discography|not available on spotify|"
        r"upload (this|the) (song|album) to spotify)\b",
        re.I,
    ),
    "02_catalog_metadata_error": re.compile(
        r"\b(misspelled|wrong (album|artist|title|track|cover|lyrics|song|name)|"
        r"lyrics (are )?(out of sync|wrong|incorrect|missing)|mixed up with|"
        r"typo in (song|artist|album|title)|incorrect artist|wrong artwork|"
        r"duplicate artist|wrong picture)\b",
        re.I,
    ),
    "03_region_availability": re.compile(
        r"\b(region|country|greyed out|grayed out|geo[- ]?block|"
        r"available in (my|the|[a-z]+ country)|"
        r"not available in (my|the|[a-z]+ country|uk|us|usa|canada|philippines|australia|germany|mexico|brazil|india)|"
        r"traveling abroad|moved to|country settings|licensing in (my|the|[a-z]+ country))\b",
        re.I,
    ),
    "04_billing_payment": re.compile(
        r"\b(charged|billing|payment|invoice|credit card|debit card|refund|receipt|"
        r"paypal|bank account|promo code|cash ?back|capital one|double charged|"
        r"charged twice|subscription fee|charged me|unrecognized charge)\b",
        re.I,
    ),
    "05_subscription_plan_management": re.compile(
        r"\b(family plan|student (discount|plan|verification)|sheerid|"
        r"premium (family|for students|duo)|upgrade|downgrade|add member|"
        r"cancel (my )?premium|cancel (my )?subscription|change (my )?plan|join family|"
        r"switch to (premium|family))\b",
        re.I,
    ),
    "06_login_authentication": re.compile(
        r"\b(can\'?t log ?in|cannot log ?in|login|log ?in error|password|reset password|"
        r"locked out|hacked|compromised|2fa|verification code|email changed|"
        r"forgot (my )?password|facebook log ?in|cant log in)\b",
        re.I,
    ),
    "07_technical_malfunction": re.compile(
        r"\b(crash|crashes|crashing|bug|error|glitch|freeze|freezing|playback|buffering|"
        r"offline (songs|mode|download)|bluetooth|carplay|sonos|not playing|won\'?t play|"
        r"skipping|black screen|keeps stopping|keeps pausing|won\'?t load|"
        r"is spotify down|spotify (is )?down|outage|down for everyone|server(s)? down|"
        r"everyone having|global issue|down right now|system down|is it down|"
        r"working for anyone|anyone else having|down again)\b",
        re.I,
    ),
    "08_feature_request": re.compile(
        r"\b(feature request|please add|can you add|would be (great|nice|cool|awesome) if|"
        r"suggestion|bring back|light mode|idea for|wish spotify had|add an? option|"
        r"add support for|option to)\b",
        re.I,
    ),
    "09_artist_rights_holder_mgmt": re.compile(
        r"\b(spotify for artists|artist (profile|page|account|claim|verification|access)|"
        r"verify (my )?artist|rights holder|copyright|dmca|takedown|royalt(y|ies)|"
        r"distributor|claim (my )?artist|as an artist|my music on spotify)\b",
        re.I,
    ),
}

FLAGS = {
    "prior_interaction_dissatisfaction": re.compile(
        r"\b(still waiting|no (one|reply|response)|sent (a|\d+) (message|dm|tweet)|"
        r"third time|second time|ignored|waiting for (days|hours|reply)|"
        r"nobody (replied|responded|answered)|frustrated|terrible support|worst support|been days)\b",
        re.I,
    ),
    "alternate_channel_request": re.compile(
        r"\b(check (your )?dm|sent (you )?a dm|sent (a )?direct message|check pm|sent pm|"
        r"dm\'?d you|dm sent|in your dms|can i dm|can you dm|sent a private message)\b",
        re.I,
    ),
}

TECH_SCOPE = {
    "platform_wide": re.compile(
        r"\b(is spotify down|spotify (is )?down|outage|down for everyone|server(s)? down|"
        r"everyone having|global issue|down right now|system down|is it down|"
        r"working for anyone|anyone else having|down again|spotify crashing for everyone)\b",
        re.I,
    ),
    "individual": re.compile(
        r"\b(on my (iphone|android|phone|mac|pc|ipad|laptop|car|device|samsung|pixel)|"
        r"my bluetooth|my carplay|my app|reinstalled|cleared cache|ios \d|android \d|my desktop)\b",
        re.I,
    ),
}

ESCALATION = {
    "churn_threat": re.compile(
        r"\b(cancel(ling|ing)? (my )?(subscription|premium|account)|leaving spotify|"
        r"switching to (apple music|tidal|deezer|amazon)|unsubscribing|done with spotify|close my account)\b",
        re.I,
    ),
    "minor_account": re.compile(
        r"\b(child|minor|under 13|my kid|kid\'?s account|parent(al)? account|age (limit|restriction)|daughter|son)\b",
        re.I,
    ),
    "repeated_charge": re.compile(
        r"\b(charged twice|double charge|charged again|billed twice|two charges|"
        r"charged multiple times|charged 2x|billed again)\b",
        re.I,
    ),
}

SIGNOFF_PATTERN = re.compile(r"(\^[A-Z]{2}\b|\-[A-Z]{2}\b|\/[A-Z]{2}\b)")

INTENT_PRIORITY_ORDER = [
    "06_login_authentication",
    "04_billing_payment",
    "07_technical_malfunction",
    "05_subscription_plan_management",
    "03_region_availability",
    "01_catalog_content_gap",
    "02_catalog_metadata_error",
    "08_feature_request",
    "09_artist_rights_holder_mgmt",
]

# ---------------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------------

def compute_deterministic_hash(conversation_id: str, salt: str = FIXED_SALT) -> str:
    """Compute SHA256(conversation_id + salt)."""
    return hashlib.sha256(f"{conversation_id}{salt}".encode("utf-8")).hexdigest()

def load_exclusions(exclusions_path: Path) -> Set[str]:
    """Load exclusion conversation thread IDs."""
    exclusions = set()
    if exclusions_path.exists():
        with exclusions_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    exclusions.add(line)
    return exclusions

def extract_candidate_features(conv: Dict[str, Any], salt: str = FIXED_SALT) -> Dict[str, Any]:
    """Extract classification, scope, flags, and structural characteristics from a conversation record."""
    tid = conv["conversation_thread_id"]
    inbound_msgs = [m for m in conv.get("ordered_messages", []) if m.get("inbound")]
    customer_text = " ".join(m.get("text", "") for m in inbound_msgs)
    inbound_authors = [m.get("author_id") for m in inbound_msgs]

    # Substantive intent matching
    matched_intents = [k for k, p in PATTERNS.items() if p.search(customer_text)]

    # Technical scope candidate
    scope = None
    if "07_technical_malfunction" in matched_intents:
        if TECH_SCOPE["platform_wide"].search(customer_text):
            scope = "platform_wide"
        elif TECH_SCOPE["individual"].search(customer_text):
            scope = "individual"
        else:
            scope = "unclear"

    # Cross-cutting flags
    is_dissat = bool(FLAGS["prior_interaction_dissatisfaction"].search(customer_text))
    is_alt_chan = bool(FLAGS["alternate_channel_request"].search(customer_text))

    # Non-intent classes
    is_no_action = bool(
        re.search(
            r"\b(thanks that fixed|thank you that worked|all sorted now|got it thanks|"
            r"thanks for the help|awesome thanks|fixed now|thank you so much|works now thanks)\b",
            customer_text,
            re.I,
        )
    )
    is_insufficient = (
        len(customer_text.strip()) < 35
        and any(
            w in customer_text.lower()
            for w in ["help", "help me", "fix", "dm", "hello", "hey", "support", "question", "broken", "issue", "problem"]
        )
        and len(matched_intents) == 0
        and not is_no_action
    )
    is_out_of_scope = (
        bool(
            re.search(
                r"\b(i love spotify|listening to|now playing|playlist is fire|greatest song|shoutout)\b",
                customer_text,
                re.I,
            )
        )
        and not any(
            w in customer_text.lower()
            for w in ["help", "issue", "problem", "fix", "why", "error", "broken", "cant", "cannot", "refund", "charge"]
        )
        and len(matched_intents) == 0
    )

    # Escalation sensitivity
    escalations = [k for k, p in ESCALATION.items() if p.search(customer_text)]

    # Structural risk
    has_signoff = any(SIGNOFF_PATTERN.search(m.get("text", "")) for m in inbound_msgs)
    has_multi_author = len(set(inbound_authors)) > 1
    is_structural = has_signoff or has_multi_author

    # Boundary pairs
    is_b_01_02 = (
        "01_catalog_content_gap" in matched_intents and "02_catalog_metadata_error" in matched_intents
    ) or bool(
        re.search(r"\b(track|song|album)\b.*\b(missing|wrong|misspelled)\b", customer_text, re.I)
        and ("01_catalog_content_gap" in matched_intents or "02_catalog_metadata_error" in matched_intents)
    )

    is_b_01_07 = (
        "01_catalog_content_gap" in matched_intents and "07_technical_malfunction" in matched_intents
    ) or bool(
        re.search(r"\b(song|track|album|playlist)\b.*\b(won\'?t play|disappeared|unavailable|greyed|crashes)\b", customer_text, re.I)
        and ("01_catalog_content_gap" in matched_intents or "07_technical_malfunction" in matched_intents)
    )

    is_b_06_07 = (
        "06_login_authentication" in matched_intents and "07_technical_malfunction" in matched_intents
    ) or bool(
        re.search(r"\b(log ?in|sign ?in|password)\b.*\b(crash|error|bug|freeze)\b", customer_text, re.I)
    )

    is_b_07_08 = (
        "07_technical_malfunction" in matched_intents and "08_feature_request" in matched_intents
    ) or bool(
        re.search(r"\b(update|new version|feature)\b.*\b(broken|bug|bring back|change)\b", customer_text, re.I)
    )

    is_b_01_08 = (
        "01_catalog_content_gap" in matched_intents and "08_feature_request" in matched_intents
    ) or bool(
        re.search(r"\b(add|support|catalog|format|lossless|hifi)\b.*\b(please|feature|request|when)\b", customer_text, re.I)
        and "08_feature_request" in matched_intents
    )

    # Primary candidate intent determination
    candidate_intent = None
    if matched_intents:
        for p_intent in INTENT_PRIORITY_ORDER:
            if p_intent in matched_intents:
                candidate_intent = p_intent
                break
    elif is_insufficient:
        candidate_intent = "insufficient_information"
    elif is_out_of_scope:
        candidate_intent = "out_of_scope_non_support"
    elif is_no_action:
        candidate_intent = "no_action_acknowledgment_only"

    return {
        "raw": conv,
        "id": tid,
        "hash": compute_deterministic_hash(tid, salt),
        "text": customer_text,
        "is_multi_turn": conv.get("customer_brand_interaction_turn_count", 1) >= 2,
        "matched_intents": matched_intents,
        "candidate_intent": candidate_intent,
        "scope": scope,
        "is_dissat": is_dissat,
        "is_alt_chan": is_alt_chan,
        "is_no_action": is_no_action,
        "is_insufficient": is_insufficient,
        "is_out_of_scope": is_out_of_scope,
        "escalations": escalations,
        "is_structural": is_structural,
        "is_b_01_02": is_b_01_02,
        "is_b_01_07": is_b_01_07,
        "is_b_06_07": is_b_06_07,
        "is_b_07_08": is_b_07_08,
        "is_b_01_08": is_b_01_08,
        "is_compound": len(matched_intents) >= 2,
    }

# ---------------------------------------------------------------------------
# Sampling Specification
# ---------------------------------------------------------------------------

def get_strata_specifications() -> List[Tuple[str, int, Callable[[Dict[str, Any]], bool]]]:
    """Return the ordered list of (stratum_name, quota, predicate)."""
    return [
        ("intent_baseline_01_catalog_content_gap", 14, lambda x: "01_catalog_content_gap" in x["matched_intents"]),
        ("intent_baseline_02_catalog_metadata_error", 8, lambda x: "02_catalog_metadata_error" in x["matched_intents"]),
        ("intent_baseline_03_region_availability", 10, lambda x: "03_region_availability" in x["matched_intents"]),
        ("intent_baseline_04_billing_payment", 16, lambda x: "04_billing_payment" in x["matched_intents"]),
        ("intent_baseline_05_subscription_plan_management", 12, lambda x: "05_subscription_plan_management" in x["matched_intents"]),
        ("intent_baseline_06_login_authentication", 12, lambda x: "06_login_authentication" in x["matched_intents"]),
        ("intent_baseline_07_technical_malfunction_individual", 7, lambda x: "07_technical_malfunction" in x["matched_intents"] and x["scope"] == "individual"),
        ("intent_baseline_07_technical_malfunction_platform_wide", 5, lambda x: "07_technical_malfunction" in x["matched_intents"] and x["scope"] == "platform_wide"),
        ("intent_baseline_07_technical_malfunction_unclear", 4, lambda x: "07_technical_malfunction" in x["matched_intents"] and x["scope"] == "unclear"),
        ("intent_baseline_08_feature_request", 12, lambda x: "08_feature_request" in x["matched_intents"]),
        ("intent_baseline_09_artist_rights_holder_mgmt", 8, lambda x: "09_artist_rights_holder_mgmt" in x["matched_intents"]),
        ("non_intent_insufficient_information", 8, lambda x: x["is_insufficient"]),
        ("non_intent_out_of_scope_non_support", 8, lambda x: x["is_out_of_scope"]),
        ("non_intent_no_action_acknowledgment_only", 8, lambda x: x["is_no_action"]),
        ("flag_prior_interaction_dissatisfaction", 6, lambda x: x["is_dissat"]),
        ("flag_alternate_channel_request", 6, lambda x: x["is_alt_chan"]),
        ("boundary_pair_01_02", 3, lambda x: x["is_b_01_02"]),
        ("boundary_pair_01_07", 4, lambda x: x["is_b_01_07"]),
        ("boundary_pair_06_07", 3, lambda x: x["is_b_06_07"]),
        ("boundary_pair_07_08", 3, lambda x: x["is_b_07_08"]),
        ("boundary_pair_01_08", 3, lambda x: x["is_b_01_08"]),
        ("escalation_sensitive", 10, lambda x: len(x["escalations"]) > 0),
        ("compound_multi_intent", 10, lambda x: x["is_compound"]),
        ("structural_risk_audit", 6, lambda x: x["is_structural"]),
        ("unstratified_control", 14, lambda x: True),
    ]

# ---------------------------------------------------------------------------
# Core Pipeline Execution
# ---------------------------------------------------------------------------

def generate_golden_set_candidates(
    input_path: Path,
    output_candidates_path: Path,
    exclusions_path: Path,
    salt: str = FIXED_SALT,
    target_total: int = 200,
    min_multi_turn_pct: float = 0.35,
) -> List[Dict[str, Any]]:
    """Execute deterministic candidate generation, validation, and serialization."""
    input_path = Path(input_path)
    output_candidates_path = Path(output_candidates_path)
    exclusions_path = Path(exclusions_path)

    output_candidates_path.parent.mkdir(parents=True, exist_ok=True)

    exclusions = load_exclusions(exclusions_path)
    print(f"Loaded {len(exclusions)} exclusion IDs from {exclusions_path}")

    if not input_path.exists():
        raise FileNotFoundError(f"Input corpus not found: {input_path}")

    # Read and parse candidates
    candidates: List[Dict[str, Any]] = []
    total_loaded = 0
    with input_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            total_loaded += 1
            conv = json.loads(line)
            tid = conv.get("conversation_thread_id")

            # Must contain both customer and spotify, and not be excluded
            if not conv.get("contains_customer_and_spotify", False):
                continue
            if tid in exclusions:
                continue

            features = extract_candidate_features(conv, salt=salt)
            candidates.append(features)

    print(f"Scanned {total_loaded} conversations. Found {len(candidates)} eligible candidate threads.")

    # Sort all candidates deterministically by SHA256 hash
    candidates.sort(key=lambda x: x["hash"])

    strata_specs = get_strata_specifications()
    expected_quota_sum = sum(q for _, q, _ in strata_specs)
    if expected_quota_sum != target_total:
        raise ValueError(
            f"Sampling specification total ({expected_quota_sum}) does not match target total ({target_total})"
        )

    # Deterministic allocation per stratum
    selected_ids: Set[str] = set()
    selected_records: List[Dict[str, Any]] = []
    stratum_membership: Dict[str, List[str]] = {}

    shortfalls = []

    for stratum_name, quota, predicate in strata_specs:
        pool = [c for c in candidates if predicate(c) and c["id"] not in selected_ids]
        available_count = len(pool)
        if available_count < quota:
            shortfall = quota - available_count
            shortfalls.append({
                "stratum": stratum_name,
                "required": quota,
                "available": available_count,
                "shortfall": shortfall,
            })
            chosen = pool
        else:
            chosen = pool[:quota]

        for item in chosen:
            selected_ids.add(item["id"])
            selected_records.append(item)
            stratum_membership.setdefault(item["id"], []).append(stratum_name)

    if shortfalls:
        error_msg = ["FAIL: Stratum quota shortfall detected:"]
        for s in shortfalls:
            error_msg.append(
                f"  - Stratum: {s['stratum']} | Required: {s['required']} | Available: {s['available']} | Shortfall: {s['shortfall']}"
            )
        raise RuntimeError("\n".join(error_msg))

    if len(selected_records) != target_total:
        raise RuntimeError(
            f"Candidate count mismatch: expected {target_total}, produced {len(selected_records)}"
        )

    # Multi-turn verification & enforcement
    multi_turn_threshold = int(target_total * min_multi_turn_pct)
    multi_turn_count = sum(1 for r in selected_records if r["is_multi_turn"])
    print(f"Initial Multi-Turn Count: {multi_turn_count} / {target_total} ({multi_turn_count/target_total*100:.1f}%)")

    if multi_turn_count < multi_turn_threshold:
        print(f"Multi-turn count {multi_turn_count} is below requirement {multi_turn_threshold}. Performing replacement...")
        # Replace single-turn items in unstratified_control or flexible strata with multi-turn alternatives
        for idx, item in enumerate(selected_records):
            if multi_turn_count >= multi_turn_threshold:
                break
            if not item["is_multi_turn"]:
                # Find replacement in eligible corpus satisfying same predicate
                # Search lowest hash multi-turn candidate not already selected
                replacements = [
                    c for c in candidates
                    if c["is_multi_turn"] and c["id"] not in selected_ids
                ]
                if replacements:
                    repl = replacements[0]
                    selected_ids.remove(item["id"])
                    selected_ids.add(repl["id"])
                    selected_records[idx] = repl
                    multi_turn_count += 1

    if multi_turn_count < multi_turn_threshold:
        raise RuntimeError(
            f"Unable to meet multi-turn quota: required >= {multi_turn_threshold}, achieved {multi_turn_count}"
        )

    # Tag all qualifying strata for each selected candidate
    final_output_records: List[Dict[str, Any]] = []

    for item in selected_records:
        applicable_strata = []
        for stratum_name, _, predicate in strata_specs:
            if stratum_name == "unstratified_control":
                if "unstratified_control" in stratum_membership.get(item["id"], []):
                    applicable_strata.append(stratum_name)
            else:
                if predicate(item):
                    applicable_strata.append(stratum_name)

        raw_conv = item["raw"]

        output_record = {
            "conversation_id": item["id"],
            "sampling_strata": applicable_strata,
            "candidate_intent": item["candidate_intent"],
            "technical_scope_candidate": item["scope"],
            "prior_interaction_dissatisfaction_candidate": item["is_dissat"],
            "alternate_channel_request_candidate": item["is_alt_chan"],
            "is_multi_turn": item["is_multi_turn"],
            "is_structural_risk": item["is_structural"],
            "sampling_hash": item["hash"],
            "thread_root_tweet_id": raw_conv.get("thread_root_tweet_id"),
            "ordered_messages": raw_conv.get("ordered_messages", []),
            "conversation_depth": raw_conv.get("conversation_depth", 0),
            "contains_customer_and_spotify": raw_conv.get("contains_customer_and_spotify", True),
            "customer_brand_interaction_turn_count": raw_conv.get("customer_brand_interaction_turn_count", 1),
            "contains_two_or_more_customer_brand_interaction_turns": raw_conv.get(
                "contains_two_or_more_customer_brand_interaction_turns", False
            ),
            "reconstruction_flags": raw_conv.get("reconstruction_flags", []),
        }
        final_output_records.append(output_record)

    # Write output to JSONL
    with output_candidates_path.open("w", encoding="utf-8") as f:
        for rec in final_output_records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    print(f"\nSuccessfully generated {len(final_output_records)} golden set candidate records.")
    print(f"Output saved to: {output_candidates_path}")

    return final_output_records

# ---------------------------------------------------------------------------
# CLI Entrypoint
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Deterministic Golden Evaluation Set candidate generation")
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("data/processed/spotify_conversations.jsonl"),
        help="Path to full reconstructable SpotifyCares conversations corpus",
    )
    parser.add_argument(
        "--output-candidates",
        type=Path,
        default=Path("data/processed/golden_set_candidates.jsonl"),
        help="Output path for candidate evaluation set JSONL",
    )
    parser.add_argument(
        "--exclusions",
        type=Path,
        default=Path("data/processed/golden_set_exclusions.txt"),
        help="Path to exclusion conversation IDs list",
    )
    parser.add_argument(
        "--salt",
        type=str,
        default=FIXED_SALT,
        help="Fixed salt for deterministic SHA256 hashing",
    )
    parser.add_argument(
        "--target-total",
        type=int,
        default=200,
        help="Target total candidates to generate",
    )

    args = parser.parse_args()

    generate_golden_set_candidates(
        input_path=args.input,
        output_candidates_path=args.output_candidates,
        exclusions_path=args.exclusions,
        salt=args.salt,
        target_total=args.target_total,
    )

if __name__ == "__main__":
    main()
