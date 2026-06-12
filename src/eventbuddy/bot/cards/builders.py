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


def reminder_channel_card(*, task_name: str, recipients: list[str]) -> dict:
    return {
        "type": "AdaptiveCard",
        "version": "1.4",
        "body": [
            {"type": "TextBlock", "weight": "Bolder",
             "text": f"Remind about '{task_name}' — choose a channel"},
            {"type": "TextBlock", "text": f"Recipients: {', '.join(recipients)}", "wrap": True},
        ],
        "actions": [
            {"type": "Action.Submit", "title": "💬 Send via Teams",
             "data": {"action": "remind", "channel": "teams", "task": task_name}},
            {"type": "Action.Submit", "title": "📧 Send via Outlook",
             "data": {"action": "remind", "channel": "outlook", "task": task_name}},
        ],
    }
