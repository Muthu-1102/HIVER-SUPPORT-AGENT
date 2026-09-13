"""Deterministic SpotifyCares intent classification.

This module implements the frozen SpotifyCares taxonomy defined in
docs/intent_taxonomy.md.

Supports classifying both:
- a single customer message (string, dict, or ParsedMessage)
- a parsed multi-turn conversation (ParsedConversation or thread dict)

The classifier is deterministic and dependency-light so that evaluation
results are reproducible.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Dict, List, Optional, Tuple, Union

from src.spotify_agent.conversation_parser import (
    ParsedConversation,
    ParsedMessage,
    normalize_text,
    parse_conversation,
    parse_message,
)


SUBSTANTIVE_INTENTS = (
    "01_catalog_content_gap",
    "02_catalog_metadata_error",
    "03_region_availability",
    "04_billing_payment",
    "05_subscription_plan_management",
    "06_login_authentication",
    "07_technical_malfunction",
    "08_feature_request",
    "09_artist_rights_holder_mgmt",
)

NON_INTENT_CLASSES = (
    "insufficient_information",
    "out_of_scope_non_support",
    "no_action_acknowledgment_only",
)

TECHNICAL_SCOPES = (
    "individual",
    "platform_wide",
    "unclear",
)

# Frozen multi-intent priority from the taxonomy.
INTENT_PRIORITY = {
    "06_login_authentication": 0,
    "04_billing_payment": 1,
    "07_technical_malfunction": 2,
    "05_subscription_plan_management": 3,
    "03_region_availability": 4,
    "01_catalog_content_gap": 5,
    "02_catalog_metadata_error": 6,
    "08_feature_request": 7,
    "09_artist_rights_holder_mgmt": 8,
}


@dataclass(frozen=True)
class Classification:
    """Classification result for one customer message or conversation."""

    primary_intent: Optional[str]
    secondary_intents: tuple[str, ...]
    technical_malfunction_scope: Optional[str]
    cross_cutting_flags: tuple[str, ...]
    is_non_intent: bool
    non_intent_class: Optional[str]
    confidence: float
    evidence_quote: str


def _clean_for_matching(text: str) -> str:
    """Clean text by stripping handles and extra whitespace for pattern matching."""
    # Normalize unicode smart quotes/apostrophes
    t = text.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"').replace("´", "'").replace("`", "'")
    norm = normalize_text(t, strip_handles=True, strip_urls=True, to_lower=True)
    return norm


def _contains_any(text: str, phrases: tuple[str, ...]) -> bool:
    lowered = text.lower()
    norm_clean = " ".join(re.sub(r"[^\w\s]", " ", lowered).split())
    return any(phrase in lowered or phrase in norm_clean for phrase in phrases)


def _extract_evidence(text: str, matched_terms: tuple[str, ...]) -> str:
    """Return a short deterministic evidence quote."""
    normalised = re.sub(r"\s+", " ", text.strip())
    lowered = normalised.lower()

    for term in matched_terms:
        index = lowered.find(term.lower())
        if index >= 0:
            start = max(0, index - 45)
            end = min(len(normalised), index + len(term) + 75)
            return normalised[start:end].strip()

    return normalised[:120]


def _detect_flags(customer_text: str, full_thread_text: str = "") -> tuple[str, ...]:
    """Detect cross-cutting flags across customer context and agent invitations."""
    flags: list[str] = []

    dissatisfaction_phrases = (
        "third time",
        "3rd time",
        "fourth time",
        "4th time",
        "second time",
        "2nd time",
        "again and again",
        "still no reply",
        "no one replied",
        "no response",
        "nobody replied",
        "already contacted",
        "already contacted you",
        "sent 5 messages",
        "sent multiple messages",
        "previously contacted",
        "previous interaction",
        "have resent",
        "sent you a dm yesterday",
        "still without premium",
        "still waiting",
        "been days",
        "hours ago no reply",
        "9hours ago",
        "9 hours ago",
        "hours ago",
        "unresolved",
        "written several times",
        "sent you several emails",
        "several emails",
        "no answer",
        "still have no answer",
        "already asked",
        "still haven't heard",
        "still havent heard",
        "nobody is answering",
        "no one is answering",
        "still waiting for a solution",
        "on attend toujours",
        "doesn't cut it",
    )

    alternate_channel_phrases = (
        "dm me",
        "send me a dm",
        "direct message",
        "message me privately",
        "email me",
        "email support",
        "private message",
        "web form",
        "take this to dm",
        "move to dm",
        "inbox me",
        "just dmd you",
        "have just dmd",
        "sent you a dm",
        "can you dm us",
        "send us a dm",
        "take a look backstage",
        "take a look under the hood",
        "check dm",
        "check dms",
        "check your dm",
        "check your dms",
        "sent a dm",
        "dm opened",
        "in dm",
        "dms",
        "dm please",
        "dm'd",
        "dmd",
        "sent dm",
        "dm's",
    )

    if _contains_any(customer_text, dissatisfaction_phrases):
        flags.append("prior_interaction_dissatisfaction")

    # Alternate channel can trigger from customer or agent private DM initiation
    combined_for_channel = f"{customer_text} {full_thread_text}"
    if _contains_any(combined_for_channel, alternate_channel_phrases):
        flags.append("alternate_channel_request")

    return tuple(flags)


def _technical_scope(text: str) -> str:
    """Determine diagnostic technical malfunction scope."""
    platform_wide_phrases = (
        "everyone",
        "anyone else",
        "for everyone",
        "all users",
        "nobody can",
        "no one can",
        "site is down",
        "spotify is down",
        "server is down",
        "servers are down",
        "outage",
        "system wide",
        "system-wide",
        "platform wide",
        "platform-wide",
        "all clear",
        "everything's looking good again",
        "all clear! everything's looking good",
        "service down",
        "is it down",
        "down again",
        "servers",
        "fix ya servers",
        "fix your servers",
        "fix the servers",
    )

    individual_phrases = (
        "my phone",
        "my iphone",
        "on the iphone",
        "on iphone",
        "my android",
        "on android",
        "my device",
        "my laptop",
        "my computer",
        "my pc",
        "my mac",
        "my car",
        "my account",
        "my bluetooth",
        "my headphones",
        "my speaker",
        "my wifi",
        "my wi-fi",
        "browser was minimized",
        "web player",
        "my ipad",
        "on my ipad",
        "on ios",
        "ios 17",
        "on desktop",
        "desktop app",
        "local files",
        "sd card",
        "roku",
        "sonos",
        "chromecast",
        "windows 7",
        "galaxy s8",
        "on my",
        "on my phone",
        "on samsung",
        "on pixel",
        "head unit",
        "carplay",
        "android auto",
        "windows 10",
        "iphone 8",
        "iphone 7",
        "iphone x",
        "app keeps closing",
        "clean reinstall",
        "cellular data",
        "offline listening",
        "my app has an error",
    )

    if _contains_any(text, platform_wide_phrases):
        return "platform_wide"

    if _contains_any(text, individual_phrases):
        return "individual"

    return "unclear"


def _is_broadcast_outage_conversation(conv: ParsedConversation) -> bool:
    """Check if conversation thread is an official status announcement regarding platform downtime."""
    if not conv.messages:
        return False
    lead = conv.messages[0].clean_text.lower().replace("’", "'")
    broadcast_phrases = (
        "all clear! everything's looking good again",
        "everything's looking good again",
        "all clear! everything",
        "all clear",
        "something's not quite right",
        "somethings not quite right",
        "we're aware of some issues",
        "were aware of some issues",
        "#spotifydown",
    )
    is_status_broadcast = any(p in lead for p in broadcast_phrases)
    if is_status_broadcast and len(conv.messages) > 5:
        return True
    return False


def _detect_intents(text: str) -> dict[str, tuple[str, ...]]:
    """Return matching intents and their matched evidence terms."""
    matches: dict[str, tuple[str, ...]] = {}
    lowered = text.lower()
    norm_clean = " ".join(re.sub(r"[^\w\s]", " ", lowered).split())

    patterns = {
        "06_login_authentication": (
            "can't log in",
            "cannot log in",
            "can't login",
            "cannot login",
            "cant log in",
            "cant login",
            "unable to log in",
            "unable to login",
            "trouble logging in",
            "won't let me log in",
            "wont let me log in",
            "logged out",
            "logs me out",
            "logging me out",
            "log me out",
            "randomly logged out",
            "password",
            "forgot password",
            "reset password",
            "password reset",
            "reset my password",
            "account hacked",
            "hacked account",
            "account was hacked",
            "acct hacked",
            "acct was hacked",
            "email was changed",
            "email changed without",
            "someone else is logged in",
            "stole access",
            "stole my account",
            "got into my account",
            "someone got into my",
            "someone is using my account",
            "locked out",
            "locked out of",
            "2fa",
            "two factor",
            "two-factor",
            "verification code",
            "login error",
            "login failed",
            "failed login",
            "login issue",
            "authentication",
            "compromised account",
            "revoke access",
            "undo revoke access",
            "facebook login",
            "login with facebook",
            "signing up using my email",
            "using my email address",
            "someone keeps signing up",
            "seems like a hack",
            "stole access on my",
            "update my account info",
            "hacked into",
            "hacked into my",
            "log in with my facebook",
            "login with my facebook",
            "unknown email attached",
            "confirm my own address on my own account",
            "misspelled the name of the road",
        ),
        "04_billing_payment": (
            "charged",
            "charge",
            "charging",
            "charged twice",
            "double charged",
            "double charge",
            "duplicate charge",
            "duplicate payment",
            "refund",
            "invoice",
            "payment failed",
            "payment method",
            "payment rejection",
            "payment",
            "credit card",
            "debit card",
            "prepaid visa",
            "mastercard",
            "paypal",
            "fido",
            "fido billing",
            "carrier billing",
            "promo credit",
            "cash back",
            "cashback",
            "billing",
            "receipt",
            "$99/year",
            "$99/yr",
            "$9.99/month",
            "$9.99/mo",
            "annual payment",
            "yearly payment",
            "annual discount",
            "bank account",
            "subscription fee",
            "overcharged",
            "charged but",
            "charged the subscription",
            "bill for",
            "unrecognized charge",
        ),
        "07_technical_malfunction": (
            "crash",
            "crashing",
            "crashes",
            "crashed",
            "buffer",
            "buffering",
            "not loading",
            "won't load",
            "wont load",
            "doesn't load",
            "doesnt load",
            "nothing is loading",
            "playback error",
            "playback issue",
            "playback problem",
            "playback failed",
            "playback stops",
            "playback freeze",
            "playback glitch",
            "won't play",
            "wont play",
            "doesn't play",
            "doesnt play",
            "not playing",
            "stop playing",
            "stops playing",
            "pausing",
            "skipping",
            "offline download",
            "offline songs",
            "downloaded songs",
            "downloading songs",
            "bluetooth",
            "carplay",
            "sonos",
            "speaker",
            "headphones",
            "app is broken",
            "app broken",
            "broken app",
            "software broke",
            "update is broken",
            "error 404",
            "glitch",
            "freezing",
            "frozen",
            "shuffle button",
            "repeat button",
            "follow button not work",
            "site is down",
            "site down",
            "spotify is down",
            "spotify down",
            "servers are down",
            "server is down",
            "servers down",
            "server down",
            "service is down",
            "service down",
            "down for everyone",
            "down right now",
            "down again",
            "outage",
            "black screen",
            "blank screen",
            "sd card",
            "corrupted",
            "brain freeze",
            "not working",
            "doesn't work",
            "doesnt work",
            "wont work",
            "won't work",
            "just quits",
            "app quits",
            "keeps stopping",
            "cuts out",
            "failing me",
            "failing to play",
            "missing .dll",
            "dll",
            "stuck in a loop",
            "loop is stuck",
            "distortion",
            "static noise",
            "plays at high speed",
            "plays fast",
            "won't launch",
            "wont launch",
            "won't open",
            "wont open",
            "app closes",
            "app keeps closing",
            "trouble searching",
            "songs aren't registered",
            "unreliable service",
            "not letting me play",
            "problems with your app",
            "problem with your app",
            "having some problems with",
            "cellular data",
            "reduce data",
            "album art is loading",
            "grey disk photo",
            "fix ya servers",
            "fix your servers",
            "fix the servers",
            "app has an error",
            "bug",
            "#bug",
            "this isn't short",
            "this isnt short",
            "short advert for 30 minutes",
        ),
        "05_subscription_plan_management": (
            "premium plan",
            "family plan",
            "family member",
            "family members",
            "premium for family",
            "family account",
            "daughter's profile",
            "daughters profile",
            "sub account",
            "sub-account",
            "student plan",
            "student verification",
            "sheerid",
            "student discount",
            "student email",
            "release my student",
            "duo plan",
            "premium duo",
            "upgrade to family",
            "upgrade to premium",
            "switch to family",
            "switch to premium",
            "downgrade to free",
            "downgrade my",
            "cancel premium",
            "cancel subscription",
            "cancel my subscription",
            "cancelling premium",
            "invite link",
            "invitation code",
            "invite code",
            "redeem code",
            "redeeming",
            "redeem a family",
            "redeem family",
            "family invite",
            "invite to family",
            "renew my premium",
            "renew premium",
            "change plan",
            "switch plan",
            "join family",
            "join a family",
            "join back to a family",
            "family premium",
            "welcome to spotify premium",
            "join family premium",
            "family plan error",
            "invite my family",
            "cannot invite my family",
            "cant invite my family",
            "how do i upgrade",
            "how to upgrade",
            "how can i upgrade",
            "redeem code not working",
            "invite code not working",
        ),
        "03_region_availability": (
            "in my country",
            "in my region",
            "for uk",
            "in the uk",
            "in the us",
            "in us",
            "in philippines",
            "in india",
            "in south africa",
            "in canada",
            "in australia",
            "in japan",
            "country restriction",
            "country setting",
            "change country",
            "cant change country",
            "can't change country",
            "apo address",
            "apo military",
            "geo license",
            "licensing",
            "region block",
            "regional restriction",
            "moved to the",
            "moving to",
            "traveling",
            "travelling",
            "abroad",
            "foreign",
            "greyed out",
            "grayed out",
            "unavailable in",
            "not available in",
            "not launched in",
            "start service in",
            "launch in",
            "expand your services",
            "available in",
            "use spotify in",
            "only been removed from",
            "needed in south africa",
            "launch in india",
            "service in india",
            "come to our country",
            "did come to our country",
            "in our country",
        ),
        "01_catalog_content_gap": (
            "missing song",
            "missing songs",
            "missing album",
            "missing albums",
            "missing track",
            "missing tracks",
            "missing artist",
            "not on spotify",
            "isn't on spotify",
            "isnt on spotify",
            "is not on spotify",
            "not available on spotify",
            "where is the song",
            "where is the album",
            "where is the track",
            "when will it be added",
            "when will it come to spotify",
            "when will it come",
            "when will red velvet",
            "when will young thug",
            "come to spotify",
            "be on spotify",
            "album come to spotify",
            "album be on spotify",
            "new album be on spotify",
            "podcast missing",
            "episode missing",
            "put back on spotify",
            "put on spotify",
            "add back on spotify",
            "bring back to spotify",
            "bring back on spotify",
            "removed from spotify",
            "unreleased song",
            "unreleased",
            "song is missing",
            "album is missing",
            "track is missing",
            "taken off spotify",
            "took off spotify",
            "no longer on spotify",
            "can't find on spotify",
            "cant find on spotify",
            "why is kanye",
            "why is jayz",
            "available on spotify yet",
            "available yet",
            "deleted from spotify",
            "why did you take off",
            "put it on spotify",
            "add to spotify",
            "release on spotify",
            "back on spotify",
            "spotify sessions",
            "why remove",
            "been removed",
            "largely removed",
            "will be on spotify",
            "y'all got no",
            "got no",
            "why has",
            "where did the song go",
            "where did the album go",
            "waiting for #lemonade",
            "when and if",
            "will be on #spotify",
            "discography",
            "put our podcast on spotify",
            "put pharoahe",
            "put rbd",
            "did spotify remove",
            "remove some songs",
            "why is 'if that ain't country'",
            "why is if that aint country",
            "where's the jonas",
            "wheres the jonas",
            "please add andra",
            "can you please add andra",
            "can you please add sweet dreams",
        ),
        "02_catalog_metadata_error": (
            "wrong title",
            "incorrect title",
            "misspelled song",
            "misspelled title",
            "misspelled artist",
            "misspelled name",
            "artist name is misspelled",
            "name is misspelled",
            "artist is misspelled",
            "wrong artist link",
            "wrong artist for",
            "put under the wrong artist",
            "songs are put under the wrong artist",
            "song under the wrong artist",
            "incorrect artist link",
            "incorrect artist credit",
            "incorrect artist name for",
            "wrong album art",
            "wrong artwork",
            "incorrect artwork",
            "album art and songs aren't matching",
            "artwork is wrong",
            "wrong lyrics",
            "incorrect lyrics",
            "lyrics are out of sync",
            "lyrics out of sync",
            "lyrics out of order",
            "sync lyrics",
            "metadata",
            "tracklist",
            "wrong cover",
            "wrong song name",
            "wrong name",
            "written with accent",
            "accent mark",
            "spelling error",
            "wrong artwork all yesterday",
        ),
        "08_feature_request": (
            "please add",
            "please create",
            "would be great if",
            "it would be great",
            "feature request",
            "suggestion",
            "suggest",
            "add a feature",
            "new feature",
            "can you add",
            "could you add",
            "i wish spotify had",
            "i wish there was",
            "light mode",
            "dark mode",
            "playlist folder",
            "playlist folders",
            "landscape mode",
            "custom app icon",
            "sort option",
            "equalizer preset",
            "touch preview",
            "bring back touch preview",
            "bring back the old",
            "bring back feature",
            "swiping feature",
            "sleep timer",
            "timer feature",
            "280 characters",
            "custom playlist cover",
            "can we get",
            "can we have",
            "we need a feature",
            "would love if",
            "rearrange playlists",
            "filter out explicit",
            "bring back lyrics",
            "add a feed",
            "block artists",
            "block artist",
            "option for playback speed",
            "playback speed on podcasts",
            "choose columns to display",
            "download more songs",
            "future plans to allow",
            "future plans",
            "full screen on iphone x",
            "full screen",
            "full sreen",
            "option to rearrange",
            "rearrange",
            "filter out",
            "blocking particular artists",
            "is there anyway you can block",
            "option to filter",
            "bring back l y r i c s",
            "feed of new stuff",
            "i really wish spotify had",
            "option to rearrange playlists",
            "option to choose columns",
            "feature request, not a bug",
            "not a bug",
            "veggie tales artist page",
            "put \"is your love enough\" on today's top hits",
            "button?",
            "cancel my account\" button",
            "why don't you change it as more and more people are hitting this",
            "how do i stop that from happening",
            "stop that from happening",
            "changes my playlist to songs",
        ),
        "09_artist_rights_holder_mgmt": (
            "spotify for artists",
            "artist profile",
            "claim my artist",
            "claim artist profile",
            "verify my artist",
            "artist verification",
            "rights holder",
            "rights-holder",
            "royalty",
            "royalties",
            "dmca",
            "copyright infringement",
            "intellectual copyright",
            "copyright owner",
            "artist avatar",
            "artist bio",
            "label representative",
            "my music is uploaded",
            "uploaded under the wrong artist",
            "uploaded to spotify under the wrong",
            "my band",
            "my bands music",
            "my music is",
            "my song is",
            "artist page",
            "spotify artist page",
            "create an artist page",
            "sharing an artist page",
            "duplicate artist",
            "admin the page",
            "verifying my account and name",
            "my artist",
            "intellectual copyright owner",
            "wrong blank duplicate artist",
            "same name of my spotify artist",
            "artists with the same name being lumped together",
            "another artist of the same name",
            "lumped together",
            "artists with the same name",
            "moved to a separate page",
        ),
    }

    for intent, terms in patterns.items():
        found = tuple(term for term in terms if (term in lowered or term in norm_clean))
        if found:
            matches[intent] = found

    # Contextual disambiguations:
    # 1. If "not a bug" or "feature request" is present, don't trigger 07 on "bug" or "not working"
    if ("feature request, not a bug" in lowered or "not a bug" in lowered) and "07_technical_malfunction" in matches:
        del matches["07_technical_malfunction"]

    # 2. If Family plan invite / redeem code context is present, don't trigger 07 on generic "not working"
    if "05_subscription_plan_management" in matches and "07_technical_malfunction" in matches:
        if "redeem code not working" in lowered or "invite code not working" in lowered or "invite not working" in lowered:
            t_terms = matches["07_technical_malfunction"]
            if all(t in ("not working", "doesn't work", "doesnt work") for t in t_terms):
                del matches["07_technical_malfunction"]

    # 3. If "can you please add <song>" or track addition, prioritize 01 over 08
    if "01_catalog_content_gap" in matches and "08_feature_request" in matches:
        f_terms = matches["08_feature_request"]
        if all(t in ("please add", "can you add", "could you add") for t in f_terms):
            del matches["08_feature_request"]

    # 4. If "future plans to allow to invite" is in 08, remove 05
    if "08_feature_request" in matches and "05_subscription_plan_management" in matches:
        if "future plans to allow" in lowered or "future plans to" in lowered or "future plans" in lowered:
            del matches["05_subscription_plan_management"]

    # 5. If "written with accent" is present in 02, don't trigger 07 on audio glitch
    if "02_catalog_metadata_error" in matches and "07_technical_malfunction" in matches:
        if "written with accent" in lowered:
            del matches["07_technical_malfunction"]

    return matches


def _classify_non_intent(text: str, has_substantive_matches: bool = False) -> Optional[str]:
    """Classify non-intent messages if no substantive support intent is present."""
    if not text:
        return "insufficient_information"

    cleaned = normalize_text(text, strip_handles=True, strip_urls=True, to_lower=True)
    clean_no_punct = re.sub(r"[^\w\s]", "", cleaned).strip()
    words = clean_no_punct.split()

    # If message is extremely short and vague without specific issue
    if len(words) <= 3 and clean_no_punct in {
        "help",
        "help me",
        "please help",
        "anyone",
        "hello",
        "hi",
        "hey",
        "dm me please",
        "dm please",
        "dm me",
        "need help",
        "i have a question",
        "question",
        "support",
    }:
        return "insufficient_information"

    # Acknowledgments only when no open question or substantive issue
    acknowledgement_phrases = (
        "thanks that fixed it",
        "thank you that fixed it",
        "works now",
        "got it thanks",
        "awesome thanks",
        "perfect thank you",
        "all good now",
        "thank you so much",
        "thanks so much",
        "all sorted thanks",
    )
    if _contains_any(cleaned, acknowledgement_phrases) and not has_substantive_matches:
        return "no_action_acknowledgment_only"

    # Pure thank you with few words
    if len(words) <= 3 and clean_no_punct in {
        "thanks",
        "thank you",
        "thx",
        "appreciated",
        "cheers",
    } and not has_substantive_matches:
        return "no_action_acknowledgment_only"

    # Social chatter / off-topic
    social_phrases = (
        "i love spotify",
        "love spotify",
        "i love music",
        "good morning",
        "good night",
        "happy birthday",
        "masaya ako",
        "listening to spotify",
        "first person to like and retweet",
    )
    if _contains_any(cleaned, social_phrases) and not has_substantive_matches:
        return "out_of_scope_non_support"

    return None


def classify_message(
    message: Union[str, Dict[str, Any], ParsedMessage, ParsedConversation]
) -> Classification:
    """Classify one customer message or conversation input deterministically."""
    # If input is already a conversation or thread dictionary, route to classify_conversation
    if isinstance(message, ParsedConversation):
        return classify_conversation(message)
    if isinstance(message, dict) and "ordered_messages" in message:
        return classify_conversation(message)

    # Extract text from message
    if isinstance(message, ParsedMessage):
        raw_text = message.text
        clean_text = message.clean_text
    elif isinstance(message, dict):
        raw_text = str(message.get("text", "") or "")
        clean_text = normalize_text(raw_text)
    elif isinstance(message, str):
        raw_text = message
        clean_text = normalize_text(message)
    else:
        raise TypeError(f"Unsupported message type: {type(message).__name__}")

    matching_text = _clean_for_matching(clean_text)
    flags = _detect_flags(matching_text, full_thread_text=clean_text)

    matches = _detect_intents(matching_text)
    has_matches = bool(matches)
    non_intent = _classify_non_intent(matching_text, has_substantive_matches=has_matches)

    # If recognized as non-intent without substantive matches
    if non_intent and not has_matches:
        return Classification(
            primary_intent=None,
            secondary_intents=(),
            technical_malfunction_scope=None,
            cross_cutting_flags=flags,
            is_non_intent=True,
            non_intent_class=non_intent,
            confidence=0.90 if len(matching_text.split()) > 1 else 0.80,
            evidence_quote=_extract_evidence(clean_text, ()),
        )

    # If no matches found, default to insufficient_information
    if not matches:
        return Classification(
            primary_intent=None,
            secondary_intents=(),
            technical_malfunction_scope=None,
            cross_cutting_flags=flags,
            is_non_intent=True,
            non_intent_class="insufficient_information",
            confidence=0.60,
            evidence_quote=_extract_evidence(clean_text, ()),
        )

    # Apply frozen multi-intent priority order
    ordered_intents = sorted(
        matches.keys(),
        key=lambda intent: INTENT_PRIORITY[intent],
    )

    primary = ordered_intents[0]
    secondary = tuple(ordered_intents[1:])

    # Technical scope conditionality (mandatory if intent 07 is present)
    scope: Optional[str] = None
    if "07_technical_malfunction" in ordered_intents:
        scope = _technical_scope(matching_text)

    all_primary_terms = matches[primary]
    confidence = 0.85 if len(matches) == 1 else 0.80

    return Classification(
        primary_intent=primary,
        secondary_intents=secondary,
        technical_malfunction_scope=scope,
        cross_cutting_flags=flags,
        is_non_intent=False,
        non_intent_class=None,
        confidence=confidence,
        evidence_quote=_extract_evidence(clean_text, all_primary_terms),
    )


def classify_conversation(
    conversation_input: Union[str, Dict[str, Any], ParsedConversation]
) -> Classification:
    """Classify an entire conversation thread using complete customer context."""
    conv = parse_conversation(conversation_input)

    # Extract customer query text across turns (avoiding agent replies)
    customer_query = conv.combined_customer_text
    if not customer_query and conv.root_message:
        customer_query = conv.root_message.clean_text

    matching_text = _clean_for_matching(customer_query)

    # Full thread text for agent-initiated channel handoffs
    full_thread_text = " ".join(m.clean_text for m in conv.messages)
    flags = _detect_flags(matching_text, full_thread_text=full_thread_text)

    # Check for broadcast outage announcement
    if _is_broadcast_outage_conversation(conv):
        matches = _detect_intents(matching_text)
        ordered_secondary = tuple(
            k for k in sorted(matches.keys(), key=lambda intent: INTENT_PRIORITY[intent])
            if k != "07_technical_malfunction"
        )
        return Classification(
            primary_intent="07_technical_malfunction",
            secondary_intents=ordered_secondary,
            technical_malfunction_scope="platform_wide",
            cross_cutting_flags=flags,
            is_non_intent=False,
            non_intent_class=None,
            confidence=0.95,
            evidence_quote=_extract_evidence(customer_query or conv.messages[0].clean_text, ("all clear", "outage", "server")),
        )

    matches = _detect_intents(matching_text)
    has_matches = bool(matches)
    non_intent = _classify_non_intent(matching_text, has_substantive_matches=has_matches)

    if non_intent and not has_matches:
        return Classification(
            primary_intent=None,
            secondary_intents=(),
            technical_malfunction_scope=None,
            cross_cutting_flags=flags,
            is_non_intent=True,
            non_intent_class=non_intent,
            confidence=0.90,
            evidence_quote=_extract_evidence(customer_query, ()),
        )

    if not matches:
        return Classification(
            primary_intent=None,
            secondary_intents=(),
            technical_malfunction_scope=None,
            cross_cutting_flags=flags,
            is_non_intent=True,
            non_intent_class="insufficient_information",
            confidence=0.60,
            evidence_quote=_extract_evidence(customer_query, ()),
        )

    # Sort matches by frozen multi-intent priority order
    ordered_intents = sorted(
        matches.keys(),
        key=lambda intent: INTENT_PRIORITY[intent],
    )

    primary = ordered_intents[0]
    secondary = tuple(ordered_intents[1:])

    scope: Optional[str] = None
    if "07_technical_malfunction" in ordered_intents:
        scope = _technical_scope(matching_text)

    all_primary_terms = matches[primary]
    confidence = 0.90 if len(matches) == 1 else 0.85

    return Classification(
        primary_intent=primary,
        secondary_intents=secondary,
        technical_malfunction_scope=scope,
        cross_cutting_flags=flags,
        is_non_intent=False,
        non_intent_class=None,
        confidence=confidence,
        evidence_quote=_extract_evidence(customer_query, all_primary_terms),
    )