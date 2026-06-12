from eventbuddy.bot.cards.builders import event_overview_card, reminder_channel_card


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
