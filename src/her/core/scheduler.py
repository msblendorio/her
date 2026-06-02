"""Time-based autonomy for Samantha.

Two complementary mechanisms, both alive only while a session is running
(the orchestrator starts/stops their loops in start()/stop()):

* **Schedule** — user-defined tasks that fire at fixed times, expressed as
  standard 5-field cron strings (``minute hour day-of-month month
  day-of-week``). When a job is due, its prompt is handed to Samantha as if
  the moment had arrived to do it. Jobs persist to ``schedule.json``.

* **Pulse** — a recurring ambient tick. Every ``interval`` seconds Samantha
  gets a quiet self-check nudge and *decides on her own* whether anything is
  worth saying. Persisted on/off + interval lives in user preferences.

This module owns the cron parsing/matching (dependency-free) and the
persisted ``ScheduleStore``. The runtime loops that consume them live in the
orchestrator, which has the realtime session to push to.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)


# ── Cron parsing / matching ──────────────────────────────────────────────
# A compact implementation of the classic Vixie-cron 5-field syntax. Each
# field supports ``*``, single values, ``a-b`` ranges, comma lists, and
# ``*/n`` / ``a-b/n`` steps. No external dependency — croniter would be
# overkill for what is a handful of lines.

_FIELD_BOUNDS = [
    (0, 59),   # minute
    (0, 23),   # hour
    (1, 31),   # day of month
    (1, 12),   # month
    (0, 7),    # day of week (0 and 7 are both Sunday)
]


def _parse_field(field_str: str, lo: int, hi: int) -> set[int]:
    """Expand one cron field into the concrete set of values it matches.

    Raises ValueError on anything malformed or out of range.
    """
    values: set[int] = set()
    for part in field_str.split(","):
        part = part.strip()
        if not part:
            raise ValueError(f"empty term in cron field {field_str!r}")

        step = 1
        rng = part
        if "/" in part:
            rng, _, step_str = part.partition("/")
            try:
                step = int(step_str)
            except ValueError as e:
                raise ValueError(f"bad step {step_str!r} in {part!r}") from e
            if step <= 0:
                raise ValueError(f"step must be positive in {part!r}")

        if rng == "*":
            start, end = lo, hi
        elif "-" in rng:
            a, _, b = rng.partition("-")
            try:
                start, end = int(a), int(b)
            except ValueError as e:
                raise ValueError(f"bad range {rng!r}") from e
        else:
            try:
                start = end = int(rng)
            except ValueError as e:
                raise ValueError(f"bad value {rng!r}") from e

        if start < lo or end > hi or start > end:
            raise ValueError(
                f"cron value {rng!r} out of range [{lo},{hi}] or reversed"
            )
        values.update(range(start, end + 1, step))
    return values


def _split_cron(expr: str) -> list[str]:
    fields = expr.split()
    if len(fields) != 5:
        raise ValueError(
            f"cron expression must have 5 fields, got {len(fields)}: {expr!r}"
        )
    return fields


def cron_matches(expr: str, when: datetime) -> bool:
    """True when ``when`` (a naive/local datetime) satisfies the cron ``expr``.

    Follows the standard cron quirk: when *both* day-of-month and day-of-week
    are restricted (neither is ``*``), the job runs if *either* matches.
    """
    fields = _split_cron(expr)
    minutes = _parse_field(fields[0], *_FIELD_BOUNDS[0])
    hours = _parse_field(fields[1], *_FIELD_BOUNDS[1])
    doms = _parse_field(fields[2], *_FIELD_BOUNDS[2])
    months = _parse_field(fields[3], *_FIELD_BOUNDS[3])
    dows = _parse_field(fields[4], *_FIELD_BOUNDS[4])
    if 7 in dows:  # normalise Sunday
        dows = (dows - {7}) | {0}

    if when.minute not in minutes:
        return False
    if when.hour not in hours:
        return False
    if when.month not in months:
        return False

    # Python weekday(): Mon=0..Sun=6 ; cron dow: Sun=0..Sat=6.
    cron_dow = (when.weekday() + 1) % 7
    dom_star = fields[2].strip() == "*"
    dow_star = fields[4].strip() == "*"
    dom_ok = when.day in doms
    dow_ok = cron_dow in dows

    if dom_star and dow_star:
        return True
    if dom_star:
        return dow_ok
    if dow_star:
        return dom_ok
    return dom_ok or dow_ok


def validate_cron(expr: str) -> bool:
    """Return True if ``expr`` is a well-formed 5-field cron string."""
    try:
        cron_matches(expr, datetime(2000, 1, 1))
        return True
    except (ValueError, TypeError):
        return False


def minute_marker(when: datetime) -> str:
    """A per-minute key used to de-duplicate firings within the same minute."""
    return when.strftime("%Y-%m-%dT%H:%M")


# ── Persisted schedule store ─────────────────────────────────────────────


@dataclass
class ScheduleJob:
    id: str
    when: str            # 5-field cron expression
    prompt: str          # what Samantha should do when it fires
    enabled: bool = True
    last_run: str = ""   # minute_marker of the last firing (dedupe)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ScheduleJob":
        return cls(
            id=str(d.get("id") or uuid.uuid4().hex[:8]),
            when=str(d.get("when", "")),
            prompt=str(d.get("prompt", "")),
            enabled=bool(d.get("enabled", True)),
            last_run=str(d.get("last_run", "")),
            created_at=str(d.get("created_at", "")) or datetime.now().isoformat(timespec="seconds"),
        )


class ScheduleStore:
    """A small JSON-backed list of cron jobs, written atomically."""

    def __init__(self, path: str) -> None:
        self.path = Path(path)

    def _read(self) -> list[ScheduleJob]:
        try:
            raw = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return []
        except OSError:
            log.warning("schedule: could not read %s", self.path)
            return []
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            log.warning("schedule: %s is not valid JSON — starting empty", self.path)
            return []
        if not isinstance(data, list):
            return []
        return [ScheduleJob.from_dict(d) for d in data if isinstance(d, dict)]

    def _write(self, jobs: list[ScheduleJob]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(
            dir=str(self.path.parent), prefix=".schedule_", suffix=".json"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump([j.to_dict() for j in jobs], f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def list(self) -> list[ScheduleJob]:
        return self._read()

    def add(self, when: str, prompt: str) -> ScheduleJob:
        """Validate and append a new job. Raises ValueError on a bad cron."""
        when = (when or "").strip()
        prompt = (prompt or "").strip()
        if not validate_cron(when):
            raise ValueError(f"invalid cron expression: {when!r}")
        if not prompt:
            raise ValueError("schedule job needs a prompt")
        jobs = self._read()
        job = ScheduleJob(id=uuid.uuid4().hex[:8], when=when, prompt=prompt)
        jobs.append(job)
        self._write(jobs)
        return job

    def remove(self, job_id: str) -> bool:
        jobs = self._read()
        kept = [j for j in jobs if j.id != job_id]
        if len(kept) == len(jobs):
            return False
        self._write(kept)
        return True

    def toggle(self, job_id: str, enabled: bool | None = None) -> ScheduleJob | None:
        jobs = self._read()
        target: ScheduleJob | None = None
        for j in jobs:
            if j.id == job_id:
                j.enabled = (not j.enabled) if enabled is None else bool(enabled)
                target = j
                break
        if target is None:
            return None
        self._write(jobs)
        return target

    def mark_ran(self, job_id: str, marker: str) -> None:
        jobs = self._read()
        changed = False
        for j in jobs:
            if j.id == job_id:
                j.last_run = marker
                changed = True
                break
        if changed:
            self._write(jobs)

    def due(self, when: datetime) -> list[ScheduleJob]:
        """Enabled jobs whose cron matches ``when`` and which haven't already
        fired this minute. Bad cron strings are skipped defensively.
        """
        marker = minute_marker(when)
        out: list[ScheduleJob] = []
        for j in self._read():
            if not j.enabled or j.last_run == marker:
                continue
            try:
                if cron_matches(j.when, when):
                    out.append(j)
            except ValueError:
                log.warning("schedule: skipping job %s with bad cron %r", j.id, j.when)
        return out
