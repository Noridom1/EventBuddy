"""Agentic web tools backed by Tavily (Impl 3).

One provider powers both capabilities the agent needs to behave like a general assistant:
`search` (ranked result snippets) and `fetch` (clean full-page extraction). A thin httpx
wrapper mirroring `GraphClient` — all network errors are swallowed and returned as empty
results so a flaky search never breaks the conversation turn (degradation principle)."""
import httpx

from eventbuddy.common.logging import get_logger
from eventbuddy.config import settings

log = get_logger("integrations.web")

TAVILY_BASE = "https://api.tavily.com"
# Cap extracted page text so a single fetch can't blow the 4096-token working window.
_FETCH_CHAR_BUDGET = 6000


class WebSearchClient:
    """Tavily search + extract. Construct only when an API key is configured."""

    def __init__(self, api_key: str | None = None, http=None, *, timeout: int | None = None):
        self._key = api_key or settings.tavily_api_key
        self._http = http or httpx.Client(
            base_url=TAVILY_BASE, timeout=timeout or settings.web_search_timeout
        )

    def search(self, query: str, max_results: int | None = None) -> list[dict]:
        """Web search → `[{title, url, snippet}]` (most relevant first). Empty on any error."""
        try:
            r = self._http.post("/search", json={
                "api_key": self._key,
                "query": query,
                "max_results": max_results or settings.web_search_max_results,
                "search_depth": "basic",
            })
            r.raise_for_status()
            results = r.json().get("results", [])
        except Exception as e:  # noqa: BLE001 — degrade: a failed search returns nothing
            log.warning(f"web search failed ({type(e).__name__}: {e})")
            return []
        return [
            {"title": x.get("title", ""), "url": x.get("url", ""),
             "snippet": x.get("content", "")}
            for x in results
        ]

    def fetch(self, url: str) -> dict:
        """Extract a single page's main text → `{url, content}` (truncated). `{}` on error."""
        try:
            r = self._http.post("/extract", json={"api_key": self._key, "urls": [url]})
            r.raise_for_status()
            results = r.json().get("results", [])
        except Exception as e:  # noqa: BLE001
            log.warning(f"web fetch failed ({type(e).__name__}: {e})")
            return {}
        if not results:
            return {}
        content = (results[0].get("raw_content") or results[0].get("content") or "")
        return {"url": url, "content": content[:_FETCH_CHAR_BUDGET]}
