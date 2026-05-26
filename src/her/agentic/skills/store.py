"""On-disk persistence of learned skills.

Layout under ``settings.skills_path``::

    skills/
        index.json                 # {<slug>: {name, description, summary, ...}}
        <slug>/
            trace.jsonl            # raw event log (one JSON per line)
            script.applescript     # compiled script (LLM output)
            shots/                 # screenshots used during compilation
                001.png ...

The index is the source of truth for *what skills exist*. Individual
script/trace files are looked up by slug; missing files just mean the
skill can't be run / recompiled and is reported as such to the model.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from .recorder import SkillRecording, slugify

log = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


class SkillStore:
    def __init__(self, base_dir: str | Path) -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.index_path = self.base_dir / "index.json"

    # Index --------------------------------------------------------------

    def _load_index(self) -> dict[str, dict]:
        if not self.index_path.exists():
            return {}
        try:
            return json.loads(self.index_path.read_text(encoding="utf-8"))
        except Exception:
            log.exception("skills: index corrupted, returning empty")
            return {}

    def _save_index(self, idx: dict[str, dict]) -> None:
        tmp = self.index_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(idx, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.index_path)

    # Public API --------------------------------------------------------

    def list_skills(self) -> list[dict]:
        """Return a sorted list of skill metadata records.

        Each record has ``slug``, ``name``, ``description``, ``summary``,
        ``created_at``, and ``event_count``.
        """
        idx = self._load_index()
        return [{"slug": k, **v} for k, v in sorted(idx.items())]

    def get(self, slug: str) -> dict | None:
        return self._load_index().get(slug)

    def script_path(self, slug: str) -> Path:
        return self.base_dir / slug / "script.applescript"

    def save_recording(
        self,
        rec: SkillRecording,
        script: str,
        summary: str,
    ) -> str:
        """Persist a finished recording: trace, script, and index entry.

        Returns the canonical slug under which it was stored.
        """
        slug = slugify(rec.name)
        out_dir = rec.out_dir if rec.out_dir is not None else (self.base_dir / slug)
        out_dir.mkdir(parents=True, exist_ok=True)

        trace_path = out_dir / "trace.jsonl"
        with open(trace_path, "w", encoding="utf-8") as f:
            for evt in rec.events:
                f.write(json.dumps(asdict(evt), ensure_ascii=False) + "\n")

        (out_dir / "script.applescript").write_text(script, encoding="utf-8")

        idx = self._load_index()
        idx[slug] = {
            "name": rec.name,
            "description": rec.description,
            "summary": summary,
            "created_at": _now_iso(),
            "event_count": len(rec.events),
        }
        self._save_index(idx)
        log.info("skills: saved '%s' (%d events)", slug, len(rec.events))
        return slug

    def delete(self, slug: str) -> bool:
        """Remove a skill's index entry and on-disk files. Returns True
        if the skill existed, False otherwise.
        """
        idx = self._load_index()
        if slug not in idx:
            return False
        del idx[slug]
        self._save_index(idx)
        # Wipe the per-skill folder (best-effort, ignore missing).
        import shutil
        try:
            shutil.rmtree(self.base_dir / slug)
        except FileNotFoundError:
            pass
        except Exception:
            log.exception("skills: failed to delete folder for %s", slug)
        return True
