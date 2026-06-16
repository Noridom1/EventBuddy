"""Markdown → HTML rendering for outbound email/Teams bodies (agent.formatting)."""

from eventbuddy.agent.formatting import render_markdown


def test_headings_bold_and_bullets_become_html():
    html = render_markdown("## Title\n\nHello **Starter**\n\n- one\n- two")
    assert "<h2>Title</h2>" in html
    assert "<strong>Starter</strong>" in html
    assert "<li>one</li>" in html and "<li>two</li>" in html


def test_single_newlines_become_line_breaks():
    # nl2br: a roster of one-line items without blank lines still keeps its breaks.
    html = render_markdown("When: 10:00\nWhere: Atrium")
    assert "<br" in html
    assert "When: 10:00" in html and "Where: Atrium" in html


def test_paragraphs_are_separated():
    html = render_markdown("First para.\n\nSecond para.")
    assert html.count("<p>") == 2


def test_empty_input_is_safe():
    assert render_markdown("") in ("", "<p></p>")
    assert render_markdown(None) in ("", "<p></p>")


def test_fallback_escapes_and_splits_when_lib_missing(monkeypatch):
    # Simulate the `markdown` dep being absent — render_markdown must degrade, not crash,
    # and not collapse the body to one line. Markers survive as literal text; HTML is escaped.
    import builtins

    real_import = builtins.__import__

    def _no_markdown(name, *args, **kwargs):
        if name == "markdown":
            raise ImportError("simulated missing dependency")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _no_markdown)
    html = render_markdown("a <b>\n\nc")
    assert "&lt;b&gt;" in html  # escaped, not injected
    assert html.count("<p>") == 2
