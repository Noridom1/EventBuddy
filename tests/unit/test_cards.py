from eventbuddy.bot.cards.builders import (
    confirm_card,
    event_overview_card,
    reminder_channel_card,
)


def test_event_overview_card_has_name_and_status():
    card = event_overview_card(
        name="AI Workshop", objective="learn", members=["a@x.com"], status="ideation"
    )
    body_text = str(card)
    assert "AI Workshop" in body_text and "Ideation" in body_text


def test_reminder_channel_card_offers_teams_and_outlook_actions():
    card = reminder_channel_card(task_name="slides", recipients=["Huy"])
    actions = card["actions"]
    titles = [a["title"] for a in actions]
    assert any("Teams" in t for t in titles)
    assert any("Outlook" in t for t in titles)


def test_reminder_card_data_carries_only_opaque_token():
    # The card must carry the pending_id + channel, never recipients/identity (rule 2).
    card = reminder_channel_card(task_name="slides", recipients=["a@x.com"], pending_id="tok-1")
    for action in card["actions"]:
        assert action["data"]["pending_id"] == "tok-1"
        assert action["data"]["action"] == "remind"
        assert set(action["data"]) == {"action", "channel", "pending_id"}  # nothing else
        assert "a@x.com" not in str(action["data"])


def test_confirm_card_single_button_with_action_and_token():
    card = confirm_card(title="Send email: Hi", summary="To 3 recipient(s).",
                        pending_id="tok-2", action="mail")
    assert len(card["actions"]) == 1
    data = card["actions"][0]["data"]
    assert data == {"action": "mail", "pending_id": "tok-2"}
