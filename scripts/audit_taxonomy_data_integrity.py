#!/usr/bin/env python3
"""
Data Integrity Audit Script for Intent Taxonomy Preparation.

Inspects target threads (spotify_root_784880, spotify_root_904057) and audits
the SpotifyCares dataset for third-party support agent crosstalk and structural anomalies.
"""

import json
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

TARGET_THREADS = ["spotify_root_784880", "spotify_root_904057"]

def audit_dataset(dataset_path):
    dataset_path = Path(dataset_path)
    if not dataset_path.exists():
        print(f"Error: {dataset_path} not found.", file=sys.stderr)
        sys.exit(1)

    print(f"Auditing data integrity on {dataset_path}...")

    found_targets = {}
    total_conversations = 0
    crosstalk_count = 0
    signoff_pattern = re.compile(r'\^[A-Z]{2}\b')

    crosstalk_threads = []

    with dataset_path.open('r', encoding='utf-8') as f:
        for line in f:
            if not line.strip():
                continue
            total_conversations += 1
            conv = json.loads(line)
            tid = conv.get('conversation_thread_id')
            if tid in TARGET_THREADS:
                found_targets[tid] = conv

            # Detect non-Spotify support signoffs in inbound messages
            inbound_signoffs = []
            for msg in conv.get('ordered_messages', []):
                if msg.get('inbound') and signoff_pattern.search(msg.get('text', '')):
                    inbound_signoffs.append((msg.get('author_id'), msg.get('text')))
            
            if inbound_signoffs:
                crosstalk_count += 1
                crosstalk_threads.append((tid, inbound_signoffs))

    print(f"Total conversations scanned: {total_conversations}")
    print(f"Target threads found: {len(found_targets)} / {len(TARGET_THREADS)}")
    print(f"Conversations with third-party support agent crosstalk: {crosstalk_count}")

    audit_results = {
        "total_conversations": total_conversations,
        "target_threads": {},
        "crosstalk_count": crosstalk_count
    }

    for tid in TARGET_THREADS:
        conv = found_targets.get(tid)
        if not conv:
            print(f"\n[FAIL] Thread {tid} not found!")
            continue

        print("\n" + "="*80)
        print(f"INSPECTING THREAD: {tid}")
        print("="*80)
        
        messages = conv.get('ordered_messages', [])
        print(f"Message Count: {len(messages)}")
        print(f"Conversation Depth: {conv.get('conversation_depth')}")
        print(f"Interaction Turn Count: {conv.get('customer_brand_interaction_turn_count')}")

        inbound_authors = set(m['author_id'] for m in messages if m['inbound'])
        outbound_authors = set(m['author_id'] for m in messages if not m['inbound'])

        print(f"Inbound Author IDs: {inbound_authors}")
        print(f"Outbound Author IDs: {outbound_authors}")

        has_crosstalk = any(signoff_pattern.search(m['text']) for m in messages if m['inbound'])
        print(f"Third-Party Agent Signoff Present in Inbound Messages: {has_crosstalk}")

        for i, m in enumerate(messages):
            print(f"  [{i}] ID={m['tweet_id']} | Author={m['author_id']} | Inbound={m['inbound']} | Text={m['text'][:100]}")

        # Assess suitability
        if tid == "spotify_root_784880":
            validity = "Structurally Impaired / Contaminated"
            suitability = "Unsuitable / High-Risk for direct retrieval grounding without message trimming. (Contains Capital One support agent 142798 signoffs ^IP/^DH misclassified as inbound customer messages)."
        elif tid == "spotify_root_904057":
            validity = "Partially Valid / Multi-Phase"
            suitability = "Requires Truncation. Turns 2-5 are high-quality retrieval grounding for 01_catalog_content_gap, but Turns 0-1 contain non-support social chatter ('Masaya ako' and handle 148611)."
        else:
            validity = "Unknown"
            suitability = "Unknown"

        audit_results["target_threads"][tid] = {
            "message_count": len(messages),
            "validity": validity,
            "suitability": suitability,
            "inbound_authors": list(inbound_authors)
        }

    return audit_results

if __name__ == "__main__":
    dataset_file = sys.argv[1] if len(sys.argv) > 1 else "data/processed/spotify_conversations.jsonl"
    audit_dataset(dataset_file)
