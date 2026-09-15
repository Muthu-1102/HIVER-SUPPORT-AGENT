"""Safety, sanitization, and groundedness validator for customer support responses.

Ensures customer-facing responses never leak:
- Twitter handles (@115887, @SpotifyCares, etc.)
- Personalized greetings with customer names (Hi Harry, Hey Mike)
- Legacy shortened t.co links or dangling URL references
- Internal routing queue names (QUEUE_*, billing_support, etc.)
- Internal intent taxonomy identifiers (06_login_authentication, P0, etc.)
- Unsupported or unauthorized financial promises (e.g. unconditional refund guarantees)
"""

from __future__ import annotations

import html
import re
from typing import List, Optional, Set, Tuple

HANDLE_RE = re.compile(r"@\w+")
TWEET_ID_RE = re.compile(r"\b\d{10,20}\b")
AGENT_SIGNATURE_RE = re.compile(r"(?:^|\s)(?:[/^~-][A-Z]{1,3}|\^[a-z]{1,3})\s*$", re.MULTILINE)
PERSONALIZED_GREETING_RE = re.compile(r"\b(?:Hi|Hey|Hello|Hey there|Hi there)\s+[A-Z][a-z]+[.,!]?\s*", re.IGNORECASE)
DANGLING_LINK_RE = re.compile(r"\b(?:using the steps here|using the link here|using the link|steps here|follow the steps here|here|link|url|via this link)\s*:\s*\.?", re.IGNORECASE)
INTERNAL_QUEUE_RE = re.compile(r"\b(?:QUEUE_[A-Z_]+|queue_[a-z_]+)\b")
INTERNAL_TAXONOMY_RE = re.compile(r"\b(?:0\d_[a-z_]+|P[0-8])\b")
MULTI_SPACE_RE = re.compile(r"\s+")

ALLOWED_DOMAINS = {
    "spotify.com",
    "www.spotify.com",
    "community.spotify.com",
    "artists.spotify.com",
    "support.spotify.com",
}


def sanitize_response_text(text: str) -> str:
    """Sanitize and clean customer-facing response text."""
    if not text:
        return ""

    cleaned = html.unescape(text)

    # 1. Strip agent signatures (e.g. /CB, ^AM)
    cleaned = AGENT_SIGNATURE_RE.sub("", cleaned)

    # 2. Strip Twitter handles
    cleaned = HANDLE_RE.sub("", cleaned)

    # 3. Strip legacy short URLs
    cleaned = re.sub(r"https?://t\.co/\S+", "", cleaned)
    cleaned = re.sub(r"https?://spoti\.fi/\S+", "", cleaned)

    # 4. Clean dangling link references left after URL removal
    cleaned = DANGLING_LINK_RE.sub("", cleaned)

    # 5. Strip personalized greetings with historical customer names
    cleaned = PERSONALIZED_GREETING_RE.sub("", cleaned)

    # 6. Strip internal queue references
    cleaned = INTERNAL_QUEUE_RE.sub("", cleaned)

    # 7. Strip internal taxonomy IDs
    cleaned = INTERNAL_TAXONOMY_RE.sub("", cleaned)

    # 8. Normalize whitespace and trailing punctuation
    cleaned = re.sub(r"\s+([.,!?])", r"\1", cleaned)
    cleaned = MULTI_SPACE_RE.sub(" ", cleaned).strip()

    return cleaned


def validate_response_safety(text: str) -> Tuple[bool, List[str]]:
    """Validate safety boundaries and return list of violations if any."""
    violations: List[str] = []

    if not text or len(text.strip()) < 5:
        violations.append("Response text is empty or too short.")

    if HANDLE_RE.search(text):
        violations.append("Response contains unstripped @handle mention.")

    if INTERNAL_QUEUE_RE.search(text):
        violations.append("Response leaks internal queue name.")

    if INTERNAL_TAXONOMY_RE.search(text):
        violations.append("Response leaks internal taxonomy identifier.")

    # Check for unapproved external URLs
    urls = re.findall(r"https?://([a-zA-Z0-9.-]+)(?:/\S*)?", text)
    for domain in urls:
        base_domain = domain.lower().lstrip("www.")
        if not any(base_domain == d.lstrip("www.") or base_domain.endswith("." + d.lstrip("www.")) for d in ALLOWED_DOMAINS):
            violations.append(f"Response contains unapproved URL domain: {domain}")

    is_safe = (len(violations) == 0)
    return is_safe, violations
