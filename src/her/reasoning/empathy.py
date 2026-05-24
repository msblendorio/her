"""Live empathy signal — cheap, no extra LLM call.

The persistent CharacterProfile (see memory/character.py) tells Samantha
who she's talking to. This module tells her how that person sounds *right
now*: are they upset, playful, curt, curious? We sniff for it on every
user turn with light heuristics and only emit a change event when the
inferred mood actually crosses to a different bucket.

Heuristics are intentionally rough. The realtime model is good at picking
up tone on its own — our job is just to bias the system prompt slightly
so it knows whether to dial empathy up or down.
"""
from __future__ import annotations

import asyncio
import logging
import re
from collections import deque
from typing import Literal

from ..core.event_bus import bus

log = logging.getLogger(__name__)

Mood = Literal["distressed", "playful", "curious", "curt", "calm"]

_RING_SIZE = 4   # last N user turns we keep around for trend detection

# Keyword lists are deliberately small and multilingual (it/en plus a few
# es/fr/de tokens). The realtime model already understands tone — we only
# need enough signal to flip from "calm" to one of the other buckets.
# Patterns use `\b` only at the *start* of each alternative: many entries
# are stems (e.g. "preoccupat" → matches "preoccupato/a/i/e"), so a
# trailing word boundary would block them. The price is some loose
# matching mid-stem ("alone" matches "aloneness", etc.) which we accept
# — the realtime model is the real source of tone, this is just a bias.
_DISTRESS_RX = re.compile(
    r"\b(?:"
    r"sad|hurt|angry|alone|lonely|tired|exhausted|scared|afraid|anxious|worried|"
    r"stress|depress|overwhelm|broken|cry|crying|"
    r"trist|stanc|spaventat|preoccupat|ansios|"
    r"sopraffatt|piang|"
    r"fatigu|inquiet|deprim|"
    r"traurig|m[üu]de|allein|besorgt|"
    r"cansad|preocupad"
    r")",
    re.IGNORECASE,
)
_PLAYFUL_RX = re.compile(
    r"\b(?:haha|hehe|lol|lmao|jaja|hihi|"
    r"divertent|spasso|scherz|"
    r"funny|joke|kidding|"
    r"divertid|broma|"
    r"witzig|spa[ßs])",
    re.IGNORECASE,
)
_CURIOUS_RX = re.compile(
    r"\b(?:why|how come|what if|"
    r"perch[ée]|come mai|cosa succede se|"
    r"por qu[ée]|c[oó]mo|"
    r"pourquoi|comment|"
    r"warum|wieso)\b",
    re.IGNORECASE,
)


def detect_mood(text: str) -> Mood:
    """Classify a single user utterance.

    Order matters: distress wins over playful wins over curious; short
    utterances with no signal collapse to 'curt' so Samantha can mirror
    brevity instead of over-explaining.
    """
    t = (text or "").strip()
    if not t:
        return "calm"

    if _DISTRESS_RX.search(t):
        return "distressed"
    if _PLAYFUL_RX.search(t) or t.count("!") >= 2:
        return "playful"
    if _CURIOUS_RX.search(t) or t.endswith("?"):
        return "curious"

    # No emotional signal at all and very short → user is being terse.
    if len(t.split()) <= 3:
        return "curt"

    return "calm"


class EmpathyTracker:
    """Subscribes to user transcripts and tracks the current Mood.

    The current mood is the most common bucket across the last `_RING_SIZE`
    turns, with ties broken in favor of stronger signals (distressed >
    playful > curious > curt > calm). We only publish `empathy.changed`
    when the bucket actually flips, so the realtime session.update is rare.
    """

    _PRIORITY: dict[Mood, int] = {
        "distressed": 5,
        "playful": 4,
        "curious": 3,
        "curt": 2,
        "calm": 1,
    }

    def __init__(self) -> None:
        self._ring: deque[Mood] = deque(maxlen=_RING_SIZE)
        self.current: Mood = "calm"
        self._task: asyncio.Task | None = None
        self._running = False

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._ring.clear()
        self.current = "calm"
        q = bus.subscribe("realtime.user_text")

        async def pump() -> None:
            try:
                while self._running:
                    text = await q.get()
                    if not text:
                        continue
                    self.ingest(str(text))
            except asyncio.CancelledError:
                raise
            finally:
                bus.unsubscribe("realtime.user_text", q)

        self._task = asyncio.create_task(pump(), name="empathy-tracker")

    def ingest(self, text: str) -> Mood:
        """Process one user utterance. Publishes `empathy.changed` if the
        aggregated mood crosses to a different bucket. Returns the new
        aggregated mood (useful for tests)."""
        mood = detect_mood(text)
        self._ring.append(mood)
        new_current = self._aggregate()
        if new_current != self.current:
            log.info("empathy: mood %s -> %s", self.current, new_current)
            self.current = new_current
            bus.publish("empathy.changed", new_current)
        return self.current

    def _aggregate(self) -> Mood:
        if not self._ring:
            return "calm"
        counts: dict[Mood, int] = {}
        for m in self._ring:
            counts[m] = counts.get(m, 0) + 1
        # Sort by (count, priority) so a tie picks the stronger signal.
        ranked = sorted(counts.items(), key=lambda kv: (kv[1], self._PRIORITY[kv[0]]), reverse=True)
        return ranked[0][0]

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None
