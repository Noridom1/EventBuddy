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


SHOW_ALL_CHOICE = "__all__"


def file_pick_card(*, query: str, names: list[str], pending_id: str,
                   show_all: bool = True) -> dict:
    """Disambiguation picker (Impl 9): when a file name/description matches several files, ask
    the user to choose with a **multi-select dropdown** (no typing). The submit carries only the
    opaque `pending_id` + the selected file names (rule 2 — the candidate set + the original
    question live server-side in the pending store). A "Show all files in this chat" choice lets
    the user override to any file. `selected` arrives comma-joined for a multi-select ChoiceSet."""
    choices = [{"title": n, "value": n} for n in names]
    if show_all:
        choices.append({"title": "📂 Show all files in this chat", "value": SHOW_ALL_CHOICE})
    return {
        "type": "AdaptiveCard",
        "version": "1.4",
        "body": [
            {"type": "TextBlock", "weight": "Bolder", "wrap": True,
             "text": f"A few files match '{query}'. Which should I read?"},
            {"type": "Input.ChoiceSet", "id": "selected", "isMultiSelect": True,
             "style": "compact", "placeholder": "Pick one or more files", "choices": choices},
        ],
        "actions": [
            {"type": "Action.Submit", "title": "📄 Read selected",
             "data": {"action": "read_files", "pending_id": pending_id}},
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
