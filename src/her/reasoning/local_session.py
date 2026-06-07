"""On-device, free voice session — a drop-in replacement for RealtimeSession.

Where :class:`RealtimeSession` streams audio to OpenAI's hosted speech-to-speech
model, this class assembles the same loop entirely on the machine:

    mic PCM16 ──▶ webrtcvad (turn detection) ──▶ faster-whisper (STT)
              ──▶ Ollama LLM (streaming + tool calls) ──▶ Kokoro (TTS) ──▶ PCM16

It exposes the *identical* public interface the orchestrator relies on
(``connect`` / ``send_audio`` / ``send_text`` / ``inject_scene`` /
``inject_screen_text`` / ``pulse`` / ``run_scheduled_task`` /
``ask_about_upload`` / ``set_accessibility`` / ``set_empathy`` /
``set_learned_skills`` / ``close``) and publishes the same event-bus topics
(``realtime.audio_out`` / ``realtime.user_text`` / ``realtime.assistant_text`` /
``realtime.assistant_done`` / ``realtime.status`` / ``realtime.error``), so the
web layer and the rest of the app cannot tell which backend is live.

The browser sends and expects PCM16 mono **24 kHz** — the same rate Kokoro emits
— so TTS output needs no resampling; only the VAD/STT path is downsampled to the
16 kHz those models want.

All heavy dependencies (faster-whisper, kokoro, webrtcvad) are imported lazily
so the default OpenAI build never needs them installed.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import httpx
import numpy as np

from ..agentic.executor import execute_tool_call
from ..agentic.tools import openai_specs
from ..config import settings
from ..core.event_bus import bus
from ..core.state import state
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

# 16 kHz, 20 ms frames for webrtcvad: 320 samples = 640 bytes (int16).
_VAD_RATE = 16000
_VAD_FRAME = 320
_PREROLL_MS = 320          # audio kept before speech onset, so we don't clip it
_MIN_SPEECH_MS = 250       # utterances shorter than this are treated as noise
_MAX_HISTORY = 30          # conversation turns kept in the local model's context
_MAX_TOOL_ROUNDS = 5       # safety cap on tool-call ping-pong per response
_AUDIO_CHUNK = 4800        # bytes per realtime.audio_out frame (~100 ms @ 24 kHz)

# espeak language tags derived from the assistant language. German has no
# Kokoro voice, so it falls back to English.
_LANG_CODE = {"it": "it", "en": "en-us", "es": "es", "fr": "fr-fr", "de": "en-us", "pt": "pt-br"}
# A sensible feminine default voice per espeak language tag.
_LANG_VOICE = {
    "en-us": "af_heart", "en-gb": "bf_emma", "it": "if_sara", "es": "ef_dora",
    "fr-fr": "ff_siwis", "pt-br": "pf_dora",
}
# Where to fetch the Kokoro ONNX model files when they're not on disk yet.
_KOKORO_URLS = {
    "model": "https://github.com/thewh1teagle/kokoro-onnx/releases/download/"
             "model-files-v1.0/kokoro-v1.0.onnx",
    "voices": "https://github.com/thewh1teagle/kokoro-onnx/releases/download/"
              "model-files-v1.0/voices-v1.0.bin",
}
# Strong boundaries always flush a chunk to TTS; soft ones flush only once the
# clause is long enough — so the first words start playing sooner on long
# replies without chopping short ones into unnatural fragments.
_STRONG_END = ".!?…\n"
_SOFT_END = ",;:"
_SOFT_MIN_CHARS = 40


class LocalRealtimeSession:
    def __init__(
        self,
        language: str = "",
        extra_instructions: str = "",
        accessibility: bool = False,
        character_profile: CharacterProfile | None = None,
        empathy_mood: str = "calm",
        learned_skills: list[dict] | None = None,
    ) -> None:
        self.language = resolve_lang(language or settings.assistant_language)
        self._extra_instructions = extra_instructions
        self._accessibility = bool(accessibility)
        self._character = character_profile
        self._empathy_mood = empathy_mood or "calm"
        self._learned_skills = list(learned_skills or [])

        self._history: list[dict] = []
        self._closed = False

        # Lazily-loaded engines (see _stt_model / _tts_engine / _vad).
        self._stt: Any = None
        self._tts: Any = None
        self._vad_engine: Any = None

        # VAD streaming state.
        self._vad_carry = np.empty(0, dtype=np.int16)   # leftover < one frame
        self._preroll = bytearray()                      # rolling pre-speech audio
        self._utt = bytearray()                          # current utterance @ 24 kHz
        self._in_speech = False
        self._silence_ms = 0.0
        self._speech_ms = 0.0

        # Turn / response lifecycle.
        self._turn_lock = asyncio.Lock()
        self._respond_task: asyncio.Task | None = None
        self._player_task: asyncio.Task | None = None
        self._speak_q: asyncio.Queue[str | None] | None = None

    # ── Lifecycle ─────────────────────────────────────────────────────────

    async def connect(self) -> None:
        """Preload the STT/TTS/VAD engines so the first turn isn't slow.

        Raises a clear RuntimeError (surfaced to the UI) when a local
        dependency is missing, mirroring the cowork client's behavior.
        """
        log.info(
            "starting LOCAL voice session (stt=%s, llm=%s, tts=%s/%s)",
            settings.local_stt_model, settings.local_llm_model,
            self._kokoro_lang(), self._kokoro_voice(),
        )
        # Fail fast with a clear message if the Ollama brain isn't reachable.
        await self._preflight_llm()
        # Touch each engine once, off the event loop.
        await asyncio.to_thread(self._stt_model)
        await asyncio.to_thread(self._tts_engine)
        self._vad()
        state.listening = True
        bus.publish("realtime.status", state.snapshot())

    async def _preflight_llm(self) -> None:
        """Verify the Ollama server is up and the configured model is pulled.

        Unreachable → RuntimeError (surfaced to the UI). Reachable but the model
        isn't pulled → a loud warning (the first turn would otherwise hang).
        """
        base = settings.local_llm_base_url.rstrip("/")
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.get(f"{base}/models")
                r.raise_for_status()
                ids = {m.get("id") for m in (r.json().get("data") or [])}
        except Exception as e:
            raise RuntimeError(
                f"local LLM not reachable at {base} — is Ollama running? "
                f"Start it and `ollama pull {settings.local_llm_model}` ({e})"
            ) from e
        if settings.local_llm_model not in ids:
            log.warning(
                "local LLM model %r not found on the server (have: %s) — "
                "run `ollama pull %s`",
                settings.local_llm_model, ", ".join(sorted(ids)) or "none",
                settings.local_llm_model,
            )

    async def close(self) -> None:
        self._closed = True
        for task in (self._respond_task, self._player_task):
            if task is not None and not task.done():
                task.cancel()
        state.listening = state.thinking = state.speaking = False
        bus.publish("realtime.status", state.snapshot())

    # ── Engine loaders (lazy, cached) ─────────────────────────────────────

    def _stt_model(self) -> Any:
        if self._stt is None:
            try:
                from faster_whisper import WhisperModel  # noqa: PLC0415
            except ImportError as e:
                raise RuntimeError(
                    "faster-whisper is not installed — run "
                    "`pip install -r requirements.txt` to use VOICE_BACKEND=local"
                ) from e
            self._stt = WhisperModel(
                settings.local_stt_model,
                device=settings.local_stt_device,
                compute_type=settings.local_stt_compute,
            )
        return self._stt

    def _tts_engine(self) -> Any:
        if self._tts is None:
            try:
                from kokoro_onnx import Kokoro  # noqa: PLC0415
            except ImportError as e:
                raise RuntimeError(
                    "kokoro-onnx is not installed — run "
                    "`pip install -r requirements.txt` to use VOICE_BACKEND=local"
                ) from e
            model_path, voices_path = self._ensure_tts_files()
            self._tts = Kokoro(model_path, voices_path)
        return self._tts

    @staticmethod
    def _ensure_tts_files() -> tuple[str, str]:
        """Return (model_path, voices_path), downloading them once if missing."""
        import urllib.request  # noqa: PLC0415
        from pathlib import Path  # noqa: PLC0415

        targets = {
            "model": Path(settings.local_tts_model_path),
            "voices": Path(settings.local_tts_voices_path),
        }
        for key, path in targets.items():
            if path.exists() and path.stat().st_size > 0:
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            log.info("kokoro: downloading %s → %s (one-time)", key, path)
            urllib.request.urlretrieve(_KOKORO_URLS[key], path)  # noqa: S310
        return str(targets["model"]), str(targets["voices"])

    def _vad(self) -> Any:
        if self._vad_engine is None:
            try:
                import webrtcvad  # noqa: PLC0415
            except ImportError as e:
                raise RuntimeError(
                    "webrtcvad is not installed — run "
                    "`pip install -r requirements.txt` to use VOICE_BACKEND=local"
                ) from e
            self._vad_engine = webrtcvad.Vad(int(settings.local_vad_aggressiveness))
        return self._vad_engine

    def _kokoro_lang(self) -> str:
        return (settings.local_tts_lang or "").strip() or _LANG_CODE.get(self.language, "en-us")

    def _kokoro_voice(self) -> str:
        # A non-default LOCAL_TTS_VOICE is used verbatim; otherwise pick the
        # feminine default that matches the language.
        configured = (settings.local_tts_voice or "").strip()
        if configured and configured != "af_heart":
            return configured
        return _LANG_VOICE.get(self._kokoro_lang(), "af_heart")

    # ── Audio in → turn detection ─────────────────────────────────────────

    async def send_audio(self, pcm16: bytes) -> None:
        """Feed a mic chunk (PCM16 mono 24 kHz) through the VAD turn detector."""
        if self._closed or not pcm16:
            return
        has_speech, dur_ms = self._chunk_has_speech(pcm16)

        # Keep a short rolling pre-roll so the start of a word isn't clipped.
        self._preroll.extend(pcm16)
        max_preroll = int(_PREROLL_MS / 1000 * 24000) * 2
        if len(self._preroll) > max_preroll:
            del self._preroll[:-max_preroll]

        if has_speech:
            if not self._in_speech:
                self._in_speech = True
                self._utt = bytearray(self._preroll)   # include the pre-roll
                self._speech_ms = 0.0
                # Barge-in: if Samantha is mid-utterance, stop her at once.
                if state.speaking and self._respond_task and not self._respond_task.done():
                    log.debug("local: barge-in, cancelling current response")
                    self._respond_task.cancel()
            self._utt.extend(pcm16)
            self._silence_ms = 0.0
            self._speech_ms += dur_ms
        elif self._in_speech:
            self._utt.extend(pcm16)
            self._silence_ms += dur_ms
            if self._silence_ms >= float(settings.local_vad_silence_ms):
                audio = bytes(self._utt)
                spoke = self._speech_ms
                self._reset_utterance()
                if spoke >= _MIN_SPEECH_MS:
                    asyncio.create_task(self._handle_turn(audio), name="local-turn")

    def _reset_utterance(self) -> None:
        self._utt = bytearray()
        self._in_speech = False
        self._silence_ms = 0.0
        self._speech_ms = 0.0

    def _chunk_has_speech(self, pcm24: bytes) -> tuple[bool, float]:
        """Return ``(contains_speech, duration_ms)`` for one 24 kHz chunk.

        The chunk is downsampled to 16 kHz and split into 20 ms frames (carrying
        any remainder to the next call); a chunk counts as speech when ≥30 % of
        its frames are voiced.
        """
        arr = np.frombuffer(pcm24, dtype=np.int16)
        dur_ms = len(arr) / 24000.0 * 1000.0
        x16 = self._to_16k(arr).astype(np.int16)
        buf = np.concatenate([self._vad_carry, x16])
        n_frames = len(buf) // _VAD_FRAME
        vad = self._vad()
        voiced = 0
        for i in range(n_frames):
            frame = buf[i * _VAD_FRAME:(i + 1) * _VAD_FRAME].tobytes()
            try:
                if vad.is_speech(frame, _VAD_RATE):
                    voiced += 1
            except Exception:
                pass
        self._vad_carry = buf[n_frames * _VAD_FRAME:]
        has = n_frames > 0 and voiced >= max(1, int(n_frames * 0.3))
        return has, dur_ms

    @staticmethod
    def _to_16k(arr_24k: np.ndarray) -> np.ndarray:
        """Linear-resample a 24 kHz signal to 16 kHz (ratio 2/3)."""
        n = len(arr_24k)
        n_out = int(n * 2 / 3)
        if n_out < 1:
            return np.empty(0, dtype=arr_24k.dtype)
        idx = np.linspace(0, n, n_out, endpoint=False)
        return np.interp(idx, np.arange(n), arr_24k)

    # ── Speech-to-text ────────────────────────────────────────────────────

    def _transcribe(self, audio24: bytes) -> str:
        arr = np.frombuffer(audio24, dtype=np.int16).astype(np.float32) / 32768.0
        x16 = self._to_16k(arr).astype(np.float32)
        model = self._stt_model()
        # Pin the language (configured, else the session's) — auto-detect
        # misfires badly on short utterances (calls them English ~0.39).
        segments, _ = model.transcribe(
            x16,
            language=settings.local_stt_language or self.language or None,
            beam_size=1,
            vad_filter=True,
        )
        return " ".join(seg.text for seg in segments).strip()

    # ── Turn handling ─────────────────────────────────────────────────────

    async def _handle_turn(self, audio24: bytes) -> None:
        if self._closed:
            return
        try:
            text = await asyncio.to_thread(self._transcribe, audio24)
        except Exception:
            log.exception("local: transcription failed")
            return
        text = (text or "").strip()
        if not text:
            state.listening = True
            bus.publish("realtime.status", state.snapshot())
            return
        bus.publish("realtime.user_text", text)
        self._history.append({"role": "user", "content": text})
        await self._dispatch_response()

    async def _dispatch_response(self) -> None:
        """Run one full LLM→TTS response under the turn lock."""
        async with self._turn_lock:
            if self._closed:
                return
            self._respond_task = asyncio.create_task(self._respond(), name="local-respond")
            try:
                await self._respond_task
            except asyncio.CancelledError:
                pass

    async def _respond(self) -> None:
        state.thinking, state.speaking = True, False
        bus.publish("realtime.status", state.snapshot())
        self._speak_q = asyncio.Queue()
        self._player_task = asyncio.create_task(self._player(), name="local-player")
        final_text = ""
        try:
            final_text = await self._llm_loop()
            await self._speak_q.put(None)          # flush sentinel
            await self._player_task                 # let playback finish
            if final_text:
                bus.publish("realtime.assistant_done", final_text)
        except asyncio.CancelledError:
            if self._player_task and not self._player_task.done():
                self._player_task.cancel()
            raise
        finally:
            if self._player_task and not self._player_task.done():
                self._player_task.cancel()
            self._trim_history()
            state.thinking = state.speaking = False
            state.listening = True
            bus.publish("realtime.status", state.snapshot())

    # ── LLM (Ollama, streaming, with tool calls) ──────────────────────────

    def _tool_specs(self) -> list[dict] | None:
        if not settings.agentic_enabled:
            return None
        specs = [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t.get("parameters", {}),
                },
            }
            for t in openai_specs()
        ]
        return specs or None

    async def _llm_loop(self) -> str:
        instructions = build_instructions(
            language=self.language,
            extra_instructions=self._extra_instructions,
            accessibility=self._accessibility,
            character=self._character,
            empathy_mood=self._empathy_mood,
            learned_skills=self._learned_skills,
        )
        messages: list[dict] = [{"role": "system", "content": instructions}, *self._history]
        tools = self._tool_specs()
        final_text = ""
        for _ in range(_MAX_TOOL_ROUNDS):
            content, tool_calls = await self._stream_chat(messages, tools)
            msg: dict[str, Any] = {"role": "assistant", "content": content or ""}
            if tool_calls:
                msg["tool_calls"] = tool_calls
            self._history.append(msg)
            messages.append(msg)
            if not tool_calls:
                final_text = content
                break
            # Execute each tool call and feed results back for the next round.
            for tc in tool_calls:
                fn = tc.get("function", {})
                name = fn.get("name", "")
                args = fn.get("arguments", "") or "{}"
                if isinstance(args, dict):
                    args = json.dumps(args)
                result = await execute_tool_call(tc.get("id", ""), name, args)
                tool_msg = {
                    "role": "tool",
                    "tool_call_id": tc.get("id", ""),
                    "content": json.dumps(result, ensure_ascii=False),
                }
                self._history.append(tool_msg)
                messages.append(tool_msg)
        return final_text

    async def _stream_chat(
        self, messages: list[dict], tools: list[dict] | None
    ) -> tuple[str, list[dict]]:
        """Stream one chat completion from Ollama.

        Publishes assistant-text deltas live and enqueues complete sentences for
        TTS as they form. Returns ``(full_text, tool_calls)`` once the stream
        closes; ``tool_calls`` is the accumulated OpenAI-format list (possibly
        empty).
        """
        url = f"{settings.local_llm_base_url.rstrip('/')}/chat/completions"
        payload: dict[str, Any] = {
            "model": settings.local_llm_model,
            "messages": messages,
            "stream": True,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        content_parts: list[str] = []
        sentence_buf = ""
        tool_acc: dict[int, dict] = {}
        # Generous read timeout between tokens, short connect — a hung server
        # surfaces as an error instead of deadlocking the turn lock forever.
        timeout = httpx.Timeout(120.0, connect=10.0)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream("POST", url, json=payload) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line or not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            obj = json.loads(data)
                        except json.JSONDecodeError:
                            continue
                        choices = obj.get("choices") or [{}]
                        delta = choices[0].get("delta", {}) or {}
                        piece = delta.get("content") or ""
                        if piece:
                            content_parts.append(piece)
                            bus.publish("realtime.assistant_text", piece)
                            sentence_buf += piece
                            sentence_buf = self._flush_sentences(sentence_buf)
                        for tcd in delta.get("tool_calls") or []:
                            self._accumulate_tool_call(tool_acc, tcd)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.exception("local: LLM stream failed")
            bus.publish("realtime.error", {"message": f"local LLM error: {e}"})
        # Speak whatever sentence fragment is left over.
        tail = sentence_buf.strip()
        if tail and self._speak_q is not None:
            self._speak_q.put_nowait(tail)
        tool_calls = [tool_acc[k] for k in sorted(tool_acc)]
        return "".join(content_parts).strip(), tool_calls

    def _flush_sentences(self, buf: str) -> str:
        """Enqueue speakable chunks from ``buf`` for TTS; return the unflushed tail."""
        if self._speak_q is None:
            return buf
        seg_start, i, n = 0, 0, len(buf)
        while i < n:
            ch = buf[i]
            strong = ch in _STRONG_END
            soft = ch in _SOFT_END and (i - seg_start) >= _SOFT_MIN_CHARS
            if strong or soft:
                chunk = buf[seg_start:i + 1].strip()
                if chunk:
                    self._speak_q.put_nowait(chunk)
                seg_start = i + 1
            i += 1
        return buf[seg_start:]

    @staticmethod
    def _accumulate_tool_call(acc: dict[int, dict], delta: dict) -> None:
        idx = delta.get("index", 0)
        slot = acc.setdefault(idx, {"id": "", "type": "function",
                                    "function": {"name": "", "arguments": ""}})
        if delta.get("id"):
            slot["id"] = delta["id"]
        fn = delta.get("function") or {}
        if fn.get("name"):
            slot["function"]["name"] = fn["name"]
        if fn.get("arguments"):
            slot["function"]["arguments"] += fn["arguments"]

    # ── Text-to-speech playback ───────────────────────────────────────────

    async def _player(self) -> None:
        """Consume sentences and stream their synthesized audio to the browser."""
        assert self._speak_q is not None
        try:
            while True:
                sentence = await self._speak_q.get()
                if sentence is None:
                    break
                if self._closed:
                    continue
                try:
                    pcm = await asyncio.to_thread(self._synthesize, sentence)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    log.exception("local: TTS synthesis failed")
                    continue
                if not pcm:
                    continue
                if not state.speaking:
                    state.speaking, state.thinking = True, False
                    bus.publish("realtime.status", state.snapshot())
                for off in range(0, len(pcm), _AUDIO_CHUNK):
                    bus.publish("realtime.audio_out", pcm[off:off + _AUDIO_CHUNK])
        except asyncio.CancelledError:
            raise

    def _synthesize(self, text: str) -> bytes:
        engine = self._tts_engine()
        samples, _ = engine.create(
            text,
            voice=self._kokoro_voice(),
            speed=float(settings.local_tts_speed),
            lang=self._kokoro_lang(),
        )
        wav = np.clip(np.asarray(samples, dtype=np.float32), -1.0, 1.0)
        return (wav * 32767.0).astype("<i2").tobytes()

    # ── Text / context injection (mirror RealtimeSession) ─────────────────

    async def send_text(self, text: str) -> None:
        text = (text or "").strip()
        if not text or self._closed:
            return
        self._cancel_current()
        self._history.append({"role": "user", "content": text})
        asyncio.create_task(self._dispatch_response(), name="local-text-turn")

    async def inject_scene(self, caption: str) -> None:
        if self._closed or not caption.strip():
            return
        self._history.append(
            {"role": "system", "content": f"{scene_prefix(self.language)} {caption}"}
        )

    async def inject_screen_text(self, text: str) -> None:
        if self._closed or not text.strip():
            return
        self._history.append(
            {"role": "system", "content": f"{screen_prefix(self.language)}\n{text}"}
        )

    async def pulse(self) -> None:
        if self._closed or state.thinking or state.speaking:
            return
        self._history.append({"role": "system", "content": pulse_prompt(self.language)})
        asyncio.create_task(self._dispatch_response(), name="local-pulse")

    async def run_scheduled_task(self, prompt: str) -> None:
        prompt = (prompt or "").strip()
        if self._closed or not prompt:
            return
        self._cancel_current()
        self._history.append(
            {"role": "system",
             "content": f"{scheduled_task_prefix(self.language)}\n{prompt}"}
        )
        asyncio.create_task(self._dispatch_response(), name="local-scheduled")

    async def ask_about_upload(self, label: str) -> None:
        label = (label or "").strip()
        if self._closed or not label:
            return
        self._cancel_current()
        self._history.append(
            {"role": "system",
             "content": f"{upload_question_prefix(self.language)} {label}"}
        )
        asyncio.create_task(self._dispatch_response(), name="local-upload-ask")

    def _cancel_current(self) -> None:
        if self._respond_task and not self._respond_task.done():
            self._respond_task.cancel()

    # ── Live system-prompt knobs (rebuilt on the next turn) ───────────────

    async def set_learned_skills(self, skills: list[dict]) -> None:
        self._learned_skills = list(skills or [])

    async def set_accessibility(self, on: bool) -> None:
        self._accessibility = bool(on)

    async def set_empathy(self, mood: str) -> None:
        self._empathy_mood = (mood or "calm").strip() or "calm"

    # ── Internals ─────────────────────────────────────────────────────────

    def _trim_history(self) -> None:
        """Bound the local model's context to the most recent turns.

        Trims from the front but never cuts in the middle of a tool exchange
        (an assistant message carrying tool_calls must keep its tool replies),
        so we drop whole leading user/assistant/tool groups.
        """
        if len(self._history) <= _MAX_HISTORY:
            return
        drop = len(self._history) - _MAX_HISTORY
        # Advance past any tool messages so we don't orphan a tool reply.
        while drop < len(self._history) and self._history[drop].get("role") == "tool":
            drop += 1
        self._history = self._history[drop:]
