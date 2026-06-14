def event_overview_card(*, name: str, objective: str, members: list[str], status: str) -> dict:
    return {
        "type": "AdaptiveCard",
        "version": "1.4",
        "body": [
            {"type": "TextBlock", "size": "Large", "weight": "Bolder", "text": name},
            {"type": "TextBlock", "text": f"Objective: {objective}", "wrap": True},
            {"type": "TextBlock", "text": f"Members: {', '.join(members)}", "wrap": True},
            {"type": "TextBlock", "text": f"Status: {status.capitalize()}", "wrap": True},
        ],
    }


def reminder_channel_card(
    *, task_name: str, recipients: list[str], pending_id: str = "", body: str | None = None
) -> dict:
    # `pending_id` is the opaque token the confirm handler resolves server-side; the card
    # carries it (+ the channel) but NEVER recipients/identity (cross-cutting rule 2).
    # `recipients`/`body` are *display only* — they let the reviewer see exactly what will be
    # sent (and to whom) before choosing a channel (Impl 4).
    blocks = [
        {"type": "TextBlock", "weight": "Bolder",
         "text": f"Remind about '{task_name}' — choose a channel"},
        {"type": "TextBlock", "text": f"Recipients: {', '.join(recipients)}", "wrap": True},
    ]
    if body:
        blocks.append({"type": "TextBlock", "text": body, "wrap": True, "separator": True})
    return {
        "type": "AdaptiveCard",
        "version": "1.4",
        "body": blocks,
        "actions": [
            {"type": "Action.Submit", "title": "💬 Send via Teams",
             "data": {"action": "remind", "channel": "teams", "pending_id": pending_id}},
            {"type": "Action.Submit", "title": "📧 Send via Outlook",
             "data": {"action": "remind", "channel": "outlook", "pending_id": pending_id}},
        ],
    }


def confirm_card(*, title: str, summary: str, pending_id: str, action: str,
                 channel: str | None = None, recipients: list[str] | None = None,
                 body: str | None = None) -> dict:
    """A generic single-button HITL confirmation card (e.g. for `send_outlook_mail`). The
    button data carries only the action type + opaque `pending_id` (+ optional channel) — never
    recipients/identity (cross-cutting rule 2). `recipients`/`body` are *display only*: they let
    the reviewer see exactly what will be sent before confirming."""
    data = {"action": action, "pending_id": pending_id}
    if channel:
        data["channel"] = channel
    blocks = [
        {"type": "TextBlock", "weight": "Bolder", "text": title, "wrap": True},
        {"type": "TextBlock", "text": summary, "wrap": True},
    ]
    if recipients:
        blocks.append({"type": "TextBlock", "text": f"To: {', '.join(recipients)}",
                       "wrap": True, "isSubtle": True, "spacing": "Small"})
    if body:
        blocks.append({"type": "TextBlock", "text": body, "wrap": True, "separator": True})
    return {
        "type": "AdaptiveCard",
        "version": "1.4",
        "body": blocks,
        "actions": [
            {"type": "Action.Submit", "title": "✅ Confirm & send", "data": data},
        ],
    }
