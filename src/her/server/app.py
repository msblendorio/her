"""FastAPI app: static UI + control endpoints + WebSocket bridges."""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .. import __version__
from ..agentic.tools import TOOLS
from ..config import settings
from ..core.orchestrator import orchestrator
from ..core.state import state
from ..i18n import LANGUAGES, resolve as resolve_lang
from ..memory.store import MemoryStore
from .ws import register_ws_routes

log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent.parent / "ui" / "static"


def create_app() -> FastAPI:
    app = FastAPI(title="her", version=__version__)

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    register_ws_routes(app)

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(str(STATIC_DIR / "index.html"))

    @app.get("/api/state")
    async def get_state() -> dict:
        return state.snapshot()

    @app.get("/api/config")
    async def get_config() -> dict:
        mem_count = 0
        if settings.memory_enabled:
            try:
                mem_count = MemoryStore(settings.memory_path).count()
            except Exception:
                pass
        return {
            "version": __version__,
            "model": settings.openai_realtime_model,
            "voice": settings.openai_voice,
            "language": settings.assistant_language,
            "vision_enabled": settings.vision_enabled,
            "vision_interval_s": settings.vision_caption_interval,
            "world_model_enabled": settings.world_model_enabled,
            "memory_enabled": settings.memory_enabled,
            "memory_count": mem_count,
        }

    @app.get("/api/memory")
    async def get_memory() -> dict:
        if not settings.memory_enabled:
            return {"enabled": False, "entries": []}
        entries = MemoryStore(settings.memory_path).all()
        return {
            "enabled": True,
            "count": len(entries),
            "entries": [
                {
                    "timestamp": e.timestamp,
                    "summary": e.summary,
                    "key_facts": e.key_facts,
                    "turn_count": e.turn_count,
                    "duration_s": e.duration_s,
                }
                for e in entries
            ],
        }

    @app.get("/api/cowork")
    async def get_cowork() -> dict:
        from ..cowork.client import client as cowork_client
        from ..cowork.skills_store import skill_store
        skills: list[dict] = []
        try:
            skills = skill_store.list_skills()
        except Exception:
            pass
        return {
            "enabled": settings.cowork_enabled,
            "configured": cowork_client.is_configured(),
            "credential": cowork_client.credential_kind(),
            "model": settings.anthropic_model,
            "skills": skills,
        }

    @app.get("/api/wiki")
    async def get_wiki() -> dict:
        from ..memory.wiki.store import store as wiki_store
        pages: list[dict] = []
        try:
            pages = wiki_store.list_pages()
        except Exception:
            pass
        return {
            "enabled": settings.wiki_enabled,
            "count": len(pages),
            "pages": pages,
        }

    @app.get("/api/languages")
    async def get_languages() -> dict:
        return {"default": resolve_lang(settings.assistant_language), "languages": LANGUAGES}

    @app.get("/api/tools")
    async def get_tools() -> dict:
        return {
            "enabled": settings.agentic_enabled,
            "tools": [
                {"name": t.name, "description": t.description, "parameters": t.parameters}
                for t in TOOLS
            ],
        }

    # ── Schedule (cron-driven tasks) ─────────────────────────────────────
    @app.get("/api/schedule")
    async def get_schedule() -> dict:
        jobs = orchestrator.schedule_store.list()
        return {
            "enabled": settings.schedule_enabled,
            "jobs": [j.to_dict() for j in jobs],
        }

    @app.post("/api/schedule")
    async def add_schedule(request: Request) -> JSONResponse:
        when = prompt = ""
        try:
            body = await request.json()
            if isinstance(body, dict):
                when = str(body.get("when") or "").strip()
                prompt = str(body.get("prompt") or "").strip()
        except Exception:
            pass
        try:
            job = orchestrator.schedule_store.add(when, prompt)
        except ValueError as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
        return JSONResponse({"ok": True, "job": job.to_dict()})

    @app.delete("/api/schedule/{job_id}")
    async def delete_schedule(job_id: str) -> dict:
        return {"ok": orchestrator.schedule_store.remove(job_id)}

    @app.post("/api/schedule/{job_id}/toggle")
    async def toggle_schedule(job_id: str) -> JSONResponse:
        job = orchestrator.schedule_store.toggle(job_id)
        if job is None:
            return JSONResponse({"ok": False, "error": "not found"}, status_code=404)
        return JSONResponse({"ok": True, "job": job.to_dict()})

    # ── Pulse (ambient proactive check-in) ───────────────────────────────
    @app.get("/api/pulse")
    async def get_pulse() -> dict:
        return orchestrator.pulse_status()

    @app.post("/api/pulse")
    async def set_pulse(request: Request) -> dict:
        enabled = interval_s = None
        try:
            body = await request.json()
            if isinstance(body, dict):
                if "enabled" in body and body["enabled"] is not None:
                    enabled = bool(body["enabled"])
                if body.get("interval_s") is not None:
                    interval_s = float(body["interval_s"])
        except Exception:
            pass
        return await orchestrator.set_pulse(enabled=enabled, interval_s=interval_s)

    @app.post("/api/session/start")
    async def start_session(request: Request) -> dict:
        # Body is optional: {"language": "it" | "en" | "es" | "fr" | "de"}
        language = ""
        try:
            body = await request.json()
            if isinstance(body, dict):
                language = str(body.get("language") or "")
        except Exception:
            pass
        await orchestrator.start(language=language)
        return {"ok": True, "state": state.snapshot()}

    @app.post("/api/session/stop")
    async def stop_session() -> dict:
        await orchestrator.stop()
        return {"ok": True, "state": state.snapshot()}

    @app.post("/api/text")
    async def post_text(request: Request) -> dict:
        text = ""
        try:
            body = await request.json()
            if isinstance(body, dict):
                text = str(body.get("text") or "").strip()
        except Exception:
            pass
        if text:
            await orchestrator.push_user_text(text)
        return {"ok": True}

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        await orchestrator.stop()

    return app


app = create_app()
