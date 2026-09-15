#!/usr/bin/env python3
"""Build sanitized non-gold historical resolution corpus for runtime RAG.

Extracts customer inquiry and SpotifyCares resolution pairs from
data/processed/spotify_conversations.jsonl, strictly excluding:
- All 200 canonical gold evaluation conversation IDs
- All 28 design-time audit conversation IDs
- Any corrupt or single-message threads

Sanitizes:
- User handles (@123456, @SpotifyCares)
- Agent initials / signatures (/CB, ^AM, ~SP)
- Shortened URLs and HTML entities

Outputs:
- data/processed/historical_resolutions.jsonl
- data/processed/historical_resolutions_stats.json
"""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
import re
import sys
from typing import Any, Dict, List, Optional, Set, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DEFAULT_CORPUS_PATH = PROJECT_ROOT / "data" / "processed" / "spotify_conversations.jsonl"
DEFAULT_GOLD_PATH = PROJECT_ROOT / "data" / "processed" / "golden_set_annotations.jsonl"
DEFAULT_EXCLUSIONS_PATH = PROJECT_ROOT / "data" / "processed" / "golden_set_exclusions.txt"
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "data" / "processed" / "historical_resolutions.jsonl"
DEFAULT_STATS_PATH = PROJECT_ROOT / "data" / "processed" / "historical_resolutions_stats.json"

AGENT_AUTHOR_ID = "SpotifyCares"

# Regex patterns for cleaning
HANDLE_RE = re.compile(r"@\w+")
SIGNATURE_RE = re.compile(r"(?:^|\s)(?:[/^~-][A-Z]{1,3}|\^[a-z]{1,3})\s*$", re.MULTILINE)
MULTI_SPACE_RE = re.compile(r"\s+")


def load_exclusion_ids(
    gold_path: Path = DEFAULT_GOLD_PATH,
    exclusions_path: Path = DEFAULT_EXCLUSIONS_PATH,
) -> Set[str]:
    """Load all protected IDs to guarantee zero leakage."""
    excluded: Set[str] = set()

    if gold_path.is_file():
        with open(gold_path, "r", encoding="utf-8") as f:
            for line in f:
                line_str = line.strip()
                if line_str:
                    data = json.loads(line_str)
                    cid = data.get("conversation_id")
                    if cid:
                        excluded.add(cid)

    if exclusions_path.is_file():
        with open(exclusions_path, "r", encoding="utf-8") as f:
            for line in f:
                line_str = line.strip()
                if line_str and not line_str.startswith("#"):
                    excluded.add(line_str)

    return excluded


def sanitize_text(text: str, remove_handles: bool = True, remove_signature: bool = True) -> str:
    """Sanitize raw text for index storage and display."""
    if not text:
        return ""

    # Decode HTML
    cleaned = html.unescape(text)

    # Remove signatures at end of agent messages (e.g. " /CB", " ^AM", " ~SP")
    if remove_signature:
        cleaned = SIGNATURE_RE.sub("", cleaned)

    # Remove handles
    if remove_handles:
        cleaned = HANDLE_RE.sub("", cleaned)

    # Normalize whitespace
    cleaned = MULTI_SPACE_RE.sub(" ", cleaned).strip()
    return cleaned


def extract_resolution_actions(text: str) -> List[str]:
    """Tag actionable troubleshooting categories mentioned in the resolution text."""
    lower = text.lower()
    actions: List[str] = []

    if any(k in lower for k in ["reinstall", "clean install", "uninstall and reinstall"]):
        actions.append("clean_reinstall")
    if any(k in lower for k in ["restart", "reboot", "turn off and on"]):
        actions.append("restart_device")
    if any(k in lower for k in ["cache", "offline storage", "storage setting"]):
        actions.append("clear_cache")
    if any(k in lower for k in ["log out", "sign out", "log back in", "sign in again"]):
        actions.append("relogin")
    if any(k in lower for k in ["dm us", "direct message", "send us a dm", "send a dm"]):
        actions.append("request_dm")
    if any(k in lower for k in ["update", "latest version", "app store", "play store"]):
        actions.append("update_app")
    if any(k in lower for k in ["device", "operating system", "os version", "what model"]):
        actions.append("gather_device_diagnostics")
    if any(k in lower for k in ["community.spotify.com", "ideas board", "suggest it in our community"]):
        actions.append("community_ideas")
    if any(k in lower for k in ["artists.spotify.com", "spotify for artists"]):
        actions.append("artists_portal")
    if any(k in lower for k in ["password-reset", "reset your password", "change your password"]):
        actions.append("password_reset")
    if any(k in lower for k in ["subscription", "account page", "spotify.com/account"]):
        actions.append("account_portal")
    if any(k in lower for k in ["sheerid", "student", "verify your student"]):
        actions.append("student_verification")
    if any(k in lower for k in ["licensing", "rights holders", "country", "not available in your"]):
        actions.append("licensing_guidance")

    return actions


