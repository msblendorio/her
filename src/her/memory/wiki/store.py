"""Filesystem layer for the knowledge-base wiki.

Layout under ``settings.wiki_path`` (``data/wiki`` by default)::

    wiki/
        CLAUDE.md          # schema / conventions (the "protocol" layer)
        index.md           # catalog: one line per page, rebuilt on each write
        log.md             # append-only ingest/query/lint history
        pages/
            <slug>.md      # one wiki page, with a small frontmatter block

Each page carries a tiny frontmatter (``title``, ``summary``, ``updated``) so
the index can be regenerated mechanically and the recall overview stays cheap.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from ...config import settings

log = logging.getLogger(__name__)

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(name: str) -> str:
    slug = _SLUG_RE.sub("-", (name or "").strip().lower()).strip("-")
    return slug or "page"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Split ``--- … ---`` frontmatter from the body. Returns ``(meta, body)``."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    block = text[3:end]
    body = text[end + 4:].lstrip("\n")
    meta: dict[str, str] = {}
    for line in block.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip().strip("'\"")
    return meta, body


_SCHEMA_TEMPLATE = """\
# Knowledge wiki — conventions

This folder is a persistent, interlinked knowledge base maintained by Claude on
behalf of Samantha, following Andrej Karpathy's LLM-wiki pattern.

- **pages/`<slug>`.md** — one concept/entity/topic per file. Each page begins
  with frontmatter (`title`, `summary`, `updated`) followed by a `# Title`
  heading and the prose.
- **index.md** — the catalog, one line per page. Regenerated automatically; do
  not hand-edit.
- **log.md** — append-only history of ingest/query/lint operations.

Conventions:
- Cross-link related pages with `[[slug]]`.
- Keep `summary` to a single sentence — it feeds the recall overview.
- When a new source contradicts an existing page, note the contradiction on the
  page rather than silently overwriting.
- Prefer many small, focused pages over a few large ones.
"""


class WikiStore:
    def __init__(self, base_dir: str | Path | None = None) -> None:
        raw = str(base_dir if base_dir is not None else settings.wiki_path)
        self.base_dir = Path(raw).expanduser()
        self.pages_dir = self.base_dir / "pages"
        self.index_path = self.base_dir / "index.md"
        self.log_path = self.base_dir / "log.md"
        self.schema_path = self.base_dir / "CLAUDE.md"

    # ── Init ─────────────────────────────────────────────────────────────

    def ensure_init(self) -> None:
        self.pages_dir.mkdir(parents=True, exist_ok=True)
        if not self.schema_path.exists():
            self.schema_path.write_text(_SCHEMA_TEMPLATE, encoding="utf-8")
        if not self.index_path.exists():
            self.index_path.write_text("# Wiki index\n\n_(empty)_\n", encoding="utf-8")
        if not self.log_path.exists():
            self.log_path.write_text("# Wiki log\n\n", encoding="utf-8")

    # ── Pages ────────────────────────────────────────────────────────────

    def list_pages(self) -> list[dict]:
        """Return ``[{slug, title, summary, updated}]`` for every page."""
        if not self.pages_dir.exists():
            return []
        out: list[dict] = []
        for path in sorted(self.pages_dir.glob("*.md")):
            try:
                meta, _ = _parse_frontmatter(path.read_text(encoding="utf-8"))
            except OSError:
                continue
            slug = path.stem
            out.append({
                "slug": slug,
                "title": meta.get("title", slug),
                "summary": meta.get("summary", ""),
                "updated": meta.get("updated", ""),
            })
        return out

    def read_page(self, slug: str) -> str | None:
        path = self.pages_dir / f"{slugify(slug)}.md"
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8")

    def page_body(self, slug: str) -> str | None:
        """The page content without frontmatter (for feeding the model)."""
        raw = self.read_page(slug)
        if raw is None:
            return None
        _, body = _parse_frontmatter(raw)
        return body

    def write_page(self, slug: str, title: str, summary: str, body: str) -> str:
        self.pages_dir.mkdir(parents=True, exist_ok=True)
        slug = slugify(slug or title)
        summary_line = " ".join((summary or "").splitlines()).strip()
        content = (
            f"---\ntitle: {title.strip()}\nsummary: {summary_line}\n"
            f"updated: {_now_iso()}\n---\n\n{body.strip()}\n"
        )
        (self.pages_dir / f"{slug}.md").write_text(content, encoding="utf-8")
        return slug

    def delete_page(self, slug: str) -> bool:
        path = self.pages_dir / f"{slugify(slug)}.md"
        if not path.exists():
            return False
        path.unlink()
        return True

    # ── Index & log ──────────────────────────────────────────────────────

    def rebuild_index(self) -> None:
        pages = self.list_pages()
        lines = ["# Wiki index", ""]
        if not pages:
            lines.append("_(empty)_")
        else:
            for p in pages:
                summary = f" — {p['summary']}" if p["summary"] else ""
                lines.append(f"- [{p['title']}](pages/{p['slug']}.md){summary}")
        self.index_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def read_index(self) -> str:
        if not self.index_path.exists():
            return ""
        return self.index_path.read_text(encoding="utf-8")

    def append_log(self, kind: str, title: str, note: str = "") -> None:
        self.ensure_init()
        entry = f"\n## [{_today()}] {kind} | {title}\n"
        if note:
            entry += f"{note.strip()}\n"
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(entry)

    def read_schema(self) -> str:
        if not self.schema_path.exists():
            return ""
        return self.schema_path.read_text(encoding="utf-8")


# Process-wide singleton.
store = WikiStore()
