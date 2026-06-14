from eventbuddy.bot.cards.report_card import report_card


def test_report_card_includes_metrics_summary_suggestions():
    card = report_card(
        metrics={"response_rate": 0.6, "satisfaction_avg": 4.2, "registration_rate": 0.8},
        summary_md="People liked it.", suggestions_md="1. Shorten sessions")
    text = str(card)
    assert "People liked it." in text
    assert "Shorten" in text
    assert "0.6" in text


def test_report_card_has_no_actions():
    # Read-only: the report card informs; it must not carry a send action (the manager email
    # is a separate HITL confirm card).
    card = report_card(metrics={}, summary_md="s", suggestions_md="x")
    assert "actions" not in card
