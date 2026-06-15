"""The generic (event-independent) send helpers. `_expand_aliases` normalizes recipients for
`send_email`/`send_teams_message`: split a delimited string, expand bare corporate aliases to
full addresses via the configured domain, trim, and dedupe. The teams_dm dispatch and the
tool→closure delegation are covered in test_perform_send.py and test_action_tools.py."""
from eventbuddy.agent.wiring import _expand_aliases
from eventbuddy.config import settings


def test_expand_aliases_splits_string_and_expands_alias(monkeypatch):
    monkeypatch.setattr(settings, "corp_email_domain", "vng.com.vn")
    out = _expand_aliases("phucnlt2, alice@x.com; bob")
    assert out == ["phucnlt2@vng.com.vn", "alice@x.com", "bob@vng.com.vn"]


def test_expand_aliases_accepts_list(monkeypatch):
    monkeypatch.setattr(settings, "corp_email_domain", "vng.com.vn")
    assert _expand_aliases(["phucnlt2", "a@x.com"]) == ["phucnlt2@vng.com.vn", "a@x.com"]


def test_expand_aliases_dedupes_case_insensitively(monkeypatch):
    monkeypatch.setattr(settings, "corp_email_domain", "vng.com.vn")
    assert _expand_aliases(["A@x.com", "a@x.com", "phucnlt2", "phucnlt2"]) == [
        "A@x.com", "phucnlt2@vng.com.vn"]


def test_expand_aliases_drops_bare_alias_without_domain(monkeypatch):
    # No corp domain configured → a bare alias can't be addressed and is dropped; full
    # addresses still pass through.
    monkeypatch.setattr(settings, "corp_email_domain", "")
    assert _expand_aliases("phucnlt2, a@x.com") == ["a@x.com"]


def test_expand_aliases_empty_input():
    assert _expand_aliases("") == []
    assert _expand_aliases([]) == []
    assert _expand_aliases(None) == []
