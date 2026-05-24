"""macOS Calendar via EventKit — read and write the user's calendars.

This gives Samantha agency over Google Calendar *without* an OAuth flow:
macOS Calendar already syncs Google (and iCloud, Exchange, …) when the
account is configured in System Settings → Internet Accounts. EventKit
is the system-level API on top of that store.

Permission model: the first call surfaces the standard macOS prompt
("her would like to access your Calendar"). The grant is recorded per
parent process — Terminal, PyCharm, Cursor — exactly like Screen
Recording. A denied or pending grant raises CalendarUnavailable so the
model can fall back gracefully.
"""
from __future__ import annotations

import asyncio
import logging
import sys
from datetime import datetime, timedelta
from threading import Event as ThreadEvent

from .registry import tool

log = logging.getLogger(__name__)


class CalendarUnavailable(RuntimeError):
    """Raised when EventKit can't be used (non-macOS, missing pyobjc, or denied)."""


def _import_eventkit():
    if sys.platform != "darwin":
        raise CalendarUnavailable("macOS Calendar is only available on macOS")
    try:
        import EventKit
        import Foundation
        return EventKit, Foundation
    except ImportError as e:
        raise CalendarUnavailable(
            "pyobjc-framework-EventKit is not installed "
            "(pip install pyobjc-framework-EventKit)"
        ) from e


# EKAuthorizationStatus values (stable across recent macOS versions):
# 0 = NotDetermined, 1 = Restricted, 2 = Denied,
# 3 = FullAccess (formerly Authorized), 4 = WriteOnly
_STATUS_FULL = 3
_STATUS_WRITE_ONLY = 4
_STATUS_NOT_DETERMINED = 0


_store = None
_access_checked = False


def _get_store():
    """Lazy-init a process-wide EKEventStore."""
    global _store
    EventKit, _ = _import_eventkit()
    if _store is None:
        _store = EventKit.EKEventStore.alloc().init()
    return _store


def _ensure_access_sync(write: bool = False) -> None:
    """Block until Calendar access is granted, or raise.

    On macOS 14+ uses `requestFullAccessToEventsWithCompletion_`; older
    systems fall back to `requestAccessToEntityType_completion_`. Status
    is cached after the first successful check.
    """
    global _access_checked
    EventKit, _ = _import_eventkit()
    store = _get_store()

    status = EventKit.EKEventStore.authorizationStatusForEntityType_(
        EventKit.EKEntityTypeEvent
    )
    if status == _STATUS_FULL:
        _access_checked = True
        return
    if status == _STATUS_WRITE_ONLY and write:
        _access_checked = True
        return
    if status in (1, 2):  # Restricted, Denied
        raise CalendarUnavailable(
            "Calendar access denied — grant 'Calendars' to the parent "
            "process in System Settings → Privacy & Security → Calendars."
        )

    # NotDetermined (or WriteOnly with read needed): trigger the prompt.
    done = ThreadEvent()
    outcome: dict[str, object] = {"granted": False, "error": None}

    def handler(granted, error):
        outcome["granted"] = bool(granted)
        outcome["error"] = error
        done.set()

    if hasattr(store, "requestFullAccessToEventsWithCompletion_"):
        store.requestFullAccessToEventsWithCompletion_(handler)
    else:
        store.requestAccessToEntityType_completion_(
            EventKit.EKEntityTypeEvent, handler
        )

    if not done.wait(timeout=60):
        raise CalendarUnavailable("Calendar access prompt timed out")
    if not outcome["granted"]:
        raise CalendarUnavailable(
            f"Calendar access denied by user ({outcome['error']})"
        )
    _access_checked = True


def _to_nsdate(dt: datetime):
    _, Foundation = _import_eventkit()
    return Foundation.NSDate.dateWithTimeIntervalSince1970_(dt.timestamp())


def _from_nsdate(nsdate) -> datetime:
    return datetime.fromtimestamp(nsdate.timeIntervalSince1970()).astimezone()


def _parse_iso(s: str) -> datetime:
    """Parse ISO 8601. Naive timestamps are treated as local time."""
    if not s or not s.strip():
        raise ValueError("empty datetime string")
    s = s.strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        # astimezone() on a naive datetime treats it as local — exactly what
        # the user means when they say "tomorrow at 3pm".
        dt = dt.astimezone()
    return dt


