"""Unit tests for the live empathy signal."""
from __future__ import annotations

from her.reasoning.empathy import EmpathyTracker, detect_mood


# ---------- detect_mood --------------------------------------------------


def test_detect_mood_distress_wins_over_question():
    assert detect_mood("perché sono così triste?") == "distressed"


def test_detect_mood_playful_from_emoticons():
    assert detect_mood("hahaha that's wild!!") == "playful"


def test_detect_mood_curious_from_question_mark():
    assert detect_mood("ma davvero funziona così?") == "curious"


def test_detect_mood_curt_for_very_short_input():
    assert detect_mood("ok grazie") == "curt"


def test_detect_mood_calm_for_neutral_sentence():
    assert detect_mood("oggi ho pranzato in giardino con mia madre.") == "calm"


def test_detect_mood_empty_string_is_calm():
    assert detect_mood("") == "calm"


# ---------- EmpathyTracker (no event bus involved) -----------------------


def test_tracker_starts_calm_and_flips_to_distressed():
    t = EmpathyTracker()
    assert t.current == "calm"
    # Three distressed turns should clearly carry the aggregate.
    t.ingest("mi sento triste e stanco")
    t.ingest("sono molto preoccupato per il lavoro")
    t.ingest("non ce la faccio, sono sopraffatto")
    assert t.current == "distressed"


def test_tracker_only_flips_when_aggregate_changes():
    t = EmpathyTracker()
    # A single distress turn followed by neutral ones should not be enough
    # to keep us in 'distressed' — the rolling window averages it out.
    t.ingest("sono triste oggi")
    assert t.current == "distressed"
    t.ingest("ho cucinato la pasta")
    t.ingest("ho letto il giornale")
    t.ingest("è stata una giornata tranquilla")
    # Window is 4; only one distressed turn remains -> tie-break on
    # priority would still favor distressed if it had equal count, but
    # 'calm' now dominates the ring.
    assert t.current == "calm"


def test_tracker_tie_break_favors_stronger_signal():
    t = EmpathyTracker()
    # Two distressed + two playful in the window — tie on count, distress
    # wins on priority.
    t.ingest("sono triste oggi")
    t.ingest("mi sento depresso da settimane")
    t.ingest("hahaha che spasso davvero")
    t.ingest("scherzo, davvero divertente")
    assert t.current == "distressed"
