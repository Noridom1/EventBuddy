import re
from dataclasses import dataclass, field
from enum import StrEnum

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


class Intent(StrEnum):
    CREATE_EVENT = "create_event"
    REMIND = "remind"
    QUERY_TASKS = "query_tasks"
    CONTEXT_SWITCH = "context_switch"
    GENERATE_REPORT = "generate_report"
    SMALL_TALK = "small_talk"


@dataclass
class Classification:
    intent: Intent
    slots: dict = field(default_factory=dict)


def _strip_mention(text: str) -> str:
    # Strip a bot mention (@Name) but never the "@" inside an email like a@x.com:
    # the negative lookbehind ensures the "@" isn't preceded by email-ish chars.
    return re.sub(r"(?<![\w.+-])@\w+\s*", "", text).strip()


def classify(text: str) -> Classification:
    t = _strip_mention(text)
    low = t.lower()

    if "create event" in low:
        name_match = re.search(r"create event\s+['\"]?([^'\"]+?)['\"]?(?:\s+members:|$)", t, re.I)
        emails = EMAIL_RE.findall(t)
        name = name_match.group(1).strip() if name_match else ""
        return Classification(Intent.CREATE_EVENT, {"event_name": name, "emails": emails})

    if "focus on" in low:
        q = re.search(r"focus on\s+(.+)", t, re.I)
        query = q.group(1).strip() if q else ""
        return Classification(Intent.CONTEXT_SWITCH, {"event_query": query})

    if "report" in low:
        return Classification(Intent.GENERATE_REPORT, {})

    if "remind" in low or "nhắc" in low:
        return Classification(Intent.REMIND, {"raw": t})

    if "task" in low or "due" in low:
        return Classification(Intent.QUERY_TASKS, {"raw": t})

    return Classification(Intent.SMALL_TALK, {"raw": t})
