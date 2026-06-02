"""Unit tests for the time-based autonomy scheduler.

Covers the dependency-free cron matcher/validator and the persisted
ScheduleStore. The runtime loops live in the orchestrator and aren't
exercised here — these tests keep the pure logic honest.
"""
from __future__ import annotations

from datetime import datetime

import pytest

from her.core.scheduler import (
    ScheduleStore,
    _parse_field,
    cron_matches,
    minute_marker,
    validate_cron,
)


# ---------- _parse_field --------------------------------------------------


def test_parse_field_star():
    assert _parse_field("*", 0, 5) == {0, 1, 2, 3, 4, 5}


def test_parse_field_value_range_list_step():
    assert _parse_field("3", 0, 59) == {3}
    assert _parse_field("1-3", 0, 59) == {1, 2, 3}
    assert _parse_field("1,4,7", 0, 59) == {1, 4, 7}
    assert _parse_field("*/15", 0, 59) == {0, 15, 30, 45}
    assert _parse_field("10-20/5", 0, 59) == {10, 15, 20}


@pytest.mark.parametrize("bad", ["", "1-", "x", "70", "5-1", "*/0", "1-99"])
def test_parse_field_rejects_garbage(bad):
    with pytest.raises(ValueError):
        _parse_field(bad, 0, 59)


# ---------- cron_matches --------------------------------------------------


def test_cron_every_minute():
    assert cron_matches("* * * * *", datetime(2026, 6, 2, 14, 37))


def test_cron_specific_time():
    expr = "30 9 * * *"
    assert cron_matches(expr, datetime(2026, 6, 2, 9, 30))
    assert not cron_matches(expr, datetime(2026, 6, 2, 9, 31))
    assert not cron_matches(expr, datetime(2026, 6, 2, 10, 30))


def test_cron_day_of_week():
    # 2026-06-01 is a Monday. cron dow Monday == 1.
    monday = datetime(2026, 6, 1, 8, 0)
    assert cron_matches("0 8 * * 1", monday)
    assert not cron_matches("0 8 * * 2", monday)


def test_cron_sunday_is_both_0_and_7():
    sunday = datetime(2026, 6, 7, 12, 0)  # a Sunday
    assert cron_matches("0 12 * * 0", sunday)
    assert cron_matches("0 12 * * 7", sunday)


def test_cron_dom_dow_or_semantics():
    # When both DOM and DOW are restricted, EITHER matching fires the job.
    expr = "0 0 13 * 5"  # the 13th OR any Friday
    assert cron_matches(expr, datetime(2026, 11, 13, 0, 0))   # Friday the 13th
    assert cron_matches(expr, datetime(2026, 6, 5, 0, 0))     # a Friday, not 13th
    assert cron_matches(expr, datetime(2026, 6, 13, 0, 0))    # the 13th, a Saturday
    assert not cron_matches(expr, datetime(2026, 6, 4, 0, 0)) # neither


def test_cron_step_minutes():
    assert cron_matches("*/15 * * * *", datetime(2026, 6, 2, 10, 0))
    assert cron_matches("*/15 * * * *", datetime(2026, 6, 2, 10, 45))
    assert not cron_matches("*/15 * * * *", datetime(2026, 6, 2, 10, 7))


# ---------- validate_cron -------------------------------------------------


@pytest.mark.parametrize("good", ["* * * * *", "0 9 * * 1-5", "*/10 0-6 1,15 */2 *"])
def test_validate_cron_accepts(good):
    assert validate_cron(good)


@pytest.mark.parametrize("bad", ["", "* * * *", "* * * * * *", "99 * * * *", "a b c d e"])
def test_validate_cron_rejects(bad):
    assert not validate_cron(bad)


def test_minute_marker_stable_within_minute():
    a = minute_marker(datetime(2026, 6, 2, 9, 30, 1))
    b = minute_marker(datetime(2026, 6, 2, 9, 30, 59))
    c = minute_marker(datetime(2026, 6, 2, 9, 31, 0))
    assert a == b
    assert a != c


# ---------- ScheduleStore -------------------------------------------------


def test_store_add_list_remove(tmp_path):
    store = ScheduleStore(str(tmp_path / "schedule.json"))
    assert store.list() == []

    job = store.add("0 9 * * *", "buongiorno")
    assert job.when == "0 9 * * *"
    assert job.prompt == "buongiorno"
    assert job.enabled

    jobs = store.list()
    assert len(jobs) == 1
    assert jobs[0].id == job.id

    assert store.remove(job.id) is True
    assert store.list() == []
    assert store.remove(job.id) is False


def test_store_add_rejects_bad_cron(tmp_path):
    store = ScheduleStore(str(tmp_path / "schedule.json"))
    with pytest.raises(ValueError):
        store.add("not a cron", "x")
    with pytest.raises(ValueError):
        store.add("* * * * *", "   ")


def test_store_toggle(tmp_path):
    store = ScheduleStore(str(tmp_path / "schedule.json"))
    job = store.add("* * * * *", "tick")
    assert store.toggle(job.id).enabled is False
    assert store.toggle(job.id).enabled is True
    assert store.toggle(job.id, enabled=False).enabled is False
    assert store.toggle("nope") is None


def test_store_due_respects_enabled_and_marker(tmp_path):
    store = ScheduleStore(str(tmp_path / "schedule.json"))
    job = store.add("30 9 * * *", "wake")
    when = datetime(2026, 6, 2, 9, 30)

    due = store.due(when)
    assert [j.id for j in due] == [job.id]

    # Once marked as run this minute, it should not be due again.
    store.mark_ran(job.id, minute_marker(when))
    assert store.due(when) == []

    # Disabled jobs are never due.
    store.toggle(job.id, enabled=True)
    store.mark_ran(job.id, "")  # clear marker
    store.toggle(job.id, enabled=False)
    assert store.due(when) == []


def test_store_survives_corrupt_file(tmp_path):
    p = tmp_path / "schedule.json"
    p.write_text("{ not json", encoding="utf-8")
    store = ScheduleStore(str(p))
    assert store.list() == []  # degrades gracefully
