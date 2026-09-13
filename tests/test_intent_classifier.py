import pytest
from src.spotify_agent.intent_classifier import (
    Classification,
    classify_message,
    classify_conversation,
    SUBSTANTIVE_INTENTS,
    NON_INTENT_CLASSES,
    TECHNICAL_SCOPES,
    INTENT_PRIORITY,
)
from src.spotify_agent.conversation_parser import parse_conversation


def test_single_message_classification_substantive():
    # 04_billing_payment
    res = classify_message("Why was I charged twice for my subscription this month?")
    assert isinstance(res, Classification)
    assert res.primary_intent == "04_billing_payment"
    assert res.is_non_intent is False
    assert res.non_intent_class is None
    assert "charged twice" in res.evidence_quote.lower()

    # 06_login_authentication
    res_login = classify_message("I forgot my password and cannot log in to my account.")
    assert res_login.primary_intent == "06_login_authentication"
    assert res_login.is_non_intent is False

    # 01_catalog_content_gap
    res_gap = classify_message("When will the new Red Velvet album come to Spotify?")
    assert res_gap.primary_intent == "01_catalog_content_gap"
    assert res_gap.is_non_intent is False


def test_multi_turn_classification():
    thread = {
        "conversation_id": "spotify_test_multi",
        "ordered_messages": [
            {
                "tweet_id": "1",
                "author_id": "user_123",
                "inbound": True,
                "text": "@SpotifyCares I have an issue with my account",
            },
            {
                "tweet_id": "2",
                "author_id": "SpotifyCares",
                "inbound": False,
                "text": "@user_123 Hey there, how can we help? /SU",
            },
            {
                "tweet_id": "3",
                "author_id": "user_123",
                "inbound": True,
                "text": "@SpotifyCares my app keeps crashing on iOS 17 whenever I press play",
            },
        ],
    }

    # Should use the customer turns and identify 07_technical_malfunction
    res = classify_conversation(thread)
    assert res.primary_intent == "07_technical_malfunction"
    assert res.technical_malfunction_scope == "individual"
    assert res.is_non_intent is False

    # classify_message directly on thread dict should also work
    res_direct = classify_message(thread)
    assert res_direct.primary_intent == "07_technical_malfunction"


def test_multi_intent_priority_ordering():
    # Message combining 06_login, 04_billing, and 07_technical
    # Priority: 06_login > 04_billing > 07_technical
    msg = "I got randomly logged out and then my credit card was double charged and the app crashed!"
    res = classify_message(msg)

    assert res.primary_intent == "06_login_authentication"
    assert "04_billing_payment" in res.secondary_intents
    assert "07_technical_malfunction" in res.secondary_intents

    # Message combining 04_billing and 05_plan
    # Priority: 04_billing > 05_plan
    msg2 = "How do I upgrade to a family plan with Fido billing?"
    res2 = classify_message(msg2)
    assert res2.primary_intent == "04_billing_payment"
    assert "05_subscription_plan_management" in res2.secondary_intents

    # Message combining 05_plan and 03_region
    # Priority: 05_plan > 03_region
    msg3 = "I moved abroad and need to invite a family member to my family plan."
    res3 = classify_message(msg3)
    assert res3.primary_intent == "05_subscription_plan_management"
    assert "03_region_availability" in res3.secondary_intents


def test_non_intent_classification():
    # 1. insufficient_information
    res_insuf = classify_message("help me please")
    assert res_insuf.is_non_intent is True
    assert res_insuf.non_intent_class == "insufficient_information"
    assert res_insuf.primary_intent is None

    # 2. no_action_acknowledgment_only
    res_ack = classify_message("Thank you so much that fixed it!")
    assert res_ack.is_non_intent is True
    assert res_ack.non_intent_class == "no_action_acknowledgment_only"
    assert res_ack.primary_intent is None

    # 3. out_of_scope_non_support
    res_social = classify_message("I love Spotify so much, happy birthday!")
    assert res_social.is_non_intent is True
    assert res_social.non_intent_class == "out_of_scope_non_support"
    assert res_social.primary_intent is None


def test_technical_malfunction_scopes():
    # Individual scope
    res_ind = classify_message("The repeat button is not working on my iPhone.")
    assert res_ind.primary_intent == "07_technical_malfunction"
    assert res_ind.technical_malfunction_scope == "individual"

    # Platform-wide scope
    res_outage = classify_message("Is Spotify down for everyone right now? Servers are down.")
    assert res_outage.primary_intent == "07_technical_malfunction"
    assert res_outage.technical_malfunction_scope == "platform_wide"

    # Unclear scope
    res_unclear = classify_message("Music is buffering and not loading.")
    assert res_unclear.primary_intent == "07_technical_malfunction"
    assert res_unclear.technical_malfunction_scope == "unclear"

    # Non-07 intent must have null scope
    res_non_tech = classify_message("How do I change my password?")
    assert res_non_tech.primary_intent == "06_login_authentication"
    assert res_non_tech.technical_malfunction_scope is None