def _resolve_window(when: str) -> tuple[datetime, datetime]:
    """Map a semantic keyword (or ISO date) to a [start, end) datetime range."""
    today = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
    key = (when or "today").strip().lower()
    if key == "today":
        return today, today + timedelta(days=1)
    if key == "tomorrow":
        return today + timedelta(days=1), today + timedelta(days=2)
    if key in ("week", "this_week", "next_7_days", "7_days"):
        return today, today + timedelta(days=7)
    if key in ("month", "next_30_days", "30_days"):
        return today, today + timedelta(days=30)
    # Try YYYY-MM-DD or full ISO.
    try:
        day = _parse_iso(key).replace(hour=0, minute=0, second=0, microsecond=0)
        return day, day + timedelta(days=1)
    except ValueError as e:
        raise ValueError(
            f"unknown 'when' value: {when!r}. "
            "Use today/tomorrow/this_week/next_30_days, or an ISO date."
        ) from e


def _event_to_dict(event) -> dict:
    cal = event.calendar()
    source = cal.source() if cal is not None else None
    start = _from_nsdate(event.startDate())
    end = _from_nsdate(event.endDate()) if event.endDate() is not None else start
    return {
        "title": str(event.title() or ""),
        "start": start.isoformat(timespec="minutes"),
        "end": end.isoformat(timespec="minutes"),
        "all_day": bool(event.isAllDay()),
        "location": str(event.location() or ""),
        "calendar": str(cal.title() or "") if cal is not None else "",
        "account": str(source.title() or "") if source is not None else "",
    }


def _matches_calendar_filter(event, name_filter: str) -> bool:
    if not name_filter:
        return True
    cal = event.calendar()
    if cal is None:
        return False
    needle = name_filter.lower()
    if needle in (cal.title() or "").lower():
        return True
    src = cal.source()
    if src is not None and needle in (src.title() or "").lower():
        return True
    return False


def _list_events_sync(when: str, max_results: int, calendar_filter: str) -> list[dict]:
    _ensure_access_sync(write=False)
    EventKit, _ = _import_eventkit()
    store = _get_store()

    start, end = _resolve_window(when)
    predicate = store.predicateForEventsWithStartDate_endDate_calendars_(
        _to_nsdate(start), _to_nsdate(end), None
    )
    events = list(store.eventsMatchingPredicate_(predicate) or [])
    events.sort(key=lambda e: e.startDate().timeIntervalSince1970())

    out: list[dict] = []
    for ev in events:
        if not _matches_calendar_filter(ev, calendar_filter):
            continue
        out.append(_event_to_dict(ev))
        if len(out) >= max(1, int(max_results)):
            break
    return out


def _search_events_sync(query: str, days_ahead: int, calendar_filter: str) -> list[dict]:
    _ensure_access_sync(write=False)
    EventKit, _ = _import_eventkit()
    store = _get_store()

    now = datetime.now().astimezone()
    end = now + timedelta(days=max(1, int(days_ahead)))
    predicate = store.predicateForEventsWithStartDate_endDate_calendars_(
        _to_nsdate(now), _to_nsdate(end), None
    )
    events = list(store.eventsMatchingPredicate_(predicate) or [])
    needle = (query or "").lower().strip()
    matches: list[dict] = []
    for ev in events:
        if not _matches_calendar_filter(ev, calendar_filter):
            continue
        title = str(ev.title() or "").lower()
        notes = str(ev.notes() or "").lower()
        location = str(ev.location() or "").lower()
        if needle and needle not in title and needle not in notes and needle not in location:
            continue
        matches.append(_event_to_dict(ev))
    matches.sort(key=lambda e: e["start"])
    return matches


def _resolve_calendar(store, calendar_name: str, account_name: str):
    """Pick the target EKCalendar for a write. Falls back to the default."""
    if calendar_name or account_name:
        for cal in store.calendarsForEntityType_(_import_eventkit()[0].EKEntityTypeEvent):
            if calendar_name and (cal.title() or "").lower() != calendar_name.lower():
                continue
            src = cal.source()
            if account_name and (src is None or (src.title() or "").lower() != account_name.lower()):
                continue
            if cal.allowsContentModifications():
                return cal
    return store.defaultCalendarForNewEvents()


