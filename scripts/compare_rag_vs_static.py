"""Head-to-head comparison of Static Template Responses vs. Runtime Historical RAG Responses.

Demonstrates:
- Side-by-side response text comparison
- Retrieved evidence provenance (conversation ID, similarity score, action tags)
- Graceful fallback on ambiguous or ungrounded queries
- Execution latency profiling
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
import time
from typing import Any, Dict, List

# Ensure utf-8 stdout on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.spotify_agent.agent import SpotifySupportAgent

TEST_QUERIES = [
    {
        "name": "Technical Playback Glitch (iPhone / Cache)",
        "message": "The repeat and shuffle buttons keep freezing on my iPhone app whenever I play downloaded songs.",
    },
    {
        "name": "Billing & Double Charge",
        "message": "I noticed two identical charges of $10.99 for Spotify Premium on my bank statement this month.",
    },
    {
        "name": "Student Plan SheerID Verification",
        "message": "My student discount verification link failed on SheerID. How can I renew my student status?",
    },
    {
        "name": "Content Licensing / Regional Availability",
        "message": "Why is this song greyed out and unplayable in the UK when it worked in the US?",
    },
    {
        "name": "Feature Request / Suggestion",
        "message": "Could you add a custom sleep timer directly to the desktop playlist view?",
    },
    {
        "name": "Account Compromise / Security",
        "message": "Someone changed my account email and I cannot log in or reset password. My account was hacked!",
    },
    {
        "name": "Dissatisfaction Escalation (Hard Override)",
        "message": "This is the 4th time I am contacting you and nobody has responded. Fix this immediately!",
    },
    {
        "name": "Private DM Request (Hard Override)",
        "message": "Please send me a DM so I can share my private account email safely.",
    },
]


def compare_systems() -> None:
    agent_static = SpotifySupportAgent(enable_retrieval=False)
    agent_rag = SpotifySupportAgent(enable_retrieval=True)

    print("=" * 80)
    print("SPOTIFY SUPPORT AGENT: STATIC BASELINE vs. RUNTIME RAG COMPARISON")
    print("=" * 80)

    for q in TEST_QUERIES:
        name = q["name"]
        msg = q["message"]

        # Run static
        t0 = time.perf_counter()
        res_static = agent_static.process_message(msg)
        static_time_ms = (time.perf_counter() - t0) * 1000

        # Run RAG
        t1 = time.perf_counter()
        res_rag = agent_rag.process_message(msg)
        rag_time_ms = (time.perf_counter() - t1) * 1000

        print(f"\n[Scenario: {name}]")
        print(f"Customer: \"{msg}\"")
        print(f"Predicted Intent: {res_rag.classification.primary_intent} | Queue: {res_rag.target_queue}")
        print("-" * 80)
        print(f"STATIC ({static_time_ms:.2f} ms) [{res_static.grounding_source}]:")
        print(f"  \"{res_static.text}\"")
        print(f"\nRAG ({rag_time_ms:.2f} ms) [{res_rag.grounding_source}]:")
        print(f"  \"{res_rag.text}\"")

        if res_rag.retrieved_evidence:
            top_ev = res_rag.retrieved_evidence[0]
            print(f"  Evidence Provenance: Conv ID={top_ev.conversation_id} | Similarity={top_ev.similarity_score:.4f}")
            print(f"  Extracted Actions: {top_ev.resolution_actions}")
            safe_snippet = top_ev.resolution_text[:120].encode('ascii', 'replace').decode('ascii')
            print(f"  Historical Precedent Excerpt: \"{safe_snippet}...\"")
        print("=" * 80)


if __name__ == "__main__":
    compare_systems()
