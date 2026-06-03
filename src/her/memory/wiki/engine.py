"""LLM operations over the wiki: ingest, query, lint.

Each operation assembles the current wiki context (the index plus a capped set
of page bodies) and asks Claude — through the shared Cowork client — to do the
work. ``ingest`` is the only writer: Claude returns a set of page upserts that
the store applies, after which the index is rebuilt and the log appended. All
three are no-ops with a friendly message when no Anthropic credential is set.
"""
from __future__ import annotations

import asyncio
import json
import logging

from ...config import settings
from ...cowork.client import client as cowork
from .store import store
from .uploads import extract_source

log = logging.getLogger(__name__)

_INGEST_SCHEMA = {
    "type": "object",
    "properties": {
        "pages": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "slug": {"type": "string"},
                    "title": {"type": "string"},
                    "summary": {"type": "string"},
                    "action": {"type": "string", "enum": ["create", "update"]},
                    "content": {"type": "string"},
                },
                "required": ["slug", "title", "summary", "action", "content"],
                "additionalProperties": False,
            },
        },
        "log_note": {"type": "string"},
    },
    "required": ["pages", "log_note"],
    "additionalProperties": False,
}

_INGEST_SYSTEM = (
    "You maintain a persistent markdown knowledge wiki (Karpathy's LLM-wiki "
    "pattern). You are given the current index, a sample of existing pages, and "
    "a new source. Integrate the source: create new pages or update existing "
    "ones so the wiki stays consistent and interlinked. A single source often "
    "touches several pages. Rules:\n"
    "- One concept/entity/topic per page; prefer many small focused pages.\n"
    "- Cross-link related pages with [[slug]].\n"
    "- 'slug' is lowercase kebab-case. Reuse the existing slug when updating.\n"
    "- 'summary' is ONE sentence. 'content' is the page body markdown WITHOUT "
    "frontmatter, starting with a '# Title' heading.\n"
    "- If the source contradicts an existing page, note the contradiction in "
    "the page rather than silently overwriting.\n"
    "Return only the pages you create or change."
)

_QUERY_SYSTEM = (
    "You answer questions from a persistent markdown knowledge wiki. You are "
    "given the index and relevant pages. Answer concisely from the wiki, citing "
    "page titles inline. If the wiki doesn't cover it, say so plainly rather "
    "than guessing. Your answer will be read aloud, so avoid raw markdown "
    "tables and long URLs."
)

_READ_SYSTEM = (
    "You read a single file the user just shared and report what it contains, "
    "for use in the current conversation only — it will NOT be saved. Give a "
    "faithful, concise digest: the key points, facts, and anything the user "
    "would want to act on. Lead with a one-line gist, then the detail. Your "
    "output will be read aloud, so avoid raw markdown tables and long URLs."
)

_LINT_SYSTEM = (
    "You are the health-checker for a persistent markdown knowledge wiki. Given "
    "the index and pages, report: contradictions between pages, stale or "
    "duplicated claims, orphan pages (no inbound [[links]]), and gaps worth "
    "filling. Be specific and brief — a short prioritized list. Do not rewrite "
    "the pages; just report."
)


def _context_blob(include_bodies: bool = True) -> str:
    """Render the wiki context (index + capped page bodies) for the model."""
    parts = ["## Index", store.read_index().strip()]
    if include_bodies:
        pages = store.list_pages()[: max(0, settings.wiki_max_context_pages)]
        for p in pages:
            body = store.page_body(p["slug"]) or ""
            parts.append(f"## Page: {p['slug']}\n{body.strip()}")
    return "\n\n".join(parts)


