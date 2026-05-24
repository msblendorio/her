"""FastAPI app: static UI + control endpoints + WebSocket bridges."""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
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
