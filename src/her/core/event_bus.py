"""Minimal async pub/sub used to wire perception, reasoning and the UI.

Topics are plain strings. Subscribers get an asyncio.Queue they can `await` on.
The bus drops messages for slow consumers rather than blocking publishers.
"""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any

log = logging.getLogger(__name__)


class EventBus:
    def __init__(self, queue_maxsize: int = 256) -> None:
        self._subs: dict[str, list[asyncio.Queue]] = defaultdict(list)
        self._maxsize = queue_maxsize

    def subscribe(self, topic: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=self._maxsize)
        self._subs[topic].append(q)
        return q

    def unsubscribe(self, topic: str, q: asyncio.Queue) -> None:
        if q in self._subs.get(topic, []):
            self._subs[topic].remove(q)

    def publish(self, topic: str, payload: Any) -> None:
        for q in self._subs.get(topic, []):
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                log.debug("dropping %s message: subscriber queue full", topic)


bus = EventBus()
