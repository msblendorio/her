"""Read/write Agent Skills under the global Cowork skills directory.

Layout (one folder per skill) under ``settings.cowork_skills_path`` —
``~/.claude/skills`` by default, which both Claude Cowork and Claude Code scan::

    ~/.claude/skills/
        <slug>/
            SKILL.md          # YAML frontmatter (name, description) + body
            <bundled files…>  # optional, referenced from SKILL.md

The frontmatter parser is deliberately tiny (the two required scalar fields,
``name`` and ``description``) so we don't pull in a YAML dependency. A skill
authored elsewhere with richer frontmatter still lists fine — we only read the
two fields we understand.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from ..config import settings

log = logging.getLogger(__name__)

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(name: str) -> str:
    slug = _SLUG_RE.sub("-", (name or "").strip().lower()).strip("-")
    return slug or "skill"


def _parse_frontmatter(text: str) -> dict[str, str]:
    """Return the leading ``--- … ---`` YAML block's top-level scalars."""
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    block = text[3:end]
    out: dict[str, str] = {}
    for line in block.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, _, value = line.partition(":")
        out[key.strip()] = value.strip().strip("'\"")
    return out


class CoworkSkillStore:
    def __init__(self, base_dir: str | Path | None = None) -> None:
        raw = str(base_dir if base_dir is not None else settings.cowork_skills_path)
        self.base_dir = Path(raw).expanduser()

    # ── Read ─────────────────────────────────────────────────────────────

    def list_skills(self) -> list[dict]:
        """Return ``[{slug, name, description}]`` for every installed skill."""
        if not self.base_dir.exists():
            return []
        out: list[dict] = []
        for entry in sorted(self.base_dir.iterdir()):
            skill_md = entry / "SKILL.md"
            if not entry.is_dir() or not skill_md.exists():
                continue
            try:
                fm = _parse_frontmatter(skill_md.read_text(encoding="utf-8"))
            except OSError:
                log.warning("cowork: cannot read %s", skill_md)
                continue
            out.append({
                "slug": entry.name,
                "name": fm.get("name", entry.name),
                "description": fm.get("description", ""),
            })
        return out

    def read_skill(self, slug: str) -> str | None:
        path = self.base_dir / slug / "SKILL.md"
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8")

    # ── Write ────────────────────────────────────────────────────────────

    def write_skill(
        self,
        name: str,
        description: str,
        body: str,
        extra_files: dict[str, str] | None = None,
    ) -> str:
        """Create/overwrite ``<slug>/SKILL.md`` (+ optional bundled files).

        Returns the canonical slug. ``name`` is normalized to a slug for the
        folder and the frontmatter ``name`` field; ``description`` and ``body``
        are written verbatim.
        """
        slug = slugify(name)
        out_dir = self.base_dir / slug
        out_dir.mkdir(parents=True, exist_ok=True)

        # Escape any stray newlines in the one-line description.
        desc = " ".join((description or "").splitlines()).strip()
        content = f"---\nname: {slug}\ndescription: {desc}\n---\n\n{body.strip()}\n"
        (out_dir / "SKILL.md").write_text(content, encoding="utf-8")

        for rel, data in (extra_files or {}).items():
            # Keep bundled files inside the skill folder (no path traversal).
            safe = Path(rel).name
            if safe and safe not in (".", ".."):
                (out_dir / safe).write_text(data, encoding="utf-8")

        log.info("cowork: wrote skill '%s' -> %s", slug, out_dir)
        return slug

    def delete_skill(self, slug: str) -> bool:
        import shutil
        target = self.base_dir / slug
        if not target.exists():
            return False
        try:
            shutil.rmtree(target)
        except OSError:
            log.exception("cowork: failed to delete %s", target)
            return False
        return True


# Process-wide singleton.
skill_store = CoworkSkillStore()