class WikiEngine:
    def _ready(self) -> bool:
        return settings.wiki_enabled and cowork.is_configured()

    async def ingest(self, text: str, title: str = "") -> str:
        if not self._ready():
            return (
                "The knowledge wiki needs an Anthropic credential (API key or "
                "Claude Pro/Max token) before I can file this away."
            )
        source_label = title.strip() or "untitled source"
        return await self._run_ingest(source_label, source_text=text.strip())

    async def ingest_file(self, path: str, label: str = "") -> str:
        """Ingest an uploaded file into the wiki.

        ``.txt``/``.md``/``.docx`` are extracted to text; ``.pdf`` and images
        are handed to Opus natively as attachment blocks (see ``uploads``).
        """
        if not self._ready():
            return (
                "The knowledge wiki needs an Anthropic credential (API key or "
                "Claude Pro/Max token) before I can file this away."
            )
        src = await asyncio.to_thread(extract_source, path)
        source_label = (label or src["label"]).strip() or "untitled source"
        if src["attachments"]:
            placeholder = (
                "(the source is the attached file above — read it in full and "
                "integrate its content into the wiki)"
            )
            return await self._run_ingest(
                source_label, source_text=placeholder, attachments=src["attachments"]
            )
        return await self._run_ingest(source_label, source_text=(src["text"] or "").strip())

    async def _run_ingest(
        self,
        source_label: str,
        *,
        source_text: str = "",
        attachments: list[dict] | None = None,
    ) -> str:
        """Shared ingest path: ask Opus for page upserts, then apply them."""
        await asyncio.to_thread(store.ensure_init)
        user = f"{_context_blob()}\n\n## New source: {source_label}\n{source_text}"
        raw = await cowork.complete(
            system=_INGEST_SYSTEM,
            user=user,
            max_tokens=8000,
            json_schema=_INGEST_SCHEMA,
            attachments=attachments,
        )
        data = json.loads(raw)
        pages = data.get("pages") or []
        changed: list[str] = []
        for p in pages:
            slug = await asyncio.to_thread(
                store.write_page,
                p.get("slug", ""),
                p.get("title", ""),
                p.get("summary", ""),
                p.get("content", ""),
            )
            changed.append(slug)
        await asyncio.to_thread(store.rebuild_index)
        await asyncio.to_thread(
            store.append_log, "ingest", source_label, data.get("log_note", "")
        )
        if not changed:
            return f"Read '{source_label}', but nothing new needed filing."
        return f"Filed '{source_label}' into {len(changed)} page(s): {', '.join(changed)}."

    async def read_file(self, path: str, label: str = "") -> str:
        """Read a file with Opus and return its content for the conversation,
        without writing anything to the wiki (the 'temporary' path)."""
        if not self._ready():
            return (
                "I need an Anthropic credential before I can read that file."
            )
        src = await asyncio.to_thread(extract_source, path)
        source_label = (label or src["label"]).strip() or "the file"
        if src["attachments"]:
            user = f"## File: {source_label}\n(the file is attached above — read it)"
            return await cowork.complete(
                system=_READ_SYSTEM, user=user, max_tokens=4000,
                attachments=src["attachments"],
            )
        user = f"## File: {source_label}\n{(src['text'] or '').strip()}"
        return await cowork.complete(system=_READ_SYSTEM, user=user, max_tokens=4000)

    async def query(self, question: str) -> str:
        if not self._ready():
            return (
                "The knowledge wiki needs an Anthropic credential before I can "
                "search it."
            )
        await asyncio.to_thread(store.ensure_init)
        user = f"{_context_blob()}\n\n## Question\n{question.strip()}"
        answer = await cowork.complete(
            system=_QUERY_SYSTEM, user=user, max_tokens=4000
        )
        await asyncio.to_thread(store.append_log, "query", question.strip())
        return answer or "The wiki has nothing on that yet."

    async def lint(self) -> str:
        if not self._ready():
            return "The knowledge wiki needs an Anthropic credential before I can lint it."
        await asyncio.to_thread(store.ensure_init)
        report = await cowork.complete(
            system=_LINT_SYSTEM, user=_context_blob(), max_tokens=4000
        )
        await asyncio.to_thread(store.append_log, "lint", "health check")
        return report or "The wiki looks healthy — nothing flagged."


# Process-wide singleton.
engine = WikiEngine()
