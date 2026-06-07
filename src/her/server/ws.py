"""WebSocket bridges between the browser and the orchestrator.

Three endpoints:

* `/ws/audio`  — binary frames in: PCM16 mic chunks. Binary frames out: PCM16
                 audio coming back from OpenAI Realtime.
* `/ws/vision` — binary frames in only: JPEG webcam frames.
* `/ws/events` — JSON out: transcripts, status updates, captions. JSON in: none.
"""
from __future__ import annotations

import asyncio
import json
import logging

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from ..core.event_bus import bus
from ..core.orchestrator import orchestrator
from ..core.state import state
from ..perception.vision_capture import frame_buffer

log = logging.getLogger(__name__)


async def _audio_out_pump(ws: WebSocket) -> None:
    """Forward audio deltas from the bus to the browser."""
    q = bus.subscribe("realtime.audio_out")
    try:
        while True:
            chunk = await q.get()
            await ws.send_bytes(chunk)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        bus.unsubscribe("realtime.audio_out", q)


def register_ws_routes(app: FastAPI) -> None:
    @app.websocket("/ws/audio")
    async def ws_audio(ws: WebSocket) -> None:
        await ws.accept()
        pump = asyncio.create_task(_audio_out_pump(ws), name="audio-out-pump")
        try:
            while True:
                msg = await ws.receive()
                if "bytes" in msg and msg["bytes"] is not None:
                    await orchestrator.push_mic_audio(msg["bytes"])
                elif msg.get("type") == "websocket.disconnect":
                    break
        except WebSocketDisconnect:
            pass
        except Exception:
            log.exception("ws_audio crashed")
        finally:
            pump.cancel()

    @app.websocket("/ws/vision")
    async def ws_vision(ws: WebSocket) -> None:
        await ws.accept()
        try:
            while True:
                msg = await ws.receive()
                if "bytes" in msg and msg["bytes"] is not None:
                    await frame_buffer.put_jpeg(msg["bytes"])
                elif msg.get("type") == "websocket.disconnect":
                    break
        except WebSocketDisconnect:
            pass
        except Exception:
            log.exception("ws_vision crashed")

    @app.websocket("/ws/events")
    async def ws_events(ws: WebSocket) -> None:
        await ws.accept()
        await ws.send_text(json.dumps({"type": "status", "data": state.snapshot()}))

        q_user = bus.subscribe("realtime.user_text")
        q_asst = bus.subscribe("realtime.assistant_text")
        q_done = bus.subscribe("realtime.assistant_done")
        q_caption = bus.subscribe("vision.caption")
        q_status = bus.subscribe("realtime.status")
        q_error = bus.subscribe("realtime.error")
        q_mem_loaded = bus.subscribe("memory.loaded")
        q_mem_saved = bus.subscribe("memory.saved")
        q_tool = bus.subscribe("agentic.tool_call")
        q_sched = bus.subscribe("schedule.fired")
        q_ast = bus.subscribe("ast.status")

        async def relay(queue: asyncio.Queue, kind: str) -> None:
            try:
                while True:
                    payload = await queue.get()
                    await ws.send_text(json.dumps({"type": kind, "data": payload}))
            except (WebSocketDisconnect, RuntimeError):
                pass

        tasks = [
            asyncio.create_task(relay(q_user, "user_text")),
            asyncio.create_task(relay(q_asst, "assistant_text")),
            asyncio.create_task(relay(q_done, "assistant_done")),
            asyncio.create_task(relay(q_caption, "caption")),
            asyncio.create_task(relay(q_status, "status")),
            asyncio.create_task(relay(q_error, "error")),
            asyncio.create_task(relay(q_mem_loaded, "memory_loaded")),
            asyncio.create_task(relay(q_mem_saved, "memory_saved")),
            asyncio.create_task(relay(q_tool, "tool_call")),
            asyncio.create_task(relay(q_sched, "schedule_fired")),
            asyncio.create_task(relay(q_ast, "ast_status")),
        ]
        try:
            # Keep the connection open until the client disconnects.
            while True:
                msg = await ws.receive()
                if msg.get("type") == "websocket.disconnect":
                    break
        except WebSocketDisconnect:
            pass
        except Exception:
            log.exception("ws_events crashed")
        finally:
            for t in tasks:
                t.cancel()
            for q, topic in [
                (q_user, "realtime.user_text"),
                (q_asst, "realtime.assistant_text"),
                (q_done, "realtime.assistant_done"),
                (q_caption, "vision.caption"),
                (q_status, "realtime.status"),
                (q_error, "realtime.error"),
                (q_mem_loaded, "memory.loaded"),
                (q_mem_saved, "memory.saved"),
                (q_tool, "agentic.tool_call"),
                (q_sched, "schedule.fired"),
                (q_ast, "ast.status"),
            ]:
                bus.unsubscribe(topic, q)
