"""Owns the running session: spins up the Realtime client and the vision worker,
wires them together, and provides start/stop entrypoints used by the web layer.

A session is single-tenant: the app assumes one user, one browser tab. Calling
`start()` while a session is active is a no-op.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import datetime
from time import monotonic

from ..agentic.screen import read_screen
from ..agentic.skills.runtime import store as skill_store
from ..config import settings
from ..i18n import resolve as resolve_lang, wiki_overview_block
from ..memory.wiki.store import store as wiki_store
from ..perception.location import detect_location
from ..memory.character import CharacterProfile, CharacterStore, refine_character
from ..memory.collector import TranscriptCollector
from ..memory.recall import build_recall_block
from ..memory.store import MemoryStore
from ..memory.summarizer import summarize, summarize_visual
from ..memory.visual_collector import VisualCollector
from ..perception.vision_scene import run_vision_loop
from ..perception.world_model import build_world_model
from ..reasoning.empathy import EmpathyTracker
from ..reasoning.local_session import LocalRealtimeSession
from ..reasoning.realtime_session import RealtimeSession
from .event_bus import bus
from .preferences import PreferencesStore
from .scheduler import ScheduleStore, minute_marker
from .state import state
from .usage import usage

log = logging.getLogger(__name__)

# Either voice backend satisfies the same interface; the orchestrator treats
# them interchangeably (selected by settings.voice_backend).
VoiceSession = RealtimeSession | LocalRealtimeSession


class Orchestrator:
    def __init__(self) -> None:
        self.realtime: VoiceSession | None = None
        self._vision_task: asyncio.Task | None = None
        self._screen_task: asyncio.Task | None = None
        self._skills_task: asyncio.Task | None = None
        # Time-based autonomy: cron-driven scheduled tasks + ambient pulse.
        # Both loops live only while a session is active. The job store is
        # read live on every poll, so add/remove take effect without restart.
        self.schedule_store = ScheduleStore(settings.schedule_path)
        self._schedule_task: asyncio.Task | None = None
        self._pulse_task: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        # The world model is built once and kept around; the app does not yet
        # consume its outputs, but the hook is here for when V-JEPA is wired in.
        self.world_model = build_world_model()

        self.memory_store: MemoryStore | None = None
        self.collector: TranscriptCollector | None = None
        self.visual_collector: VisualCollector | None = None
        if settings.memory_enabled:
            self.memory_store = MemoryStore(settings.memory_path)

        # Persisted preferences (accessibility mode, future knobs) — loaded
        # once and re-saved every time set_accessibility() is called.
        self.prefs_store = PreferencesStore(settings.preferences_path)
        self._prefs = self.prefs_store.load()

        # Persistent character profile (slow signal) + live empathy tracker
        # (fast signal). The store is created unconditionally so that the
        # very first session — when no profile exists yet — still writes
        # one out at the end.
        self.character_store: CharacterStore | None = None
        self._character: CharacterProfile | None = None
        self.empathy: EmpathyTracker | None = None
        self._empathy_task: asyncio.Task | None = None
        if settings.empathy_enabled:
            self.character_store = CharacterStore(settings.character_path)

        # Language is captured at start() time so summarize() at stop() still
        # has it even if the user changes the dropdown mid-session.
        self._session_language: str = resolve_lang(settings.assistant_language)

    async def start(self, language: str = "") -> None:
        async with self._lock:
            if state.active:
                log.info("session already active, ignoring start()")
                return
            self._session_language = resolve_lang(language or settings.assistant_language)
            local_voice = settings.voice_backend.strip().lower() == "local"
            log.info(
                "starting session (lang=%s, voice=%s)",
                self._session_language, "local" if local_voice else "openai",
            )
            # Local voice is free, so the status bar shows the local model name
            # and the cost stays at $0 (LocalRealtimeSession never records usage).
            usage.reset(
                model=f"local:{settings.local_llm_model}" if local_voice
                else settings.openai_realtime_model
            )

            # Build the optional recall block from previous sessions.
            extra = ""
            if self.memory_store is not None:
                recent = self.memory_store.recent(settings.memory_recall_count)
                extra = build_recall_block(recent, language=self._session_language)
                if recent:
                    log.info("memory: recalling %d previous sessions", len(recent))
                    bus.publish("memory.loaded", {"count": len(recent)})

            # Append a tiny overview of the knowledge-base wiki so Samantha
            # knows it exists and which topics it covers (she can wiki_query it).
            if settings.wiki_enabled:
                try:
                    wiki_pages = await asyncio.to_thread(wiki_store.list_pages)
                    overview = wiki_overview_block(wiki_pages, self._session_language)
                    if overview:
                        extra = f"{extra}\n\n{overview}" if extra else overview
                except Exception:
                    log.exception("wiki: could not build recall overview")

            # Start the session pre-configured with the user's persisted
            # accessibility preference, so a visually impaired user does not
            # have to reactivate the mode every time they hit Start.
            start_with_a11y = bool(self._prefs.accessibility)

            # Load the character profile (if any) — passed into the realtime
            # session so the empathy addendum is part of the initial system
            # prompt rather than pushed afterwards.
            self._character = self.character_store.load() if self.character_store else None

            # Resolve location in a worker thread before connect(), so
            # the (sync) lookup inside the system-prompt builder finds a
            # hot cache and doesn't block the event loop. Tries Apple
            # Core Location first (accurate, may trigger a one-time TCC
            # permission prompt), falls back to IP geolocation. Cached
            # process-wide after the first call.
            await asyncio.to_thread(detect_location)

            # Snapshot of user-taught skills, surfaced in the system
            # prompt so Samantha can call them by name.
            try:
                learned_skills = await asyncio.to_thread(skill_store.list_skills)
            except Exception:
                log.exception("skills: could not load index, starting empty")
                learned_skills = []

            session_cls = LocalRealtimeSession if local_voice else RealtimeSession
            self.realtime = session_cls(
                language=self._session_language,
                extra_instructions=extra,
                accessibility=start_with_a11y,
                character_profile=self._character,
                empathy_mood="calm",
                learned_skills=learned_skills,
            )
            await self.realtime.connect()

            # Live empathy tracker: subscribes to user transcripts on its
            # own; we just need to forward mood changes to the realtime
            # session so it re-pushes session.update.
            if settings.empathy_enabled:
                self.empathy = EmpathyTracker()
                await self.empathy.start()
                self._empathy_task = asyncio.create_task(
                    self._forward_empathy_changes(), name="empathy-forward"
                )

            # Refresh the in-prompt skill index whenever a new skill is
            # taught mid-session.
            self._skills_task = asyncio.create_task(
                self._forward_skill_updates(), name="skills-forward"
            )

            # Begin collecting the new transcript for end-of-session summary.
            if self.memory_store is not None:
                self.collector = TranscriptCollector()
                await self.collector.start()

                # Visual track: only meaningful if both memory and vision are
                # on, and the user hasn't explicitly disabled it.
                if settings.vision_enabled and settings.visual_memory_enabled:
                    self.visual_collector = VisualCollector()
                    await self.visual_collector.start()

            self._vision_task = asyncio.create_task(
                run_vision_loop(self._on_caption), name="vision-loop"
            )

            # Time-based autonomy loops (active-session only).
            if settings.schedule_enabled:
                self._schedule_task = asyncio.create_task(
                    self._run_schedule_loop(), name="schedule-loop"
                )
            if self._prefs.pulse_enabled:
                self._pulse_task = asyncio.create_task(
                    self._run_pulse_loop(), name="pulse-loop"
                )

            state.active = True
            state.accessibility = start_with_a11y
            state.started_at = monotonic()
            bus.publish("realtime.status", state.snapshot())

            if start_with_a11y:
                log.info("accessibility: restoring persisted mode (on)")
                self._screen_task = asyncio.create_task(
                    self._run_screen_loop(), name="accessibility-screen-loop"
                )

    async def stop(self) -> None:
        async with self._lock:
            if not state.active:
                return
            log.info("stopping session")
            duration = monotonic() - state.started_at if state.started_at else 0.0

            if self._vision_task is not None:
                self._vision_task.cancel()
                try:
                    await self._vision_task
                except (asyncio.CancelledError, Exception):
                    pass
                self._vision_task = None

            if self._screen_task is not None:
                self._screen_task.cancel()
                try:
                    await self._screen_task
                except (asyncio.CancelledError, Exception):
                    pass
                self._screen_task = None
            state.accessibility = False

            if self._skills_task is not None:
                self._skills_task.cancel()
                try:
                    await self._skills_task
                except (asyncio.CancelledError, Exception):
                    pass
                self._skills_task = None

            for attr in ("_schedule_task", "_pulse_task"):
                task = getattr(self, attr)
                if task is not None:
                    task.cancel()
                    try:
                        await task
                    except (asyncio.CancelledError, Exception):
                        pass
                    setattr(self, attr, None)

            # Tear down the empathy tracker before the collector so it
            # releases its subscription to realtime.user_text first.
            if self._empathy_task is not None:
                self._empathy_task.cancel()
                try:
                    await self._empathy_task
                except (asyncio.CancelledError, Exception):
                    pass
                self._empathy_task = None
            if self.empathy is not None:
                await self.empathy.stop()
                self.empathy = None

            # Drain the transcript collector and (best-effort) summarize.
            turns: list[tuple[str, str]] = []
            if self.collector is not None:
                turns = await self.collector.stop()
                self.collector = None

            # Drain the visual collector too, before tearing down the rest —
            # captions stop arriving once the vision task is cancelled above.
            captions: list[tuple[float, str]] = []
            if self.visual_collector is not None:
                captions = await self.visual_collector.stop()
                self.visual_collector = None

            if self.realtime is not None:
                await self.realtime.close()
                self.realtime = None

            state.active = False
            state.started_at = 0.0
            bus.publish("realtime.status", state.snapshot())

            # Summarization is fire-and-forget — runs after we've already
            # returned a snappy stop() to the UI.
            if self.memory_store is not None and turns:
                asyncio.create_task(
                    self._summarize_and_save(
                        turns, captions, duration, self._session_language
                    ),
                    name="memory-summarize",
                )

            # Character profile refinement is also fire-and-forget. It
            # reads the *just-collected* turns (and recent memory entries
            # for facts context) and writes the updated profile to disk.
            if self.character_store is not None and turns:
                asyncio.create_task(
                    self._refine_and_save_character(turns),
                    name="character-refine",
                )

    async def _summarize_and_save(
        self,
        turns: list[tuple[str, str]],
        captions: list[tuple[float, str]],
        duration: float,
        language: str,
    ) -> None:
        """Run the text and visual summarizers in parallel and persist the
        merged MemoryEntry. The visual track is optional: if there were too
        few captions (or the API failed), the entry is still saved with
        empty visual fields.
        """
        try:
            text_task = asyncio.create_task(
                summarize(turns, duration, language=language),
                name="memory-summarize-text",
            )
            visual_task = asyncio.create_task(
                summarize_visual(captions, language=language),
                name="memory-summarize-visual",
            )
            entry, (visual_summary, visual_facts) = await asyncio.gather(
                text_task, visual_task
            )
            if entry is None:
                return
            entry.visual_summary = visual_summary
            entry.visual_facts = visual_facts
            assert self.memory_store is not None
            self.memory_store.append(entry)
            bus.publish("memory.saved", {
                "summary": entry.summary,
                "key_facts": entry.key_facts,
                "visual_summary": entry.visual_summary,
                "visual_facts": entry.visual_facts,
            })
        except Exception:
            log.exception("memory: summarize_and_save failed")

    async def _forward_empathy_changes(self) -> None:
        """Bridge the empathy.changed bus topic to the realtime session.

        The tracker publishes infrequently (only when the aggregated mood
        flips bucket), so this is essentially idle most of the time.
        """
        q = bus.subscribe("empathy.changed")
        try:
            while True:
                mood = await q.get()
                if self.realtime is not None and isinstance(mood, str):
                    try:
                        await self.realtime.set_empathy(mood)
                    except Exception:
                        log.exception("empathy: set_empathy failed for mood=%s", mood)
        except asyncio.CancelledError:
            raise
        finally:
            bus.unsubscribe("empathy.changed", q)

    async def _forward_skill_updates(self) -> None:
        """When a new skill is saved mid-session, re-push the system
        prompt so Samantha sees the updated skill index right away.
        """
        q = bus.subscribe("skills.saved")
        try:
            while True:
                await q.get()
                if self.realtime is None:
                    continue
                try:
                    skills = await asyncio.to_thread(skill_store.list_skills)
                    await self.realtime.set_learned_skills(skills)
                except Exception:
                    log.exception("skills: failed to refresh prompt index")
        except asyncio.CancelledError:
            raise
        finally:
            bus.unsubscribe("skills.saved", q)

    async def _refine_and_save_character(self, turns: list[tuple[str, str]]) -> None:
        if self.character_store is None:
            return
        previous = self._character or self.character_store.load()
        recent = self.memory_store.recent(3) if self.memory_store is not None else []
        try:
            new_profile = await refine_character(previous, turns, recent_entries=recent)
        except Exception:
            log.exception("character: refine failed")
            return
        if new_profile is None:
            return
        try:
            self.character_store.save(new_profile)
            self._character = new_profile
            log.info(
                "character: profile updated (style=%s, tone=%s, baseline=%d, sessions=%d)",
                new_profile.communication_style,
                new_profile.emotional_tone,
                new_profile.empathy_baseline,
                new_profile.sessions_observed,
            )
            bus.publish("character.saved", new_profile.to_dict())
        except Exception:
            log.exception("character: save failed")

    async def push_mic_audio(self, pcm16: bytes) -> None:
        if self.realtime is not None:
            await self.realtime.send_audio(pcm16)

    async def push_user_text(self, text: str) -> None:
        text = (text or "").strip()
        if not text or self.realtime is None:
            return
        bus.publish("realtime.user_text", text)
        await self.realtime.send_text(text)

    async def _on_caption(self, caption: str) -> None:
        if self.realtime is not None:
            await self.realtime.inject_scene(caption)

    async def ask_about_upload(self, label: str) -> None:
        """Have Samantha ask, in the live session, whether a just-uploaded file
        should be kept in the wiki or treated as temporary. No-op when no
        session is up (the UI buttons still drive the decision).
        """
        if self.realtime is not None:
            await self.realtime.ask_about_upload(label)

    async def note_to_session(self, caption: str) -> None:
        """Drop a short note into the live session as ambient context (e.g. the
        content of a temporary file Opus just read). No-op without a session.
        """
        if self.realtime is not None:
            await self.realtime.inject_scene(caption)

    async def set_accessibility(self, on: bool) -> None:
        """Turn accessibility mode on/off mid-session.

        When ON: tells the realtime session to append the accessibility
        addendum, and spins up a background loop that OCRs the screen and
        injects the text as ambient context. When OFF: tears that loop down
        and reverts the addendum. Safe to call repeatedly with the same value.
        """
        on = bool(on)
        if state.accessibility == on:
            return
        state.accessibility = on
        log.info("accessibility mode -> %s", "on" if on else "off")
        bus.publish("realtime.status", state.snapshot())

        # Persist the choice so the next session starts in the same mode.
        self._prefs.accessibility = on
        try:
            self.prefs_store.save(self._prefs)
        except Exception:
            log.exception("preferences: save failed")

        if self.realtime is not None:
            await self.realtime.set_accessibility(on)

        if on:
            if self._screen_task is None or self._screen_task.done():
                self._screen_task = asyncio.create_task(
                    self._run_screen_loop(), name="accessibility-screen-loop"
                )
        else:
            if self._screen_task is not None:
                self._screen_task.cancel()
                try:
                    await self._screen_task
                except (asyncio.CancelledError, Exception):
                    pass
                self._screen_task = None

    async def _run_screen_loop(self) -> None:
        """Periodically OCR the screen and forward fresh text to the model.

        Throttled by `settings.accessibility_screen_interval` and de-duplicated
        by a content hash so repeated identical screens don't spam the model
        (the persona is already told to stay quiet on no-change, but this
        keeps token cost in check too).
        """
        interval = max(2.0, float(settings.accessibility_screen_interval))
        last_hash = ""
        log.info("accessibility screen loop started (interval=%.1fs)", interval)
        try:
            while True:
                try:
                    text = await read_screen(language=self._session_language)
                except Exception:
                    log.exception("accessibility: read_screen failed")
                    text = ""

                if text:
                    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()
                    if digest != last_hash and self.realtime is not None:
                        last_hash = digest
                        try:
                            await self.realtime.inject_screen_text(text)
                        except Exception:
                            log.exception("accessibility: inject_screen_text failed")

                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            log.info("accessibility screen loop cancelled")
            raise

    # ── Time-based autonomy ───────────────────────────────────────────────
    async def _run_schedule_loop(self) -> None:
        """Poll the schedule store and fire any cron job that's due.

        The store is re-read each tick so jobs added/removed mid-session take
        effect immediately. ``mark_ran`` records the firing minute so a job
        can't double-fire within the same minute even across short polls.
        """
        interval = max(5.0, float(settings.schedule_poll_interval))
        log.info("schedule loop started (poll=%.0fs)", interval)
        try:
            while True:
                try:
                    now = datetime.now()
                    marker = minute_marker(now)
                    for job in self.schedule_store.due(now):
                        self.schedule_store.mark_ran(job.id, marker)
                        log.info("schedule: firing job %s (%r)", job.id, job.when)
                        bus.publish("schedule.fired", {
                            "id": job.id, "when": job.when, "prompt": job.prompt,
                        })
                        if self.realtime is not None:
                            await self.realtime.run_scheduled_task(job.prompt)
                except Exception:
                    log.exception("schedule: poll failed")
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            log.info("schedule loop cancelled")
            raise

    async def _run_pulse_loop(self) -> None:
        """Every ``pulse_interval_s`` seconds, give Samantha a chance to speak
        proactively. The realtime session itself skips the tick when a
        response is already in flight; we additionally hold off while she's
        mid-thought or mid-sentence so a pulse never steps on a live turn.
        """
        interval = max(30.0, float(self._prefs.pulse_interval_s))
        log.info("pulse loop started (interval=%.0fs)", interval)
        try:
            while True:
                await asyncio.sleep(interval)
                if self.realtime is None or state.speaking or state.thinking:
                    continue
                try:
                    await self.realtime.pulse()
                except Exception:
                    log.exception("pulse: tick failed")
        except asyncio.CancelledError:
            log.info("pulse loop cancelled")
            raise

    def pulse_status(self) -> dict:
        active = self._pulse_task is not None and not self._pulse_task.done()
        return {
            "enabled": bool(self._prefs.pulse_enabled),
            "interval_s": float(self._prefs.pulse_interval_s),
            "active": active,
        }

    async def set_pulse(
        self, enabled: bool | None = None, interval_s: float | None = None
    ) -> dict:
        """Toggle the pulse on/off and/or change its interval, persist the
        choice, and (if a session is live) restart the loop to apply it.
        """
        if enabled is not None:
            self._prefs.pulse_enabled = bool(enabled)
        if interval_s is not None:
            self._prefs.pulse_interval_s = max(30.0, float(interval_s))
        try:
            self.prefs_store.save(self._prefs)
        except Exception:
            log.exception("preferences: save failed (pulse)")

        # Restart the loop so a new interval / on-off takes effect now.
        if self._pulse_task is not None:
            self._pulse_task.cancel()
            try:
                await self._pulse_task
            except (asyncio.CancelledError, Exception):
                pass
            self._pulse_task = None
        if state.active and self._prefs.pulse_enabled:
            self._pulse_task = asyncio.create_task(
                self._run_pulse_loop(), name="pulse-loop"
            )
        return self.pulse_status()


orchestrator = Orchestrator()
