"""Conversation parsing and normalization for the Spotify customer support agent.

Provides robust ingestion and normalization for both single message strings
and multi-turn conversation threads (containing ordered_messages).
"""

from __future__ import annotations

from dataclasses import dataclass
import html
import re
from typing import Any, Dict, List, Optional, Sequence, Union


@dataclass(frozen=True)
class ParsedMessage:
    """Normalized representation of a single message/turn."""

    text: str
    clean_text: str
    author_id: Optional[str] = None
    is_inbound: bool = True
    created_at: Optional[str] = None
    tweet_id: Optional[str] = None
    conversation_depth: int = 0


@dataclass(frozen=True)
class ParsedConversation:
    """Structured representation of an entire conversation thread."""

    conversation_id: Optional[str]
    messages: tuple[ParsedMessage, ...]
    customer_messages: tuple[ParsedMessage, ...]
    agent_messages: tuple[ParsedMessage, ...]
    root_message: Optional[ParsedMessage]
    combined_customer_text: str
    is_multi_turn: bool
    customer_author_id: Optional[str]


def normalize_text(
    text: str,
    strip_handles: bool = False,
    strip_urls: bool = False,
    to_lower: bool = False,
) -> str:
    """Normalize raw message text.
    
    - Decodes HTML entities (e.g. &amp; -> &, &lt; -> <)
    - Optionally removes @mentions (e.g. @SpotifyCares, @123456)
    - Optionally removes URLs (e.g. https://t.co/...)
    - Collapses consecutive whitespace characters
    - Optionally converts to lowercase
    """
    if not isinstance(text, str):
        text = str(text or "")

    # Decode HTML entities
    normalized = html.unescape(text)

    # Optional URL removal
    if strip_urls:
        normalized = re.sub(r"https?://\S+", "", normalized)

    # Optional handle removal
    if strip_handles:
        normalized = re.sub(r"@\w+", "", normalized)

    # Collapse whitespace
    normalized = re.sub(r"\s+", " ", normalized).strip()

    if to_lower:
        normalized = normalized.lower()

    return normalized


def parse_message(
    raw_msg: Union[str, Dict[str, Any], ParsedMessage],
    default_inbound: bool = True,
) -> ParsedMessage:
    """Parse a single raw message string or dictionary into a ParsedMessage."""
    if isinstance(raw_msg, ParsedMessage):
        return raw_msg

    if isinstance(raw_msg, str):
        clean = normalize_text(raw_msg)
        is_inbound = default_inbound
        return ParsedMessage(
            text=raw_msg,
            clean_text=clean,
            author_id=None,
            is_inbound=is_inbound,
            created_at=None,
            tweet_id=None,
            conversation_depth=0,
        )

    if isinstance(raw_msg, dict):
        text = str(raw_msg.get("text", "") or "")
        clean = normalize_text(text)
        author_id = raw_msg.get("author_id")
        
        # Determine inbound/customer status
        inbound_val = raw_msg.get("inbound")
        if inbound_val is not None:
            is_inbound = bool(inbound_val)
        elif author_id == "SpotifyCares":
            is_inbound = False
        else:
            is_inbound = default_inbound

        tweet_id = str(raw_msg["tweet_id"]) if raw_msg.get("tweet_id") is not None else None
        created_at = raw_msg.get("created_at")
        depth = int(raw_msg.get("conversation_depth", 0) or 0)

        return ParsedMessage(
            text=text,
            clean_text=clean,
            author_id=str(author_id) if author_id is not None else None,
            is_inbound=is_inbound,
            created_at=str(created_at) if created_at is not None else None,
            tweet_id=tweet_id,
            conversation_depth=depth,
        )

    raise TypeError(f"Unsupported message type: {type(raw_msg).__name__}")


def parse_conversation(
    raw_input: Union[str, Dict[str, Any], Sequence[Any], ParsedConversation]
) -> ParsedConversation:
    """Parse an arbitrary conversation input into a canonical ParsedConversation.
    
    Accepts:
    1. A plain string message: "Why was I charged twice?"
    2. A conversation dictionary with 'ordered_messages' and optional 'conversation_id'
    3. A single message dictionary: {"text": "...", "inbound": True}
    4. A sequence of message strings or dictionaries
    5. An already parsed ParsedConversation (returned as-is)
    """
    if isinstance(raw_input, ParsedConversation):
        return raw_input

    conversation_id: Optional[str] = None
    parsed_messages: List[ParsedMessage] = []

    if isinstance(raw_input, str):
        parsed_messages.append(parse_message(raw_input, default_inbound=True))
    elif isinstance(raw_input, dict):
        conversation_id = raw_input.get("conversation_id")
        if "ordered_messages" in raw_input and isinstance(raw_input["ordered_messages"], list):
            for m in raw_input["ordered_messages"]:
                parsed_messages.append(parse_message(m))
        elif "text" in raw_input:
            parsed_messages.append(parse_message(raw_input))
        else:
            raise ValueError("Dictionary input must contain 'ordered_messages' or 'text'")
    elif isinstance(raw_input, (list, tuple)):
        for item in raw_input:
            parsed_messages.append(parse_message(item))
    else:
        raise TypeError(f"Unsupported input type for parse_conversation: {type(raw_input).__name__}")

    messages_tuple = tuple(parsed_messages)
    customer_msgs = tuple(m for m in messages_tuple if m.is_inbound)
    agent_msgs = tuple(m for m in messages_tuple if not m.is_inbound)

    # Determine root message (first customer inbound message, or first message overall)
    root_msg: Optional[ParsedMessage] = None
    if customer_msgs:
        root_msg = customer_msgs[0]
    elif messages_tuple:
        root_msg = messages_tuple[0]

    # Find primary customer author_id
    customer_author_id: Optional[str] = None
    for m in customer_msgs:
        if m.author_id and m.author_id != "SpotifyCares":
            customer_author_id = m.author_id
            break

    # Combined customer text for holistic intent detection
    combined_customer_text = " \n ".join(m.clean_text for m in customer_msgs if m.clean_text)

    is_multi_turn = len(messages_tuple) > 1 and len(customer_msgs) >= 1 and len(agent_msgs) >= 1

    return ParsedConversation(
        conversation_id=str(conversation_id) if conversation_id is not None else None,
        messages=messages_tuple,
        customer_messages=customer_msgs,
        agent_messages=agent_msgs,
        root_message=root_msg,
        combined_customer_text=combined_customer_text,
        is_multi_turn=is_multi_turn,
        customer_author_id=customer_author_id,
    )


def extract_inbound_query(conversation_input: Union[str, Dict[str, Any], ParsedConversation]) -> str:
    """Extract the primary customer inquiry text from a conversation input.
    
    If combined customer text exists, returns it; otherwise falls back to root message text.
    """
    conv = parse_conversation(conversation_input)
    if conv.combined_customer_text:
        return conv.combined_customer_text
    if conv.root_message:
        return conv.root_message.clean_text
    return ""
