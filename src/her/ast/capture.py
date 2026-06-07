"""Phase 0 — opt-in capture of raw turns to ``data/conversations/<session>.jsonl``.

Mirrors ``memory.collector.TranscriptCollector`` (it listens on the same bus
topics) but, instead of buffering in memory for a one-shot summary, it writes
each turn to disk *incrementally* and *redacted*, with the metadata the slow
loop needs later (timestamp, turn index, language, live mood, tool calls).

Capture only runs when the user has opted in (``preferences.ast_capture``).
Nothing is ever written without that opt-in — see ``manager.AstManager``.
"""
from __future__ import annotations

import asyncio
import logging

from ..core.event_bus import bus
from .redact import redact
from .store import AstStore, now_iso

log = logging.getLogger(__name__)


class AstCapture:
    def __init__(self, store: AstStore) -> None:
        self.store = store
        self._tasks: list[asyncio.Task] = []
        self._running = False
        self._session_id = ""
        self._lang = ""
        self._turn = 0
        self._mood = "calm"
        # Tool calls observed since the last assistant turn, attached to the
        # next assistant record so the slow loop sees agentic traces.
        self._pending_tools: list[dict] = []

    async def start(self, session_id: str, language: str) -> None:
        if self._running:
            return
        self._session_id = session_id
        self._lang = language
        self._turn = 0
        self._mood = "calm"
        self._pending_tools = []
        self._running = True

        q_user = bus.subscribe("realtime.user_text")
        q_asst = bus.subscribe("realtime.assistant_done")
        q_mood = bus.subscribe("empathy.changed")
        q_tool = bus.subscribe("agentic.tool_call")

        async def pump_user() -> None:
            try:
                while self._running:
                    t = await q_user.get()
                    if t:
                        self._write("user", t)
            except asyncio.CancelledError:
                raise
            finally:
                bus.unsubscribe("realtime.user_text", q_user)

        async def pump_asst() -> None:
            try:
                while self._running:
                    t = await q_asst.get()
                    if t:
                        tools = self._pending_tools
                        self._pending_tools = []
                        self._write("assistant", t, tool_calls=tools)
            except asyncio.CancelledError:
                raise
            finally:
                bus.unsubscribe("realtime.assistant_done", q_asst)

        async def pump_mood() -> None:
            try:
                while self._running:
                    m = await q_mood.get()
                    if isinstance(m, str) and m:
                        self._mood = m
            except asyncio.CancelledError:
                raise
            finally:
                bus.unsubscribe("empathy.changed", q_mood)

        async def pump_tools() -> None:
            try:
                while self._running:
                    payload = await q_tool.get()
                    if isinstance(payload, dict):
                        self._pending_tools.append({
                            "name": str(payload.get("name") or payload.get("tool") or "?"),
                            "ok": bool(payload.get("ok", True)),
                        })
            except asyncio.CancelledError:
                raise
            finally:
                bus.unsubscribe("agentic.tool_call", q_tool)

        self._tasks = [
            asyncio.create_task(pump_user(), name="ast-capture-user"),
            asyncio.create_task(pump_asst(), name="ast-capture-asst"),
            asyncio.create_task(pump_mood(), name="ast-capture-mood"),
            asyncio.create_task(pump_tools(), name="ast-capture-tools"),
        ]
        log.info("ast: capture started (session=%s)", session_id)

    def _write(self, role: str, text: str, tool_calls: list[dict] | None = None) -> None:
        self._turn += 1
        record = {
            "session_id": self._session_id,
            "ts": now_iso(),
            "turn": self._turn,
            "role": role,
            "text": redact(text.strip()),
            "lang": self._lang,
            "mood": self._mood,
            "tool_calls": tool_calls or [],
            # Implicit feedback (interruptions / corrections) is a forward-looking
            # signal — captured as a stable shape now, populated in a later phase.
            "feedback": {"interrupted": False, "corrected_prev": False},
        }
        try:
            self.store.append_turn(self._session_id, record)
            bus.publish("ast.capture", {"turn": self._turn, "role": role})
        except Exception:
            log.exception("ast: failed to persist turn")

    async def stop(self) -> int:
        """Stop capturing and return the number of turns written this session."""
        self._running = False
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
        self._tasks.clear()
        log.info("ast: capture stopped (session=%s, turns=%d)", self._session_id, self._turn)
        return self._turn
