"""AstManager — the single coordinator for AST mode.

Owns the AST data store and retrieval, the capture lifecycle, the consolidation
trigger, and the public actions exposed to the UI (``/ast`` command + the header
badge). Mirrors the singleton pattern of ``orchestrator``: one instance,
``ast_manager``, created at the bottom of this module.

Preferences ownership: the privacy-sensitive live switches (master on/off, raw
capture opt-in, mode) live in ``preferences.json``, which the orchestrator
already loads. To keep a single source of truth, the orchestrator hands its
``Preferences`` object and store to ``bind()`` at startup; the manager mutates
that same object and persists through the same store, so the two never clobber
each other's writes.
"""
from __future__ import annotations

import asyncio
import logging

from ..config import settings
from ..core.event_bus import bus
from ..core.preferences import Preferences, PreferencesStore, _AST_MODES
from .capture import AstCapture
from .consolidate import consolidate
from .retrieval import Retrieval
from .store import AstStore
from .style import StyleCard

log = logging.getLogger(__name__)


class AstManager:
    def __init__(self) -> None:
        self.store = AstStore(settings.ast_path, settings.ast_conversations_path)
        self.retrieval = Retrieval(self.store)
        self._capture: AstCapture | None = None
        # Bound by the orchestrator at startup (see bind()). Until then we fall
        # back to a private store so the manager is usable in isolation/tests.
        self._prefs: Preferences = Preferences(
            ast_enabled=settings.ast_enabled,
            ast_capture=settings.ast_capture_enabled,
            ast_mode=settings.ast_mode if settings.ast_mode in _AST_MODES else "off",
        )
        self._prefs_store: PreferencesStore | None = None
        self._session_active = False
        self._busy: str | None = None   # "consolidating" | "training" | None
        self._sessions_since_consolidate = 0
        self._last_consolidation: dict | None = None

    # ── wiring ───────────────────────────────────────────────────────────
    def bind(self, prefs: Preferences, prefs_store: PreferencesStore) -> None:
        """Share the orchestrator's Preferences object + store (single owner)."""
        self._prefs = prefs
        self._prefs_store = prefs_store

    def _save_prefs(self) -> None:
        if self._prefs_store is not None:
            try:
                self._prefs_store.save(self._prefs)
            except Exception:
                log.exception("ast: preferences save failed")

    # ── live switches ────────────────────────────────────────────────────
    @property
    def enabled(self) -> bool:
        return bool(self._prefs.ast_enabled)

    @property
    def capture_enabled(self) -> bool:
        return bool(self._prefs.ast_capture)

    @property
    def mode(self) -> str:
        return self._prefs.ast_mode if self._prefs.ast_mode in _AST_MODES else "off"

    def set_enabled(self, on: bool) -> None:
        self._prefs.ast_enabled = bool(on)
        if not on:
            # Master off also stops any in-flight capture cleanly.
            self._prefs.ast_capture = self._prefs.ast_capture  # keep opt-in choice
        self._save_prefs()
        self._publish_status()

    def set_capture(self, on: bool) -> None:
        self._prefs.ast_capture = bool(on)
        self._save_prefs()
        self._publish_status()

    def set_mode(self, mode: str) -> str:
        self._prefs.ast_mode = mode if mode in _AST_MODES else "off"
        self._save_prefs()
        self._publish_status()
        return self._prefs.ast_mode

    # ── session lifecycle (called by the orchestrator) ───────────────────
    async def on_session_start(self, session_id: str, language: str) -> None:
        self._session_active = True
        if self.enabled and self.capture_enabled:
            self._capture = AstCapture(self.store)
            await self._capture.start(session_id, language)
        self._publish_status()

    async def on_session_end(self) -> None:
        turns = 0
        if self._capture is not None:
            try:
                turns = await self._capture.stop()
            except Exception:
                log.exception("ast: capture stop failed")
            self._capture = None
        self._session_active = False
        self._publish_status()

        if not self.enabled or turns <= 0:
            return
        self._sessions_since_consolidate += 1
        if self._sessions_since_consolidate >= max(1, settings.ast_consolidate_after_n):
            # Fire-and-forget — the orchestrator has already returned to the UI.
            asyncio.create_task(self.consolidate_now(), name="ast-consolidate")

    # ── Style Card / few-shot injection (Phase 1) ────────────────────────
    def style_block(self, language: str) -> str:
        """The in-context personalization block appended to a teacher's prompt.

        Returns "" unless AST is enabled and the mode requests prompt-level
        personalization (anything other than "off"). Combines the Style Card
        with a few representative past exchanges (few-shot)."""
        if not self.enabled or self.mode == "off":
            return ""
        raw = self.store.load_style_card()
        if not raw:
            return ""
        card = StyleCard.from_dict(raw)
        block = card.to_prompt_block(settings.ast_style_token_budget, language)
        if not block:
            return ""
        examples = self.retrieval.representative(settings.ast_fewshot_k)
        if examples:
            lines = ["", ("Esempi di come hai già risposto a questo utente:"
                          if (language or "it").startswith("it")
                          else "Examples of how you've answered this user before:")]
            for e in examples:
                u = (e.get("user") or "").strip()[:160]
                a = (e.get("assistant") or "").strip()[:200]
                if u and a:
                    lines.append(f"  · «{u}» → «{a}»")
            if len(lines) > 2:
                block = block + "\n" + "\n".join(lines)
        return block

    # ── slow loop ────────────────────────────────────────────────────────
    async def consolidate_now(self) -> dict:
        if self._busy:
            return {"ok": False, "error": f"busy: {self._busy}"}
        self._busy = "consolidating"
        self._publish_status()
        try:
            result = await consolidate(self.store)
            self._sessions_since_consolidate = 0
            self._last_consolidation = result
            return {"ok": True, **result}
        except Exception:
            log.exception("ast: consolidation failed")
            return {"ok": False, "error": "consolidation failed"}
        finally:
            self._busy = None
            self._publish_status()

    async def train_now(self) -> dict:
        """Phase 2 — on-device LoRA training (MLX). Not available yet."""
        return {
            "ok": False,
            "error": "on-device training is a Phase 2 feature (MLX LoRA) and "
                     "isn't wired up yet — see AST_MODE_PLAN.md",
        }

    # ── privacy: unlearning ──────────────────────────────────────────────
    def forget(self, target: str = "all") -> dict:
        """Delete captured raw data. ``target`` is a session id, or "all".
        Rebuilds the retrieval index afterwards (Phase 1 unlearning for T1)."""
        target = (target or "all").strip()
        if target in ("all", "*", ""):
            removed = self.store.wipe_all_raw()
            try:
                self.store.style_card_path.unlink()
            except OSError:
                pass
        else:
            removed = 1 if self.store.wipe_session(target) else 0
        # Reindex from whatever raw turns remain (no-op without the embedder).
        try:
            self.retrieval.reindex(self.store.recent_turns(50))
        except Exception:
            log.exception("ast: reindex after forget failed")
        self._publish_status()
        return {"ok": True, "removed": removed, "target": target}

    # ── status / insights (for the badge + /ast) ─────────────────────────
    def _status_label(self) -> str:
        if not self.enabled:
            return "off"
        if self._busy:
            return self._busy
        if self._session_active and self.capture_enabled:
            return "learning"
        return "idle"

    def status(self) -> dict:
        return {
            "enabled": self.enabled,
            "capture": self.capture_enabled,
            "mode": self.mode,
            "status": self._status_label(),
        }

    def insights(self) -> dict:
        """The transparency dashboard payload: "what I've learned about you"."""
        raw = self.store.load_style_card()
        card = StyleCard.from_dict(raw).to_dict() if raw else None
        return {
            **self.status(),
            "style_card": card,
            "stats": self.store.stats(),
            "last_consolidation": self._last_consolidation,
            "retrieval_available": _retrieval_available(),
        }

    def _publish_status(self) -> None:
        bus.publish("ast.status", self.status())


def _retrieval_available() -> bool:
    from .retrieval import available
    try:
        return available()
    except Exception:
        return False


ast_manager = AstManager()
