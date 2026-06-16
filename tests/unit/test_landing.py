# tests/unit/test_landing.py
from pathlib import Path

from fastapi.testclient import TestClient

from eventbuddy.config import settings
from eventbuddy.main import app

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _point_settings_at_repo(monkeypatch) -> None:
    """Resolve the asset paths from the repo root so the test doesn't depend on CWD."""
    monkeypatch.setattr(settings, "landing_page_dir", str(_REPO_ROOT / "landing_page"))
    monkeypatch.setattr(
        settings, "teams_package_path", str(_REPO_ROOT / "teams-app" / "eventbuddy.zip")
    )


def test_root_serves_landing_html(monkeypatch):
    _point_settings_at_repo(monkeypatch)
    resp = TestClient(app).get("/")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    assert "Event Buddy" in resp.text


def test_download_serves_zip_as_attachment(monkeypatch):
    _point_settings_at_repo(monkeypatch)
    resp = TestClient(app).get("/download/eventbuddy.zip")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"
    assert "attachment" in resp.headers["content-disposition"]
    assert "eventbuddy.zip" in resp.headers["content-disposition"]


def test_missing_zip_redirects_to_fallback(monkeypatch):
    # When the bundled ZIP isn't on disk, the download falls back to the SharePoint link
    # instead of 404ing, so the page's Download button keeps working.
    monkeypatch.setattr(settings, "teams_package_path", "/nonexistent/eventbuddy.zip")
    monkeypatch.setattr(settings, "teams_package_fallback_url", "https://example.com/fb.zip")
    resp = TestClient(app).get("/download/eventbuddy.zip", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "https://example.com/fb.zip"


def test_missing_assets_degrade_to_404(monkeypatch):
    # With no asset AND no fallback, both routes degrade cleanly — never crash /health.
    monkeypatch.setattr(settings, "landing_page_dir", "/nonexistent/landing")
    monkeypatch.setattr(settings, "teams_package_path", "/nonexistent/eventbuddy.zip")
    monkeypatch.setattr(settings, "teams_package_fallback_url", "")
    client = TestClient(app)
    assert client.get("/").status_code == 404
    assert client.get("/download/eventbuddy.zip").status_code == 404
    # The app still serves the health probe regardless.
    assert client.get("/health").status_code == 200
