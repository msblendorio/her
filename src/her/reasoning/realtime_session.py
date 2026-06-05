"""Thin async client around the OpenAI Realtime WebSocket API.

The class manages a single connection. From the outside:

* `send_audio(pcm16_bytes)` — push mic audio frames coming from the browser.
* `inject_scene(caption)` — push a textual scene description from the vision worker.
* `close()` — terminate the session cleanly.

It publishes incoming events on the event bus:

* `realtime.audio_out`  -> bytes (PCM16 mono 24 kHz) to play in the browser
* `realtime.user_text`  -> str  (transcript of what the user just said)
* `realtime.assistant_text` -> str (assistant transcript, streamed in deltas)
* `realtime.assistant_done` -> None (assistant finished a response)
* `realtime.status` -> dict (model state snapshots: thinking/speaking/listening)
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
from typing import Any

import websockets
from websockets.asyncio.client import ClientConnection

from ..agentic.executor import execute_tool_call
from ..agentic.tools import openai_specs
from ..config import settings
from ..core.event_bus import bus
from ..core.state import state
from ..core.usage import usage
from ..i18n import (
    pulse_prompt,
    resolve as resolve_lang,
    scene_prefix,
    scheduled_task_prefix,
    screen_prefix,
    upload_question_prefix,
)
from ..memory.character import CharacterProfile
from .instructions import build_instructions

log = logging.getLogger(__name__)

REALTIME_URL = "wss://api.openai.com/v1/realtime?model={model}"


class RealtimeSession:
    def __init__(
        self,
        language: str = "",
        extra_instructions: str = "",
        accessibility: bool = False,
        character_profile: CharacterProfile | None = None,
        empathy_mood: str = "calm",
        learned_skills: list[dict] | None = None,
    ) -> None:
        self._ws: ClientConnection | None = None
        self._recv_task: asyncio.Task | None = None
        self._closed = asyncio.Event()
        self._assistant_buffer: list[str] = []
        self._extra_instructions = extra_instructions
        self.language = resolve_lang(language or settings.assistant_language)
        # Accessibility mode toggles an addendum to the system instructions
        # without tearing down the session. Initial value comes from persisted
        # preferences (see PreferencesStore); can be flipped mid-session by
        # the toggle_accessibility_mode tool, which re-pushes session.update.
        self._accessibility = bool(accessibility)
        # Empathy modulation: a persistent profile of this user plus a live
        # mood bucket. The mood is updated mid-session via set_empathy(),
        # which re-pushes session.update so the model gets the new tone
        # directive without dropping the connection.
        self._character = character_profile
        self._empathy_mood = empathy_mood or "calm"
        # Snapshot of skills the user has taught, surfaced in the system
        # prompt so the model can invoke them. Updated by the orchestrator
        # at session start (and after each successful skill recording).
        self._learned_skills = list(learned_skills or [])
        # In-flight function calls. Keyed by call_id (set by the model). The
        # value is {"name": str, "args": str} accumulated across deltas.
        self._pending_calls: dict[str, dict[str, str]] = {}
        # The currently-active response id, or None when no response is in
        # progress. Used to avoid `conversation_already_has_active_response`
        # when a slow tool finishes after the user has already spoken again
        # and the model is mid-way through a new response.
        self._active_response_id: str | None = None

    async def connect(self) -> None:
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is not set")

        url = REALTIME_URL.format(model=settings.openai_realtime_model)
        # GA realtime: no "OpenAI-Beta" header; the API shape lives under
        # `audio.{input,output}` instead of flat `input_audio_*` keys, and
        # `modalities` was renamed to `output_modalities`.
        headers = [("Authorization", f"Bearer {settings.openai_api_key}")]
        log.info("connecting to OpenAI Realtime: %s", settings.openai_realtime_model)
        self._ws = await websockets.connect(url, additional_headers=headers, max_size=16 * 1024 * 1024)

        # Configure the session (GA shape).
        instructions = self._build_instructions()
        session_payload: dict[str, Any] = {
            "type": "realtime",
            "output_modalities": ["audio"],
            "instructions": instructions,
            "audio": {
                "input": {
                    "format": {"type": "audio/pcm", "rate": 24000},
                    "transcription": {"model": "whisper-1"},
                    "turn_detection": {
                        "type": "server_vad",
                        "threshold": 0.5,
                        "prefix_padding_ms": 300,
                        "silence_duration_ms": 600,
                        "create_response": True,
                        "interrupt_response": True,
                    },
                },
                "output": {
                    "format": {"type": "audio/pcm", "rate": 24000},
                    "voice": settings.openai_voice,
                    "speed": 1.0,
                },
            },
        }
        if settings.agentic_enabled:
            session_payload["tools"] = openai_specs()
            session_payload["tool_choice"] = "auto"
        await self._send_event({"type": "session.update", "session": session_payload})

        self._recv_task = asyncio.create_task(self._recv_loop(), name="realtime-recv")
        state.listening = True
        bus.publish("realtime.status", state.snapshot())

    async def _send_event(self, event: dict[str, Any]) -> None:
        assert self._ws is not None
        await self._ws.send(json.dumps(event))

    async def send_audio(self, pcm16: bytes) -> None:
        """Append a chunk of PCM16 mono 24 kHz audio to the input buffer."""
        if not self._ws:
            return
        await self._send_event({
            "type": "input_audio_buffer.append",
            "audio": base64.b64encode(pcm16).decode("ascii"),
        })

    async def send_text(self, text: str) -> None:
        """Inject a user text message and trigger a response.

        Runs in parallel with the audio input: typing while speaking is
        allowed. If a response is already in flight, it's cancelled first so
        the new turn takes precedence (mirrors the server-VAD interrupt
        behavior for voice).
        """
        text = (text or "").strip()
        if not self._ws or not text:
            return
        if self._active_response_id is not None:
            try:
                await self._send_event({"type": "response.cancel"})
            except Exception:
                pass
        await self._send_event({
            "type": "conversation.item.create",
            "item": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": text}],
            },
        })
        await self._send_event({"type": "response.create"})

    def _build_instructions(self) -> str:
        return build_instructions(
            language=self.language,
            extra_instructions=self._extra_instructions,
            accessibility=self._accessibility,
            character=self._character,
            empathy_mood=self._empathy_mood,
            learned_skills=self._learned_skills,
        )

    async def set_learned_skills(self, skills: list[dict]) -> None:
        """Refresh the in-prompt skill index and re-push instructions.

        Called by the orchestrator after a new skill is saved so the
        model can invoke it immediately without waiting for the next
        session.
        """
        new = list(skills or [])
        if new == self._learned_skills:
            return
        self._learned_skills = new
        if self._ws is None:
            return
        await self._send_event({
            "type": "session.update",
            "session": {"type": "realtime", "instructions": self._build_instructions()},
        })

    async def set_accessibility(self, on: bool) -> None:
        """Toggle the accessibility addendum and push it to the live session."""
        if self._accessibility == bool(on) or self._ws is None:
            self._accessibility = bool(on)
            return
        self._accessibility = bool(on)
        await self._send_event({
            "type": "session.update",
            "session": {"type": "realtime", "instructions": self._build_instructions()},
        })

    async def set_empathy(self, mood: str) -> None:
        """Update the live mood bucket and re-push instructions if changed.

        No-op when the mood is the same or when the session hasn't opened
        yet (the next connect() will pick up the new value via
        _build_instructions()).
        """
        mood = (mood or "calm").strip() or "calm"
        if mood == self._empathy_mood:
            return
        self._empathy_mood = mood
        if self._ws is None:
            return
        await self._send_event({
            "type": "session.update",
            "session": {"type": "realtime", "instructions": self._build_instructions()},
        })

    async def inject_screen_text(self, text: str) -> None:
        """Insert OCR'd screen text as an ambient context message.

        Mirrors `inject_scene` but uses the screen-specific prefix so the
        model knows the block is verbatim text rather than a description.
        """
        if not self._ws or not text.strip():
            return
        await self._send_event({
            "type": "conversation.item.create",
            "item": {
                "type": "message",
                "role": "system",
                "content": [
                    {
                        "type": "input_text",
                        "text": f"{screen_prefix(self.language)}\n{text}",
                    }
                ],
            },
        })

    async def inject_scene(self, caption: str) -> None:
        """Insert a textual scene description as a system context message.

        Uses conversation.item.create with role=system so the model treats it as
        ambient context rather than a user utterance. We do NOT trigger a
        response — server_vad will handle turn-taking when the user speaks.
        """
        if not self._ws or not caption.strip():
            return
        item = {
            "type": "conversation.item.create",
            "item": {
                "type": "message",
                "role": "system",
                "content": [
                    {
                        "type": "input_text",
                        "text": f"{scene_prefix(self.language)} {caption}",
                    }
                ],
            },
        }
        await self._send_event(item)

    async def pulse(self) -> None:
        """Ambient self-check tick: nudge the model to decide, on its own,
        whether to say something proactively.

        Skipped entirely when a response is already in flight (the user is
        being answered, or a previous tick is still talking) so the pulse can
        never interrupt a real exchange. Unlike inject_scene, this *does*
        trigger a response — but the prompt tells Samantha most ticks should
        end in silence.
        """
        if not self._ws or self._active_response_id is not None:
            return
        await self._send_event({
            "type": "conversation.item.create",
            "item": {
                "type": "message",
                "role": "system",
                "content": [
                    {"type": "input_text", "text": pulse_prompt(self.language)}
                ],
            },
        })
        await self._send_event({"type": "response.create"})

    async def run_scheduled_task(self, prompt: str) -> None:
        """Hand Samantha a stored scheduled instruction and have her act on it.

        Injected as a system message (not a fake user turn) prefixed so the
        model treats it as "the moment to do this has come". Cancels any
        in-flight response first so the scheduled task takes precedence,
        mirroring send_text().
        """
        prompt = (prompt or "").strip()
        if not self._ws or not prompt:
            return
        if self._active_response_id is not None:
            try:
                await self._send_event({"type": "response.cancel"})
            except Exception:
                pass
        await self._send_event({
            "type": "conversation.item.create",
            "item": {
                "type": "message",
                "role": "system",
                "content": [
                    {
                        "type": "input_text",
                        "text": f"{scheduled_task_prefix(self.language)}\n{prompt}",
                    }
                ],
            },
        })
        await self._send_event({"type": "response.create"})

    async def ask_about_upload(self, label: str) -> None:
        """Have Samantha ask whether a just-uploaded file should be kept in the
        wiki or treated as temporary. Injected as a system message + a response
        so she voices the question, mirroring run_scheduled_task.
        """
        label = (label or "").strip()
        if not self._ws or not label:
            return
        if self._active_response_id is not None:
            try:
                await self._send_event({"type": "response.cancel"})
            except Exception:
                pass
        await self._send_event({
            "type": "conversation.item.create",
            "item": {
                "type": "message",
                "role": "system",
                "content": [
                    {
                        "type": "input_text",
                        "text": f"{upload_question_prefix(self.language)} {label}",
                    }
                ],
            },
        })
        await self._send_event({"type": "response.create"})

    async def _recv_loop(self) -> None:
        assert self._ws is not None
        try:
            async for raw in self._ws:
                try:
                    evt = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                await self._handle_event(evt)
        except websockets.ConnectionClosed:
            log.info("realtime ws closed")
        except Exception:
            log.exception("realtime recv loop crashed")
        finally:
            self._closed.set()

    async def _handle_event(self, evt: dict[str, Any]) -> None:
        et = evt.get("type", "")

        # Audio out: stream PCM16 deltas back to the browser.
        if et == "response.output_audio.delta":
            audio_b64 = evt.get("delta", "")
            if audio_b64:
                bus.publish("realtime.audio_out", base64.b64decode(audio_b64))
            if not state.speaking:
                state.speaking = True
                state.thinking = False
                bus.publish("realtime.status", state.snapshot())

        elif et == "response.output_audio.done":
            state.speaking = False
            bus.publish("realtime.status", state.snapshot())

        # Assistant transcript deltas.
        elif et == "response.output_audio_transcript.delta":
            delta = evt.get("delta", "")
            self._assistant_buffer.append(delta)
            bus.publish("realtime.assistant_text", delta)

        elif et == "response.output_audio_transcript.done":
            full = "".join(self._assistant_buffer).strip()
            self._assistant_buffer.clear()
            bus.publish("realtime.assistant_done", full)

        # User transcript (Whisper). The dedicated completion event still exists
        # in GA; we also pick up the transcript from conversation.item.done
        # (role=user) as a fallback so we don't miss it.
        elif et == "conversation.item.input_audio_transcription.completed":
            text = evt.get("transcript", "")
            if text:
                bus.publish("realtime.user_text", text)

        elif et == "conversation.item.done":
            item = evt.get("item", {}) or {}
            if item.get("role") == "user":
                for part in item.get("content", []) or []:
                    if part.get("type") == "input_audio" and part.get("transcript"):
                        bus.publish("realtime.user_text", part["transcript"])
                        break

        # ── Function calling ──────────────────────────────────────────────
        # The model announces a function_call output item first; we capture
        # the call_id and name. Arguments stream in via deltas and finalize
        # with `response.function_call_arguments.done`.
        elif et == "response.output_item.added":
            item = evt.get("item", {}) or {}
            if item.get("type") == "function_call":
                call_id = item.get("call_id") or item.get("id") or ""
                self._pending_calls[call_id] = {
                    "name": item.get("name", ""),
                    "args": item.get("arguments", "") or "",
                }

        elif et == "response.function_call_arguments.delta":
            cid = evt.get("call_id") or evt.get("item_id") or ""
            slot = self._pending_calls.setdefault(cid, {"name": "", "args": ""})
            slot["args"] = slot["args"] + (evt.get("delta") or "")

        elif et == "response.function_call_arguments.done":
            cid = evt.get("call_id") or evt.get("item_id") or ""
            slot = self._pending_calls.pop(cid, {"name": "", "args": ""})
            name = slot["name"] or evt.get("name", "")
            args = evt.get("arguments") or slot["args"] or ""
            asyncio.create_task(self._handle_tool_call(cid, name, args))

        # Model started processing a turn.
        elif et == "response.created":
            resp = evt.get("response") or {}
            self._active_response_id = resp.get("id") or "active"
            state.thinking = True
            bus.publish("realtime.status", state.snapshot())

        elif et == "response.done":
            self._active_response_id = None
            usage.record((evt.get("response") or {}).get("usage"))
            state.thinking = False
            state.speaking = False
            bus.publish("realtime.status", state.snapshot())

        # User started/stopped speaking (server VAD).
        elif et == "input_audio_buffer.speech_started":
            state.listening = True
            bus.publish("realtime.status", state.snapshot())

        elif et == "error":
            err = evt.get("error") or {}
            # Benign race: a slow tool finished after the user spoke again and
            # a new response is already in flight. We deliberately suppress
            # the response.create in that case; if the server raced us, just
            # downgrade the log so it doesn't look like a real failure.
            if err.get("code") == "conversation_already_has_active_response":
                log.debug("realtime: %s (suppressed)", err.get("message"))
                return
            log.error("realtime error: %s", err)
            bus.publish("realtime.error", err)

    async def _handle_tool_call(self, call_id: str, name: str, raw_args: str) -> None:
        """Dispatch a model-issued function call, return its result, and ask
        the model to continue speaking about it.

        Only triggers a new response when no response is currently active —
        otherwise the function_call_output is simply added to the conversation
        and picked up by the next response (avoids 409 races when a slow tool
        finishes after the user has already spoken again).
        """
        result = await execute_tool_call(call_id, name, raw_args)
        if self._ws is None:
            return
        try:
            await self._send_event({
                "type": "conversation.item.create",
                "item": {
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": json.dumps(result, ensure_ascii=False),
                },
            })
            if self._active_response_id is None:
                await self._send_event({"type": "response.create"})
            else:
                log.debug(
                    "tool %s done while response %s is active — skipping response.create",
                    name, self._active_response_id,
                )
        except Exception:
            log.exception("failed to deliver tool result for call_id=%s", call_id)

    async def close(self) -> None:
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
        if self._recv_task is not None:
            self._recv_task.cancel()
        state.listening = False
        state.thinking = False
        state.speaking = False
        bus.publish("realtime.status", state.snapshot())
