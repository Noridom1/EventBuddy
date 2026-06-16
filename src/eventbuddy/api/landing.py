from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response

from eventbuddy.config import settings

router = APIRouter()


def _landing_index() -> Path:
    return Path(settings.landing_page_dir) / "index.html"


@router.api_route("/", methods=["GET", "HEAD"])
@router.api_route("/index.html", methods=["GET", "HEAD"])
async def landing_page() -> Response:
    """Serve the Event Buddy install page at the runtime endpoint root.

    Path is resolved at request time so a missing asset degrades to a 404 instead of
    breaking module import (and therefore the whole app / the /health probe).
    `Cache-Control: no-cache` makes the browser revalidate each load, so a redeployed page
    (the logo/images are inlined in this HTML) shows immediately instead of a stale copy."""
    index = _landing_index()
    if not index.is_file():
        return JSONResponse({"detail": "landing page not available"}, status_code=404)
    return FileResponse(index, media_type="text/html", headers={"Cache-Control": "no-cache"})


@router.get("/download/eventbuddy.zip")
async def download_package() -> Response:
    """Hand out the installable Teams app package (manifest + icons) from the same origin
    as the landing page, so the page's Download button works with no external dependency.

    If the bundled ZIP isn't on disk (e.g. it wasn't baked into the image), fall back to the
    configured SharePoint share link instead of 404ing, so the button keeps working."""
    pkg = Path(settings.teams_package_path)
    if pkg.is_file():
        return FileResponse(pkg, media_type="application/zip", filename="eventbuddy.zip")
    if settings.teams_package_fallback_url:
        return RedirectResponse(settings.teams_package_fallback_url, status_code=302)
    return JSONResponse({"detail": "package not available"}, status_code=404)