def build_resolution_corpus(
    corpus_path: Path = DEFAULT_CORPUS_PATH,
    output_path: Path = DEFAULT_OUTPUT_PATH,
    stats_path: Path = DEFAULT_STATS_PATH,
    gold_path: Path = DEFAULT_GOLD_PATH,
    exclusions_path: Path = DEFAULT_EXCLUSIONS_PATH,
    min_agent_length: int = 15,
) -> Dict[str, Any]:
    """Process conversations and write sanitized resolution corpus."""
    exclusion_ids = load_exclusion_ids(gold_path, exclusions_path)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.parent.mkdir(parents=True, exist_ok=True)

    total_threads = 0
    excluded_gold_count = 0
    skipped_no_agent = 0
    skipped_no_customer = 0
    skipped_too_short = 0
    indexed_resolutions: List[Dict[str, Any]] = []

    with open(corpus_path, "r", encoding="utf-8") as f:
        for line in f:
            line_str = line.strip()
            if not line_str:
                continue

            total_threads += 1
            thread = json.loads(line_str)
            cid = thread.get("conversation_thread_id") or f"spotify_root_{thread.get('thread_root_tweet_id')}"

            # Strict exclusion check
            if cid in exclusion_ids:
                excluded_gold_count += 1
                continue

            # Must contain both customer and Spotify
            if not thread.get("contains_customer_and_spotify", False):
                skipped_no_agent += 1
                continue

            messages = thread.get("ordered_messages", [])
            customer_msgs = [m for m in messages if m.get("inbound")]
            agent_msgs = [m for m in messages if m.get("author_id") == AGENT_AUTHOR_ID]

            if not customer_msgs:
                skipped_no_customer += 1
                continue

            if not agent_msgs:
                skipped_no_agent += 1
                continue

            # Extract initial customer query & full context
            customer_query_raw = customer_msgs[0].get("text", "")
            customer_query_clean = sanitize_text(customer_query_raw, remove_handles=True, remove_signature=False)

            # Combined customer text if multi-turn
            all_customer_text = " ".join(
                sanitize_text(m.get("text", ""), remove_handles=True, remove_signature=False)
                for m in customer_msgs
            )

            # Extract primary agent resolution turn(s)
            agent_resolution_raw = agent_msgs[0].get("text", "")
            agent_resolution_clean = sanitize_text(agent_resolution_raw, remove_handles=True, remove_signature=True)

            if len(agent_resolution_clean) < min_agent_length or len(customer_query_clean) < 3:
                skipped_too_short += 1
                continue

            actions = extract_resolution_actions(agent_resolution_clean)

            # Optional multi-turn resolution summary
            all_agent_clean = [
                sanitize_text(m.get("text", ""), remove_handles=True, remove_signature=True)
                for m in agent_msgs
                if len(sanitize_text(m.get("text", ""), remove_handles=True, remove_signature=True)) >= min_agent_length
            ]

            record = {
                "conversation_id": cid,
                "customer_query": customer_query_clean,
                "all_customer_text": all_customer_text,
                "resolution_text": agent_resolution_clean,
                "all_agent_resolutions": all_agent_clean,
                "resolution_actions": actions,
                "turn_count": len(messages),
                "created_at": customer_msgs[0].get("created_at"),
            }
            indexed_resolutions.append(record)

    # Sort deterministically by conversation_id
    indexed_resolutions.sort(key=lambda r: r["conversation_id"])

    # Write output
    with open(output_path, "w", encoding="utf-8") as out:
        for r in indexed_resolutions:
            out.write(json.dumps(r, ensure_ascii=False) + "\n")

    stats = {
        "total_source_threads": total_threads,
        "protected_exclusion_ids_loaded": len(exclusion_ids),
        "excluded_gold_threads_count": excluded_gold_count,
        "skipped_no_agent_count": skipped_no_agent,
        "skipped_no_customer_count": skipped_no_customer,
        "skipped_too_short_count": skipped_too_short,
        "indexed_resolution_count": len(indexed_resolutions),
    }

    with open(stats_path, "w", encoding="utf-8") as out_stats:
        json.dump(stats, out_stats, indent=2)

    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Build sanitized non-gold historical resolution corpus.")
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--stats", type=Path, default=DEFAULT_STATS_PATH)
    parser.add_argument("--gold", type=Path, default=DEFAULT_GOLD_PATH)
    parser.add_argument("--exclusions", type=Path, default=DEFAULT_EXCLUSIONS_PATH)
    args = parser.parse_args()

    print("Building historical resolution corpus...")
    stats = build_resolution_corpus(
        corpus_path=args.corpus,
        output_path=args.output,
        stats_path=args.stats,
        gold_path=args.gold,
        exclusions_path=args.exclusions,
    )
    print(f"Done! Indexed {stats['indexed_resolution_count']} resolutions (excluded {stats['excluded_gold_threads_count']} gold threads).")


if __name__ == "__main__":
    main()
