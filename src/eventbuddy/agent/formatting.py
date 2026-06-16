"""Markdown → HTML rendering for outbound email and Teams messages.

The model authors message bodies in **Markdown** (headings, `**bold**`, `- bullet`
lists, blank lines between paragraphs). Graph mail is sent as `contentType: HTML` and
Teams 1-1 chat renders a subset of HTML, so we convert at the send seam instead of
flattening the body into a single `<p>` (which collapsed all newlines/structure — the
reason templated mail used to arrive as one run-on paragraph).

Degrades gracefully: if the optional `markdown` dependency is missing, or rendering
throws, we fall back to escaping + paragraph/line-break splitting so a send never
hard-fails on formatting (cross-cutting graceful-degradation rule)."""

from __future__ import annotations

import html
import logging

log = logging.getLogger(__name__)

# nl2br: a lone newline → <br> (the model often writes one item per line without a blank
# line between them). sane_lists: don't fold an ordered list into a preceding bullet list.
_EXTENSIONS = ["nl2br", "sane_lists"]


def _fallback(text: str) -> str:
    """No `markdown` lib (or it errored): escape, turn blank-line blocks into <p> and
    single newlines into <br>. Markdown markers (**, -) survive as literal text — ugly
    but safe and readable — rather than the body collapsing to one line."""
    blocks = [b.strip() for b in (text or "").split("\n\n") if b.strip()]
    return "".join(
        "<p>" + html.escape(b).replace("\n", "<br>") + "</p>" for b in blocks
    ) or "<p></p>"


def render_markdown(text: str) -> str:
    """Render Markdown `text` to an HTML fragment suitable for an email or Teams body."""
    text = text or ""
    try:
        import markdown
    except ImportError:
        return _fallback(text)
    try:
        return markdown.markdown(text, extensions=_EXTENSIONS)
    except Exception as e:  # noqa: BLE001 — formatting must never break a send
        log.warning(f"markdown render failed ({type(e).__name__}: {e}); using fallback")
        return _fallback(text)
