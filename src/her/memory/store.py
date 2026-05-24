"""Append-only JSONL store of past session summaries.

One line per session. Persisted to disk so Samantha can recall what was
discussed in previous sessions when a new one starts.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass
class MemoryEntry:
    timestamp: str           # ISO-8601, UTC
    summary: str             # 1-3 sentences capturing the session's gist
    key_facts: list[str] = field(default_factory=list)  # short bullets to remember
    turn_count: int = 0
    duration_s: float = 0.0
    # Visual track — what Samantha saw via the webcam during the session.
    # Empty strings / lists for sessions that didn't have visual memory on,
    # and for legacy entries written before this field existed.
    visual_summary: str = ""
    visual_facts: list[str] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_json(cls, line: str) -> "MemoryEntry":
        data = json.loads(line)
        # Tolerate unknown extra keys from future versions and missing new
        # fields from older entries. Only pass through the keys we know.
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})


class MemoryStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, entry: MemoryEntry) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(entry.to_json() + "\n")
        log.info("memory: appended entry (%d facts) -> %s", len(entry.key_facts), self.path)

    def all(self) -> list[MemoryEntry]:
        if not self.path.exists():
            return []
        out: list[MemoryEntry] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(MemoryEntry.from_json(line))
            except Exception:
                log.warning("memory: skipping malformed line")
        return out

    def recent(self, n: int) -> list[MemoryEntry]:
        return self.all()[-n:]

    def count(self) -> int:
        return len(self.all())


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def forget_cli() -> int:
    """Console-script entry point for `her-forget`.

    Wipes the persistent memory store (`settings.memory_path`). Prompts for
    confirmation unless `--yes` / `-y` is passed.
    """
    import argparse

    from ..config import settings

    parser = argparse.ArgumentParser(
        prog="her-forget",
        description="Wipe her's persistent memory of past sessions.",
    )
    parser.add_argument(
        "-y", "--yes", action="store_true", help="skip the confirmation prompt"
    )
    args = parser.parse_args()

    path = Path(settings.memory_path)
    if not path.exists():
        print(f"No memory file at {path} — nothing to forget.")
        return 0

    store = MemoryStore(path)
    n = store.count()
    print(f"About to delete {n} session summaries from {path}.")

    if not args.yes:
        try:
            reply = input("Continue? [y/N] ").strip().lower()
        except EOFError:
            reply = ""
        if reply not in ("y", "yes"):
            print("Aborted.")
            return 1

    path.unlink()
    print(f"Forgotten {n} sessions.")
    return 0
