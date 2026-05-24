"""Listens on the event bus and accumulates the live transcript of a session.

The collected transcript is consumed by the summarizer at session-end and
then discarded — full transcripts are never persisted (only the summary is).
"""
from __future__ import annotations

import asyncio
import logging

from ..core.event_bus import bus

log = logging.getLogger(__name__)


class TranscriptCollector:
    def __init__(self) -> None:
        # Each entry is ("user"|"assistant", text)
        self.turns: list[tuple[str, str]] = []
        self._tasks: list[asyncio.Task] = []
        self._running = False

    async def start(self) -> None:
        if self._running:
            return
        self.turns.clear()
        self._running = True

        q_user = bus.subscribe("realtime.user_text")
        q_asst = bus.subscribe("realtime.assistant_done")

        async def pump_user() -> None:
            try:
                while self._running:
                    t = await q_user.get()
                    if t:
                        self.turns.append(("user", t.strip()))
            except asyncio.CancelledError:
                raise
            finally:
                bus.unsubscribe("realtime.user_text", q_user)

        async def pump_asst() -> None:
            try:
                while self._running:
                    t = await q_asst.get()
                    if t:
                        self.turns.append(("assistant", t.strip()))
            except asyncio.CancelledError:
                raise
            finally:
                bus.unsubscribe("realtime.assistant_done", q_asst)

        self._tasks = [
            asyncio.create_task(pump_user(), name="memory-collect-user"),
            asyncio.create_task(pump_asst(), name="memory-collect-asst"),
        ]

    async def stop(self) -> list[tuple[str, str]]:
        self._running = False
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
        self._tasks.clear()
        return list(self.turns)