def test_cross_cutting_flags():
    # Dissatisfaction flag
    msg_dissat = "Third time reaching out! Sent 5 messages and still no reply regarding my billing charge."
    res_dissat = classify_message(msg_dissat)
    assert "prior_interaction_dissatisfaction" in res_dissat.cross_cutting_flags
    assert res_dissat.primary_intent == "04_billing_payment"

    # Alternate channel request flag (customer initiated)
    msg_dm = "Please DM me directly regarding my hacked account."
    res_dm = classify_message(msg_dm)
    assert "alternate_channel_request" in res_dm.cross_cutting_flags

    # Alternate channel request flag (agent initiated in multi-turn thread)
    thread = {
        "ordered_messages": [
            {"author_id": "cust", "inbound": True, "text": "I was charged twice"},
            {"author_id": "SpotifyCares", "inbound": False, "text": "Hey! Can you DM us your email? /SU"},
        ]
    }
    res_thread_dm = classify_conversation(thread)
    assert "alternate_channel_request" in res_thread_dm.cross_cutting_flags


def test_regression_09_artist_rights_holder_mgmt():
    """Systematic error category: Creator/artist profile and attribution queries."""
    # 1. Release attribution on wrong artist profile
    res1 = classify_message("Why is my music always uploaded to Spotify under the wrong artist name?")
    assert res1.primary_intent == "09_artist_rights_holder_mgmt"

    # 2. Artist profile duplicate / merging
    res2 = classify_message("Artists with the same name being lumped together on the artist page.")
    assert res2.primary_intent == "09_artist_rights_holder_mgmt"

    # 3. Copyright / rights holder inquiry
    res3 = classify_message("I am the intellectual copyright owner for this track on Spotify.")
    assert res3.primary_intent == "09_artist_rights_holder_mgmt"


def test_regression_01_catalog_content_gap():
    """Systematic error category: Missing songs, albums, or removed content."""
    # 1. Discography removed
    res1 = classify_message("Where's the Jonas brothers discography?? Why did you remove some songs?")
    assert res1.primary_intent == "01_catalog_content_gap"

    # 2. Upcoming album addition
    res2 = classify_message("WHEN WILL RED VELVETS PEEK A BOO ALBUM BE ON SPOTIFY?")
    assert res2.primary_intent == "01_catalog_content_gap"

    # 3. Catalog track availability
    res3 = classify_message("Why is Kanye's and JayZ's music not available on Spotify yet?")
    assert res3.primary_intent == "01_catalog_content_gap"


def test_regression_08_feature_request():
    """Systematic error category: Feature suggestions vs bugs."""
    # 1. Playlist reorganization feature
    res1 = classify_message("Please add an option to rearrange playlists in custom order.")
    assert res1.primary_intent == "08_feature_request"

    # 2. Legacy UI feature restoration
    res2 = classify_message("Bring back touch preview swiping feature on the mobile app!")
    assert res2.primary_intent == "08_feature_request"

    # 3. Playback speed option
    res3 = classify_message("We need an option for playback speed on podcasts.")
    assert res3.primary_intent == "08_feature_request"


def test_regression_07_technical_malfunction():
    """Systematic error category: App crashes, outages, playback failures."""
    # 1. Device specific crash
    res1 = classify_message("The app keeps closing on galaxy s8 whenever cellular data is active.")
    assert res1.primary_intent == "07_technical_malfunction"
    assert res1.technical_malfunction_scope == "individual"

    # 2. Platform outage
    res2 = classify_message("Servers are down again for everyone, music cuts out.")
    assert res2.primary_intent == "07_technical_malfunction"
    assert res2.technical_malfunction_scope == "platform_wide"


def test_regression_06_login_authentication():
    """Systematic error category: Hacked account, credential loss, security."""
    # 1. Compromised account / email changed
    res1 = classify_message("Someone got into my account and the email was changed without my permission!")
    assert res1.primary_intent == "06_login_authentication"

    # 2. Facebook login revocation
    res2 = classify_message("How do I undo revoke access to login with Facebook?")
    assert res2.primary_intent == "06_login_authentication"


