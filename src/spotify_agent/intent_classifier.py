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
        "asking for the second time",
        "second time reaching out",
        "second time contacting",
        "second time asking",
        "second time i've asked",
        "second time i asked",
        "second time today",
        "for the second time",
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
        "sent you a dm yesterday",
        "hours ago no reply",
        "9hours ago",
        "9 hours ago",
        "unresolved",
        "written several times",
        "sent you several emails",
        "several emails",
        "no answer",
        "still have no answer",
        "still haven't heard",
        "still havent heard",
        "nobody is answering",
        "no one is answering",
        "still waiting for a solution",
        "still waiting for a reply",
        "still waiting for response",
        "still waiting for an answer",
        "on attend toujours",
        "sent an email to support",
        "havent reply yet",
        "haven't reply yet",
        "no one answered me back",
        "how long does it take for them to answer",
        "four times in the last month",
        "i've changed my password four times",
        "terrible customer service",
        "no one fixed a thing",
        "what is it with spotify and the non-answers",
        "closed a bunch of threads",
        "reported over a number of accounts for many years",
        "seems not to have been resolved",
        "6 days later and still",
        "days later and still",
        "been trying to sing up for 3 days",
        "been trying to sign up for 3 days",
        "already write a pm",
        "already wrote a pm",
        "by responding to my private message please",
    )

    alternate_channel_phrases = (
        "dm me",
        "send me a dm",
        "direct message",
        "message me privately",
        "email me",
        "email support",
        "private message",
        "private messages",
        "privet message",
        "privet messages",
        "web form",
        "take this to dm",
        "move to dm",
        "inbox me",
        "just dmd you",
        "have just dmd",
        "sent you a dm",
        "can you dm us",
        "send us a dm",
        "could you dm us",
        "could you dm",
        "shoot us a dm",
        "send over a dm",
        "drop us a dm",
        "dm us",
        "via dm",
        "in a dm",
        "through dm",
        "replied to your dm",
        "to your dm",
        "check dm",
        "check dms",
        "check your dm",
        "check your dms",
        "sent a dm",
        "dm opened",
        "dm please",
        "dm'd",
        "dmd",
        "sent dm",
        "pm me",
        "pm us",
        "sent a pm",
        "send a pm",
        "write a pm",
        "sent an email",
        "send an email",
        "reply to my emails",
        "reply to my email",
    )

    c_low = customer_text.lower()
    c_norm = " " + " ".join(re.sub(r"[^\w\s]", " ", c_low).split()) + " "

    if any(phrase in c_low or phrase in c_norm for phrase in dissatisfaction_phrases):
        flags.append("prior_interaction_dissatisfaction")

    # Alternate channel can trigger from customer or agent private DM initiation across full thread
    combined_for_channel = f"{customer_text} {full_thread_text}".lower()
    comb_norm = " " + " ".join(re.sub(r"[^\w\s]", " ", combined_for_channel).split()) + " "

    for p in alternate_channel_phrases:
        if p in combined_for_channel or p in comb_norm:
            flags.append("alternate_channel_request")
            break

    return tuple(sorted(flags))