def _create_event_sync(
    title: str,
    start_iso: str,
    end_iso: str,
    location: str,
    notes: str,
    calendar_name: str,
    account_name: str,
) -> dict:
    _ensure_access_sync(write=True)
    EventKit, Foundation = _import_eventkit()
    store = _get_store()

    start_dt = _parse_iso(start_iso)
    end_dt = _parse_iso(end_iso) if end_iso else start_dt + timedelta(hours=1)
    if end_dt <= start_dt:
        raise ValueError("end must be after start")

    target_cal = _resolve_calendar(store, calendar_name, account_name)
    if target_cal is None:
        raise CalendarUnavailable("no writable calendar found")

    event = EventKit.EKEvent.eventWithEventStore_(store)
    event.setTitle_(title or "(no title)")
    event.setStartDate_(_to_nsdate(start_dt))
    event.setEndDate_(_to_nsdate(end_dt))
    event.setCalendar_(target_cal)
    if location:
        event.setLocation_(location)
    if notes:
        event.setNotes_(notes)

    ok, err = store.saveEvent_span_error_(event, EventKit.EKSpanThisEvent, None)
    if not ok:
        raise CalendarUnavailable(f"could not save event: {err}")
    return _event_to_dict(event)


def is_available() -> bool:
    """Best-effort probe; does NOT trigger the access prompt."""
    if sys.platform != "darwin":
        return False
    try:
        EventKit, _ = _import_eventkit()
    except CalendarUnavailable:
        return False
    status = EventKit.EKEventStore.authorizationStatusForEntityType_(
        EventKit.EKEntityTypeEvent
    )
    # Available if we have full access, or we haven't asked yet (call will prompt).
    return status in (_STATUS_FULL, _STATUS_NOT_DETERMINED)


@tool(
    name="calendar_list_events",
    params={"max_results": {"minimum": 1, "maximum": 50}},
)
async def list_events(
    when: str = "today",
    max_results: int = 10,
    calendar_filter: str = "",
) -> list[dict]:
    """List the user's upcoming calendar events from the macOS Calendar store
    (which also reflects Google Calendar when the Google account is set up in
    System Settings → Internet Accounts). Use when the user asks 'what's on my
    agenda today?', 'do I have anything tomorrow?', 'what's this week?'.
    Returns a JSON array of {title, start, end, location, calendar, account}.

    Args:
        when: Time window — 'today' (default), 'tomorrow', 'this_week' (next 7d),
            'next_30_days', or a specific date as 'YYYY-MM-DD'.
        max_results: Cap on results (default 10).
        calendar_filter: Optional substring matched against calendar title OR
            account name (e.g. 'Google', 'gmail').
    """
    return await asyncio.to_thread(_list_events_sync, when, max_results, calendar_filter)


@tool(
    name="calendar_search_events",
    params={"days_ahead": {"minimum": 1, "maximum": 365}},
)
async def search_events(
    query: str,
    days_ahead: int = 30,
    calendar_filter: str = "",
) -> list[dict]:
    """Search the user's calendar for upcoming events whose title, notes, or
    location contain the given text. Use this for 'when is my meeting with X?',
    'do I have a dentist appointment scheduled?'.

    Args:
        query: Text to search for.
        days_ahead: How many days into the future to search (default 30).
        calendar_filter: Optional calendar/account name substring filter.
    """
    return await asyncio.to_thread(_search_events_sync, query, days_ahead, calendar_filter)


@tool(name="calendar_create_event", safe=False)
async def create_event(
    title: str,
    start: str,
    end: str = "",
    location: str = "",
    notes: str = "",
    calendar: str = "",
    account: str = "",
) -> dict:
    """Create a new event on the user's calendar (defaults to the user's primary
    calendar — typically Google if it's set as default in Calendar.app). Confirm
    the title, start, end and target calendar with the user verbally BEFORE calling.
    `start` and `end` are ISO 8601 strings; if `end` is omitted the event lasts 1 hour.

    Args:
        title: Event title.
        start: ISO 8601 start datetime, e.g. '2026-05-24T15:00'. Naive = local time.
        end: ISO 8601 end datetime. Omit for a 1h default.
        location: Optional location.
        notes: Optional notes / description.
        calendar: Optional target calendar title (exact match), e.g. 'Work'.
        account: Optional account, e.g. 'Google' or 'gmail.com', when you have
            multiple calendars with the same title.
    """
    return await asyncio.to_thread(
        _create_event_sync, title, start, end, location, notes, calendar, account
    )
