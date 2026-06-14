"""Generic file understanding (Impl 5).

`understand(parsed, llm, vision)` turns a `ParsedDoc` into `{summary, doc_type}` — a short
"what is this file / what's it for" gist plus a coarse type — WITHOUT committing to any one
use. This is the product of ingestion: catalog the file, then stop. What (if anything) to do
with it — extract members/tasks + propose invites, draft from a template, answer a question —
is a separate, optional layer keyed on `doc_type`.

Text files use a cheap chat LLM call; images / image-only PDFs use the vision model. Every
failure degrades to a safe default (never raises) so a file still records as catalogued."""
from __future__ import annotations

import json

from eventbuddy.common.logging import get_logger
from eventbuddy.ingestion.parsers import ParsedDoc, render_pdf_first_page

log = get_logger("ingestion.understand")

# A small, open vocabulary. The classifier is advisory — consumers must tolerate "other"/None.
DOC_TYPES = ("roster", "planning", "template", "agenda", "budget", "report", "image", "other")

_UNDERSTAND_PROMPT = (
    "You are cataloguing a file uploaded to an event workspace. Read the content and return "
    "ONLY JSON of the form {\"summary\": str, \"doc_type\": str}. `summary` is one or two "
    "sentences describing what the file is and what it's for. `doc_type` is the single best "
    f"fit from this list: {', '.join(DOC_TYPES)}. Do not add commentary."
)
_VISION_INSTRUCTION = (
    "Describe this image in one or two sentences: what it shows and what it would be used for "
    "in an event workspace. If it contains text, mention the key text."
)
_TEXT_BUDGET = 8000


def _parse_json(raw: str) -> dict:
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def _normalize_type(value, default: str) -> str:
    v = (value or "").strip().lower()
    return v if v in DOC_TYPES else default


def understand(parsed: ParsedDoc, *, llm, vision=None) -> dict:
    """Return `{"summary": str, "doc_type": str}` for a parsed file. Never raises."""
    if parsed.kind in ("image", "image_pdf"):
        return _understand_image(parsed, vision)
    return _understand_text(parsed, llm)


def _understand_text(parsed: ParsedDoc, llm) -> dict:
    text = (parsed.text or "").strip()
    if not text:
        return {"summary": "", "doc_type": "other"}
    try:
        raw = llm.chat([
            {"role": "system", "content": _UNDERSTAND_PROMPT},
            {"role": "user", "content": text[:_TEXT_BUDGET]},
        ])
    except Exception as e:  # noqa: BLE001 — LLM down: still catalog the file, just unlabelled
        log.warning(f"understand (text) failed for {parsed.filename} ({type(e).__name__}: {e})")
        return {"summary": "", "doc_type": "other"}
    data = _parse_json(raw)
    return {
        "summary": str(data.get("summary", "")).strip(),
        "doc_type": _normalize_type(data.get("doc_type"), "other"),
    }


def _understand_image(parsed: ParsedDoc, vision) -> dict:
    if vision is None:
        return {"summary": "(image — vision not configured)", "doc_type": "image"}
    image_bytes, mime = parsed.raw_bytes, parsed.mime
    if parsed.kind == "image_pdf":
        rendered = render_pdf_first_page(parsed.raw_bytes or b"")
        if rendered is None:
            return {"summary": "(scanned PDF — couldn't render it to read)",
                    "doc_type": "image"}
        image_bytes, mime = rendered
    if not image_bytes:
        return {"summary": "(image — nothing to read)", "doc_type": "image"}
    try:
        desc = vision.describe_image(image_bytes, mime, _VISION_INSTRUCTION)
    except Exception as e:  # noqa: BLE001 — vision down: catalog as an image, no summary
        log.warning(f"understand (image) failed for {parsed.filename} ({type(e).__name__}: {e})")
        return {"summary": "(image — couldn't read it right now)", "doc_type": "image"}
    return {"summary": (desc or "").strip(), "doc_type": "image"}
