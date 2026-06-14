"""LLM structuring of a parsed document → members/tasks JSON (architecture §5.5, §397).

The prompt forces JSON-only output so the pipeline can upsert deterministically. A malformed
reply degrades to empty lists (never invent members/tasks) so the document still records as
ingested while proposing nothing — the safe failure mode for a proactive action."""
import json

from eventbuddy.common.logging import get_logger

log = get_logger("ingestion.extractor")

STRUCTURE_PROMPT = (
    "You extract structured event data from an uploaded planning document. "
    "Return ONLY JSON of the form: "
    '{"members": [{"email": str, "display_name": str, "role": "member|moderator|host"}], '
    '"tasks": [{"task_name": str, "assignee_email": str|null, "due_date": str|null}]}. '
    "Include a person under \"members\" only if you can see an email address. "
    "Use [] for a section with nothing to extract. Do not add commentary."
)

# Cap how much document text we hand the model (token budget + cost).
_TEXT_BUDGET = 8000


class Extractor:
    def __init__(self, llm_gateway):
        self.llm = llm_gateway

    def structure(self, parsed) -> dict:
        text = parsed.text or ""
        if not text.strip():
            return {"members": [], "tasks": []}
        raw = self.llm.chat([
            {"role": "system", "content": STRUCTURE_PROMPT},
            {"role": "user", "content": text[:_TEXT_BUDGET]},
        ])
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            log.warning(f"extractor: non-JSON reply for {parsed.filename}")
            return {"members": [], "tasks": []}
        members = data.get("members", []) if isinstance(data, dict) else []
        tasks = data.get("tasks", []) if isinstance(data, dict) else []
        return {
            "members": [m for m in members if isinstance(m, dict) and m.get("email")],
            "tasks": [t for t in tasks if isinstance(t, dict) and t.get("task_name")],
        }
