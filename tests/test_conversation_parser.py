import json
from pathlib import Path
import pytest

from src.spotify_agent.conversation_parser import (
    ParsedMessage,
    ParsedConversation,
    normalize_text,
    parse_message,
    parse_conversation,
    extract_inbound_query,
)


def test_normalize_text_html_entities():
    raw = "@SpotifyCares please put black silk back &amp; let us know &lt;3"
    norm = normalize_text(raw)
    assert "&amp;" not in norm
    assert "&" in norm
    assert "<3" in norm


def test_normalize_text_strip_handles_and_urls():
    raw = "@SpotifyCares @123456 please check https://t.co/xyz123 my account"
    norm = normalize_text(raw, strip_handles=True, strip_urls=True)
    assert "@SpotifyCares" not in norm
    assert "@123456" not in norm
    assert "https://t.co/xyz123" not in norm
    assert norm == "please check my account"


def test_parse_message_from_string():
    msg = parse_message("I cannot log in to Spotify")
    assert isinstance(msg, ParsedMessage)
    assert msg.text == "I cannot log in to Spotify"
    assert msg.clean_text == "I cannot log in to Spotify"
    assert msg.is_inbound is True
    assert msg.author_id is None


def test_parse_message_from_dict():
    raw_dict = {
        "tweet_id": "1001",
        "author_id": "SpotifyCares",
        "inbound": False,
        "created_at": "Fri Sep 08 03:22:00 +0000 2017",
        "text": "Hey there, we can help! /SU",
        "conversation_depth": 1,
    }
    msg = parse_message(raw_dict)
    assert isinstance(msg, ParsedMessage)
    assert msg.tweet_id == "1001"
    assert msg.author_id == "SpotifyCares"
    assert msg.is_inbound is False
    assert msg.conversation_depth == 1


def test_parse_conversation_from_string():
    conv = parse_conversation("Why was I charged twice?")
    assert isinstance(conv, ParsedConversation)
    assert len(conv.messages) == 1
    assert len(conv.customer_messages) == 1
    assert len(conv.agent_messages) == 0
    assert conv.root_message is not None
    assert conv.root_message.clean_text == "Why was I charged twice?"
    assert conv.combined_customer_text == "Why was I charged twice?"
    assert conv.is_multi_turn is False


def test_parse_conversation_from_ordered_messages():
    thread = {
        "conversation_id": "spotify_test_001",
        "ordered_messages": [
            {
                "tweet_id": "101",
                "author_id": "user_456",
                "inbound": True,
                "text": "@SpotifyCares my family plan invite link is broken",
                "conversation_depth": 0,
            },
            {
                "tweet_id": "102",
                "author_id": "SpotifyCares",
                "inbound": False,
                "text": "@user_456 Hey! Can you DM us your email? /SU https://t.co/abc",
                "conversation_depth": 1,
            },
            {
                "tweet_id": "103",
                "author_id": "user_456",
                "inbound": True,
                "text": "@SpotifyCares I already sent DM and no reply for 3 days",
                "conversation_depth": 2,
            },
        ],
    }

    conv = parse_conversation(thread)
    assert conv.conversation_id == "spotify_test_001"
    assert len(conv.messages) == 3
    assert len(conv.customer_messages) == 2
    assert len(conv.agent_messages) == 1
    assert conv.is_multi_turn is True
    assert conv.customer_author_id == "user_456"
    assert conv.root_message.tweet_id == "101"
    assert "family plan invite link is broken" in conv.combined_customer_text
    assert "no reply for 3 days" in conv.combined_customer_text

    # Extract inbound query
    query = extract_inbound_query(conv)
    assert "family plan invite link is broken" in query
    assert "no reply for 3 days" in query


def test_parse_golden_set_candidates_preserves_data():
    """Verify that parsing actual candidates works seamlessly without modifying candidates file."""
    candidates_path = Path("data/processed/golden_set_candidates.jsonl")
    assert candidates_path.exists()

    with candidates_path.open("r", encoding="utf-8") as f:
        for idx, line in enumerate(f):
            if idx >= 10:  # test first 10 candidate threads
                break
            if not line.strip():
                continue
            data = json.loads(line)
            conv = parse_conversation(data)
            assert conv.conversation_id == data["conversation_id"]
            assert len(conv.messages) == len(data["ordered_messages"])
            assert conv.root_message is not None
            assert extract_inbound_query(conv) != ""
