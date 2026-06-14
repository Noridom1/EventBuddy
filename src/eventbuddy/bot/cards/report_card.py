def report_card(*, metrics: dict, summary_md: str, suggestions_md: str) -> dict:
    """Read-only report card (architecture §7.5) — metrics + AI summary + next-event
    suggestions. No actions: this card informs, it doesn't trigger a send (the manager-email
    draft is a separate HITL confirm card)."""
    rate = metrics.get("response_rate", 0)
    sat = metrics.get("satisfaction_avg")
    reg = metrics.get("registration_rate", 0)
    return {
        "type": "AdaptiveCard",
        "version": "1.4",
        "body": [
            {"type": "TextBlock", "size": "Large", "weight": "Bolder", "text": "📊 Event Report"},
            {"type": "TextBlock", "wrap": True,
             "text": f"Registration: {reg} · Response rate: {rate} · Satisfaction: {sat}"},
            {"type": "TextBlock", "weight": "Bolder", "text": "Summary"},
            {"type": "TextBlock", "wrap": True, "text": summary_md},
            {"type": "TextBlock", "weight": "Bolder", "text": "Suggestions for next time"},
            {"type": "TextBlock", "wrap": True, "text": suggestions_md},
        ],
    }
