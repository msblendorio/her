"""On-disk layout for AST (everything under ``data/``, which is gitignored).

```
data/conversations/<session_id>.jsonl   # T1 raw turns (opt-in)
data/ast/style_card.json                 # current Style Card (versioned in-file)
data/ast/index/                          # vector index for retrieval (Phase 1)
data/ast/datasets/<run>/                 # distillation + preference sets (Phase 2)
data/ast/adapters/<name>@<version>/      # persona / skill LoRA (Phase 2+)
data/ast/runs/<run>.json                 # metrics + promote/rollback decision
data/ast/youbench/                       # personal held-out benchmark
```

Only the Phase 0/1 paths (conversations, style_card, index) are written today;
the rest are created lazily by later phases. Writes that must not corrupt an
existing file go through :func:`atomic_write_json`.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger(__name__)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def atomic_write_json(path: Path, data: object) -> None:
    """Write ``data`` as pretty JSON to ``path`` atomically (temp + replace)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".ast_", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class AstStore:
    """Filesystem access for the AST data directory."""

    def __init__(self, base_path: str | Path, conversations_path: str | Path) -> None:
        self.base = Path(base_path)
        self.conversations = Path(conversations_path)

    # ── directory accessors (created on demand) ──────────────────────────
    @property
    def index_dir(self) -> Path:
        return self.base / "index"

    @property
    def datasets_dir(self) -> Path:
        return self.base / "datasets"

    @property
    def adapters_dir(self) -> Path:
        return self.base / "adapters"

    @property
    def runs_dir(self) -> Path:
        return self.base / "runs"

    @property
    def youbench_dir(self) -> Path:
        return self.base / "youbench"

    @property
    def style_card_path(self) -> Path:
        return self.base / "style_card.json"

    # ── raw turns (T1) ───────────────────────────────────────────────────
    def session_path(self, session_id: str) -> Path:
        safe = "".join(c for c in session_id if c.isalnum() or c in "-_") or "session"
        return self.conversations / f"{safe}.jsonl"

    def append_turn(self, session_id: str, record: dict) -> None:
        """Append one raw-turn record (already redacted) to its session file."""
        path = self.session_path(session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def list_sessions(self) -> list[Path]:
        if not self.conversations.exists():
            return []
        return sorted(
            self.conversations.glob("*.jsonl"),
            key=lambda p: p.stat().st_mtime,
        )

    def read_turns(self, path: Path) -> list[dict]:
        out: list[dict] = []
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        except OSError:
            return []
        return out

    def recent_turns(self, max_sessions: int = 20) -> list[dict]:
        """Flatten the turns of the most recent ``max_sessions`` sessions."""
        turns: list[dict] = []
        for path in self.list_sessions()[-max_sessions:]:
            turns.extend(self.read_turns(path))
        return turns

    # ── retention + wipe (privacy) ───────────────────────────────────────
    def prune_retention(self, days: int) -> int:
        """Delete raw-turn session files older than ``days``. Returns the count."""
        if days <= 0:
            return 0
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).timestamp()
        removed = 0
        for path in self.list_sessions():
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink()
                    removed += 1
            except OSError:
                continue
        if removed:
            log.info("ast: pruned %d session file(s) older than %dd", removed, days)
        return removed

    def wipe_session(self, session_id: str) -> bool:
        path = self.session_path(session_id)
        try:
            path.unlink()
            return True
        except FileNotFoundError:
            return False
        except OSError:
            log.warning("ast: could not delete %s", path)
            return False

    def wipe_all_raw(self) -> int:
        """Delete every raw-turn session file (the index is rebuilt separately)."""
        removed = 0
        for path in self.list_sessions():
            try:
                path.unlink()
                removed += 1
            except OSError:
                continue
        return removed

    # ── Style Card ───────────────────────────────────────────────────────
    def load_style_card(self) -> dict | None:
        try:
            raw = self.style_card_path.read_text(encoding="utf-8")
        except (FileNotFoundError, OSError):
            return None
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return data if isinstance(data, dict) else None

    def save_style_card(self, card: dict) -> None:
        atomic_write_json(self.style_card_path, card)

    # ── stats (for /ast insights) ────────────────────────────────────────
    def stats(self) -> dict:
        sessions = self.list_sessions()
        turns = 0
        size = 0
        for p in sessions:
            try:
                size += p.stat().st_size
            except OSError:
                continue
            turns += sum(1 for _ in self.read_turns(p))
        return {
            "sessions": len(sessions),
            "turns": turns,
            "bytes": size,
        }
