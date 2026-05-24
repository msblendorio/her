"""Web search tool — DuckDuckGo via `ddgs`.

Synchronous library, wrapped in `asyncio.to_thread` to keep the event loop
free. Returns a small list of title/url/snippet dicts suitable for the model
to read aloud and (optionally) chain into `open_url`.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from ddgs import DDGS

from .registry import tool

log = logging.getLogger(__name__)


def _search_sync(query: str, max_results: int) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for r in DDGS().text(query, max_results=max_results):
        out.append({
            "title": (r.get("title") or "").strip(),
            "url": (r.get("href") or r.get("url") or "").strip(),
            "snippet": (r.get("body") or "").strip(),
        })
    return out


@tool(params={"max_results": {"minimum": 1, "maximum": 10}})
async def web_search(query: str, max_results: int = 5) -> dict[str, Any]:
    """Search the web (DuckDuckGo) and return a short list of {title, url, snippet}.
    Use this when the user asks for facts, news, references, recipes, addresses,
    or anything you don't already know. You can then summarize the results aloud
    and optionally call open_url on the best one.

    Args:
        query: Search query, ideally in the user's language.
        max_results: How many results to return (default 5).
    """
    query = (query or "").strip()
    if not query:
        raise ValueError("query is empty")
    max_results = max(1, min(10, int(max_results)))
    try:
        results = await asyncio.to_thread(_search_sync, query, max_results)
    except Exception as e:
        log.exception("web_search failed")
        raise RuntimeError(f"search failed: {e}") from e
    return {"query": query, "count": len(results), "results": results}
