"""Voice tools for the knowledge-base wiki: list, read, ingest, query, lint.

Registered with the agentic registry on import. ``list``/``read``/``query`` are
read-only; ``ingest`` and ``lint`` are marked unsafe (they write or run a full
LLM pass) so the model confirms before invoking them on its own.
"""
from __future__ import annotations

import asyncio
import logging

from ...agentic.registry import tool
from ...core.event_bus import bus
from .engine import engine
from .store import store

log = logging.getLogger(__name__)


@tool()
async def wiki_list_pages() -> list[dict]:
    """List the pages in the knowledge wiki (the user's personal knowledge
    base). Each entry has slug, title, and a one-line summary. Call this when
    the user asks what's in their knowledge base or before querying it.
    """
    return await asyncio.to_thread(store.list_pages)


@tool()
async def wiki_read_page(slug: str) -> str:
    """Read one wiki page in full by its slug. Use after wiki_list_pages when
    the user wants the detail of a specific entry.

    Args:
        slug: The page slug as returned by wiki_list_pages.
    """
    body = await asyncio.to_thread(store.page_body, slug)
    if body is None:
        return f"no wiki page named '{slug}'"
    return body


@tool(safe=False)
async def wiki_ingest(text: str, title: str = "") -> str:
    """Add a source to the knowledge wiki: Claude reads it and updates the
    interlinked pages. Use when the user wants to remember/file durable
    knowledge — notes, an article, a decision, research (e.g. "salva questo
    nella mia knowledge base", "add this to my wiki", "remember this long-term").
    This is for lasting knowledge, distinct from short conversational memory.

    Args:
        text: The source content to integrate into the wiki.
        title: Optional short label for the source (helps name the pages).
    """
    text = (text or "").strip()
    if not text:
        raise RuntimeError("nothing to ingest")
    result = await engine.ingest(text, title)
    bus.publish("wiki.ingested", {"title": title})
    return result


@tool()
async def wiki_query(question: str) -> str:
    """Answer a question from the knowledge wiki. Use when the user asks about
    something they've filed in their knowledge base, or to look up durable facts
    they've saved (e.g. "cosa dice la mia wiki su…", "what did I save about…").

    Args:
        question: The question to answer from the wiki.
    """
    question = (question or "").strip()
    if not question:
        raise RuntimeError("a question is required")
    return await engine.query(question)


@tool(safe=False)
async def wiki_lint() -> str:
    """Run a health check over the knowledge wiki — surface contradictions,
    stale claims, orphan pages, and gaps. Call this when the user asks to
    review, tidy, or check the consistency of their knowledge base.
    """
    return await engine.lint()