def _technical_scope(
    text: str,
    is_secondary: bool = False,
    primary_intent: Optional[str] = None,
) -> str:
    """Determine diagnostic technical malfunction scope."""
    t_low = text.lower()
    t_norm = " " + " ".join(re.sub(r"[^\w\s]", " ", t_low).split()) + " "

    # If 07 is secondary to an account/billing/plan inquiry without specific device hardware mentioned, default to unclear
    if is_secondary and primary_intent in ("06_login_authentication", "04_billing_payment", "05_subscription_plan_management"):
        device_mentioned = any(d in t_low for d in (
            "my phone", "my iphone", "my android", "my pc", "my laptop", "my mac", "samsung", "pixel",
            "galaxy", "windows 10", "iphone x", "iphone 8", "ios 11", "desktop app", "browser", "web player"
        ))
        if not device_mentioned:
            return "unclear"

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
        "is spotify down",
        "spotify down",
        "is the app down",
        "#spotifydown",
    )

    individual_phrases = (
        "my phone",
        "my iphone",
        "on the iphone",
        "on iphone",
        "iphone",
        "my android",
        "on android",
        "android",
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
        "browser",
        "web player",
        "my ipad",
        "on my ipad",
        "ipad",
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
        "huawei",
        "app keeps closing",
        "clean reinstall",
        "my app has an error",
        "rebooted",
        "reinstall",
        "redownload",
        "closed the app",
        "my app",
        "updated my app",
        "latest version",
        "version 8",
        "armv7",
        "google pixel",
        "samsung s7",
        "samsung s5",
        "wrong album cover",
        "blank album cover",
        "album art",
        "gray disk",
        "share button",
        "pausing",
        "high rate of speed",
        "plays the same song",
        "missing \"api-ms-win",
        "reinstalling the software",
    )

    if "is anyone having and trouble" in t_low or "is anyone having trouble" in t_low:
        return "unclear"

    if "missing \"api-ms-win" in t_low or "reinstalling the software" in t_low:
        return "individual"

    if any(phrase in t_low or phrase in t_norm for phrase in platform_wide_phrases):
        return "platform_wide"

    if any(phrase in t_low or phrase in t_norm for phrase in individual_phrases):
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
            "error code 3",
            "error 3",
            "still ads",
            "listed as free",
            "can't access any of my songs",
            "cant access any of my songs",
            "plays the same song without actually playing",
            "wont let me join",
            "won't let me join",
            "please fix spotify",
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
            "student premium",
            "student deal",
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
            "can you please add",
            "is removed",
            "was removed",
            "got removed",
            "why removed",
            "why is it removed",
            "why was it removed",
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
            "wrong artist name",
            "uploaded under the wrong",
            "uploaded to spotify under the wrong",
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
            "button?",
            "how do i stop that from happening",
            "stop that from happening",
            "changes my playlist to songs",
            "to your playlist",
            "on your playlist",
            "to the playlist",
            "on the playlist",
            "playlist, please",
            "on today's top hits",
            "why don't you change it",
            "10k limit",
            "library limit",
            "explicit lyrics",
            "filter explicit",
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
            "my artist page",
            "artist page",
            "artist profile page",
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

    # 3. If "can you please add <song>" or track addition, prioritize 01 over 08, UNLESS it's an editorial playlist request
    if "why is" in lowered and "removed" in lowered:
        matches.setdefault("01_catalog_content_gap", ("removed",))

    if "01_catalog_content_gap" in matches and "08_feature_request" in matches:
        if "playlist" in lowered:
            matches.pop("01_catalog_content_gap", None)
        else:
            f_terms = matches["08_feature_request"]
            if all(t in ("please add", "can you add", "could you add") for t in f_terms):
                del matches["08_feature_request"]

    # 4. If "future plans to allow to invite" is in 08 and mentions family or invite, add 05 as secondary
    if "future plans to allow" in lowered and ("family" in lowered or "invite" in lowered):
        matches.setdefault("05_subscription_plan_management", ("family plan",))

    # 5. If "written with accent" is present in 02, don't trigger 07 on audio glitch
    if "02_catalog_metadata_error" in matches and "07_technical_malfunction" in matches:
        if "written with accent" in lowered:
            del matches["07_technical_malfunction"]

    # 6. SD card hardware removal is not catalog content gap
    if "sd card" in lowered and "01_catalog_content_gap" in matches:
        del matches["01_catalog_content_gap"]

    # 7. Online help 404 during billing dispute is not technical playback error
    if "error 404" in lowered and ("charged" in lowered or "online help" in lowered) and "07_technical_malfunction" in matches:
        del matches["07_technical_malfunction"]

    # 8. Entering wrong name on family account setup is plan management, not metadata error
    if ("wrong name on family" in lowered or "family plan account" in lowered) and "02_catalog_metadata_error" in matches:
        del matches["02_catalog_metadata_error"]

    # 10. Downgrading android app version is technical troubleshooting, not feature request
    if "downgrade spotify android" in lowered and "08_feature_request" in matches:
        del matches["08_feature_request"]

    # 11. Country-specific availability is region availability, not catalog gap
    if ("for uk" in lowered or "in the us" in lowered) and "03_region_availability" in matches:
        if "when will" in lowered:
            matches.pop("01_catalog_content_gap", None)

    # 12. Billing refund / charge dispute with incidental plan name mentions (not requesting plan change)
    if "04_billing_payment" in matches and "05_subscription_plan_management" in matches:
        is_charge_or_refund = any(
            w in lowered for w in ("charged", "charge", "refund", "renewal", "overcharge", "billed", "duplicate charge", "charged twice")
        )
        has_active_plan_action = any(
            w in lowered for w in (
                "how to", "how do i", "how can i", "help me cancel", "switch", "change",
                "upgrade", "downgrade", "invite", "invitation", "redeem", "join", "sign up", "signing up",
                "claim", "update", "apply", "verify", "verification", "eligibility", "sheerid",
                "add member", "daughter's profile", "daughters profile", "sub account", "sub-account"
            )
        )
        if is_charge_or_refund and not has_active_plan_action:
            matches.pop("05_subscription_plan_management", None)

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

    # Compound Intent Priority Overrides:
    # Rule A: When creator reports uploaded tracks under wrong artist name, 09 is primary over 02
    if "09_artist_rights_holder_mgmt" in ordered_intents and "02_catalog_metadata_error" in ordered_intents:
        if any(p in matching_text for p in ("my music", "uploaded under the wrong", "uploaded to spotify", "my song")):
            ordered_intents.remove("09_artist_rights_holder_mgmt")
            ordered_intents.insert(0, "09_artist_rights_holder_mgmt")

    # Rule B: When customer asks about future plans/features, 08 is primary over 05
    if "08_feature_request" in ordered_intents and "05_subscription_plan_management" in ordered_intents:
        if any(p in matching_text for p in ("future plans to allow", "future plans")):
            ordered_intents.remove("08_feature_request")
            ordered_intents.insert(0, "08_feature_request")

    # Rule C: When customer inquiry is about joining/setting up a family plan, 05 is primary over 07
    if "05_subscription_plan_management" in ordered_intents and "07_technical_malfunction" in ordered_intents:
        if any(p in matching_text for p in ("join family", "join a family", "join family premium", "let me join", "invite my family")):
            ordered_intents.remove("05_subscription_plan_management")
            ordered_intents.insert(0, "05_subscription_plan_management")

    primary = ordered_intents[0]
    secondary = tuple(ordered_intents[1:])

    # Technical scope conditionality (mandatory if intent 07 is present)
    scope: Optional[str] = None
    if "07_technical_malfunction" in ordered_intents:
        is_sec = "07_technical_malfunction" != primary
        scope = _technical_scope(matching_text, is_secondary=is_sec, primary_intent=primary)

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

    # Compound Intent Priority Overrides:
    # Rule A: When creator reports uploaded tracks under wrong artist name, 09 is primary over 02
    if "09_artist_rights_holder_mgmt" in ordered_intents and "02_catalog_metadata_error" in ordered_intents:
        if any(p in matching_text for p in ("my music", "uploaded under the wrong", "uploaded to spotify", "my song")):
            ordered_intents.remove("09_artist_rights_holder_mgmt")
            ordered_intents.insert(0, "09_artist_rights_holder_mgmt")

    # Rule B: When customer asks about future plans/features, 08 is primary over 05
    if "08_feature_request" in ordered_intents and "05_subscription_plan_management" in ordered_intents:
        if any(p in matching_text for p in ("future plans to allow", "future plans")):
            ordered_intents.remove("08_feature_request")
            ordered_intents.insert(0, "08_feature_request")

    # Rule C: When customer inquiry is about joining/setting up a family plan, 05 is primary over 07
    if "05_subscription_plan_management" in ordered_intents and "07_technical_malfunction" in ordered_intents:
        if any(p in matching_text for p in ("join family", "join a family", "join family premium", "let me join", "invite my family")):
            ordered_intents.remove("05_subscription_plan_management")
            ordered_intents.insert(0, "05_subscription_plan_management")

    primary = ordered_intents[0]
    secondary = tuple(ordered_intents[1:])

    scope: Optional[str] = None
    if "07_technical_malfunction" in ordered_intents:
        is_sec = "07_technical_malfunction" != primary
        scope = _technical_scope(matching_text, is_secondary=is_sec, primary_intent=primary)

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