def test_regression_05_subscription_plan_management():
    """Systematic error category: Student release, family invite/switching."""
    # 1. Student discount release
    res1 = classify_message("Was hoping you'd release my student email from my old account on SheerID.")
    assert res1.primary_intent == "05_subscription_plan_management"

    # 2. Family plan join / invite
    res2 = classify_message("How do I join back to a family premium plan after leaving?")
    assert res2.primary_intent == "05_subscription_plan_management"


def test_regression_02_catalog_metadata_error():
    """Systematic error category: Misspelled titles, mismatched artwork, sync lyrics."""
    # 1. Song mislabeled
    res1 = classify_message("Every song on this album has the wrong name and incorrect title.")
    assert res1.primary_intent == "02_catalog_metadata_error"

    # 2. Artwork mismatch
    res2 = classify_message("Album art and songs aren't matching on the tracklist.")
    assert res2.primary_intent == "02_catalog_metadata_error"


def test_regression_03_region_availability():
    """Systematic error category: Geo-licensing, country restriction."""
    # 1. Regional license restriction
    res1 = classify_message("Why is this album not available in the US or greyed out in my region?")
    assert res1.primary_intent == "03_region_availability"

    # 2. Geographic availability question
    res2 = classify_message("Has his music only been removed from Europe due to geo license?")
    assert res2.primary_intent == "03_region_availability"


def test_step9_targeted_refinements():
    """Verify Step 9 targeted refinements covering all 8 error categories."""
    # 1. 01_catalog_content_gap: song addition vs feature request
    res_add_song = classify_message("Can you please add Sweet Dreams (Radio Killer Remix) I think people will like it")
    assert res_add_song.primary_intent == "01_catalog_content_gap"

    # 2. 05_subscription_plan_management: how do I upgrade & family onboarding code
    res_upgrade = classify_message("How do I upgrade if you don't mind answering for me?")
    assert res_upgrade.primary_intent == "05_subscription_plan_management"

    res_family_redeem = classify_message("Have Premium for Family. Trying to set up daughter's profile, redeem code not working.")
    assert res_family_redeem.primary_intent == "05_subscription_plan_management"

    # 3. 07_technical_malfunction: loading failures, concise server outage, unicode smart quotes
    res_loading = classify_message("Hey my app has an error, and nothing is loading")
    assert res_loading.primary_intent == "07_technical_malfunction"

    res_servers = classify_message("Fix ya servers please, music stopped")
    assert res_servers.primary_intent == "07_technical_malfunction"
    assert res_servers.technical_malfunction_scope == "platform_wide"

    res_smart_quote = classify_message("Please help I can’t log in to my Spotify error 404")
    assert res_smart_quote.primary_intent == "06_login_authentication"

    # 4. 08_feature_request: negation 'not a bug', rhetorical button request, future plan expansion
    res_not_bug = classify_message("I would like to choose columns to display. This is a feature request, not a bug.")
    assert res_not_bug.primary_intent == "08_feature_request"

    res_rhetorical = classify_message("Where is the cancel my account button?")
    assert res_rhetorical.primary_intent == "08_feature_request"

    res_future_plan = classify_message("I have the Family Plan. Is there any future plans to allow to invite more members?")
    assert res_future_plan.primary_intent == "08_feature_request"

    # 5. 09_artist_rights_holder_mgmt: creator page migration vs region movement
    res_artist_move = classify_message("My bands music was moved to a separate page and I lost being able to admin the page.")
    assert res_artist_move.primary_intent == "09_artist_rights_holder_mgmt"

    # 6. 03_region_availability: informal regional phrasing
    res_region_informal = classify_message("It's 3 month ago but did Spotify come to our country...why?")
    assert res_region_informal.primary_intent == "03_region_availability"

    # 7. Broadcast outage handling
    broadcast_thread = {
        "ordered_messages": [
            {"author_id": "SpotifyCares", "inbound": False, "text": "All clear! Everything's looking good again. Enjoy the tunes."},
            {"author_id": "user1", "inbound": True, "text": "Still not letting me log in..."},
            {"author_id": "user2", "inbound": True, "text": "My payment via PayPal failed"},
            {"author_id": "user3", "inbound": True, "text": "My family account disappeared"},
            {"author_id": "user4", "inbound": True, "text": "Songs are still gone"},
            {"author_id": "user5", "inbound": True, "text": "Having the same issue"},
        ]
    }
    res_broadcast = classify_conversation(broadcast_thread)
    assert res_broadcast.primary_intent == "07_technical_malfunction"
    assert res_broadcast.technical_malfunction_scope == "platform_wide"


