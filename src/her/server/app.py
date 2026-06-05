"""FastAPI app: static UI + control endpoints + WebSocket bridges."""
from __future__ import annotations

import logging
import time
from pathlib import Path

from fastapi import FastAPI, File, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .. import __version__
from ..agentic.skills.compiler_text import forge_to_applescript
from ..agentic.skills.runtime import store as skill_store
from ..agentic.tools import TOOLS
from ..config import settings
from ..core.event_bus import bus
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
    async def index() -> HTMLResponse:
        # Stamp the version onto the cached UI assets so a new build always
        # fetches fresh JS/CSS. The packaged app runs inside a WKWebView whose
        # NetworkCache otherwise happily serves the previous version's app.js
        # (e.g. a /help typed after an update would reach the model because the
        # stale bundle had no slash-command handler). The HTML itself is sent
        # no-store so this query string is re-read on every launch.
        html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
        for asset in ("style.css", "app.js"):
            html = html.replace(
                f"/static/{asset}", f"/static/{asset}?v={__version__}"
            )
        return HTMLResponse(html, headers={"Cache-Control": "no-store"})

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
        # Reflect the active backend so the header isn't misleading in local mode.
        local_voice = settings.voice_backend.strip().lower() == "local"
        local_llm = settings.llm_backend.strip().lower() == "local"
        return {
            "version": __version__,
            "model": f"local:{settings.local_llm_model}" if local_voice
            else settings.openai_realtime_model,
            "anthropic_model": f"local:{settings.local_llm_model}" if local_llm
            else settings.anthropic_model,
            "voice": settings.local_tts_voice if local_voice else settings.openai_voice,
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

    # ── Skill Forge (author a skill from a spoken description) ────────────
    @app.get("/api/forge")
    async def list_forge() -> dict:
        return {"skills": skill_store.list_skills()}

    @app.post("/api/forge")
    async def preview_forge(request: Request) -> JSONResponse:
        """Forge a skill from a description and return a PREVIEW. Does NOT
        save — the client must POST the returned script to /api/forge/confirm.
        """
        name = description = ""
        try:
            body = await request.json()
            if isinstance(body, dict):
                name = str(body.get("name") or "").strip()
                description = str(body.get("description") or "").strip()
        except Exception:
            pass
        if not name or not description:
            return JSONResponse(
                {"ok": False, "error": "name and description are required"},
                status_code=400,
            )
        result = await forge_to_applescript(name, description)
        if result is None:
            return JSONResponse(
                {"ok": False, "error": "could not forge a script from that description"},
                status_code=422,
            )
        return JSONResponse({
            "ok": True,
            "name": name,
            "description": description,
            "summary": result.summary,
            "warnings": result.warnings,
            "script": result.script,
        })

    @app.post("/api/forge/confirm")
    async def confirm_forge_endpoint(request: Request) -> JSONResponse:
        """Persist a previewed skill. Saves exactly the script the user saw."""
        name = description = script = summary = ""
        try:
            body = await request.json()
            if isinstance(body, dict):
                name = str(body.get("name") or "").strip()
                description = str(body.get("description") or "").strip()
                script = str(body.get("script") or "").strip()
                summary = str(body.get("summary") or "").strip()
        except Exception:
            pass
        if not name or not script:
            return JSONResponse(
                {"ok": False, "error": "name and script are required"},
                status_code=400,
            )
        slug = skill_store.save_forged(name, description, script, summary)
        # Re-push the prompt so Samantha can invoke the new skill at once.
        bus.publish("skills.saved", {"slug": slug})
        return JSONResponse({"ok": True, "slug": slug})

    @app.delete("/api/forge/{slug}")
    async def delete_forge(slug: str) -> dict:
        existed = skill_store.delete(slug)
        if existed:
            bus.publish("skills.saved", {"slug": slug})
        return {"ok": existed}

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

    # ── File upload → knowledge wiki ─────────────────────────────────────
    @app.post("/api/upload")
    async def upload_file(file: UploadFile = File(...)) -> JSONResponse:
        from ..memory.wiki import uploads as wiki_uploads
        from ..memory.wiki.store import slugify

        name = file.filename or "upload"
        if not wiki_uploads.is_allowed(name):
            allowed = ", ".join(sorted(wiki_uploads.ALLOWED_EXTS))
            return JSONResponse(
                {"ok": False, "error": f"unsupported file type (allowed: {allowed})"},
                status_code=400,
            )
        data = await file.read()
        max_bytes = settings.upload_max_mb * 1024 * 1024
        if len(data) > max_bytes:
            return JSONResponse(
                {"ok": False, "error": f"file too large (max {settings.upload_max_mb} MB)"},
                status_code=400,
            )

        dest_dir = Path(settings.uploads_path).expanduser()
        dest_dir.mkdir(parents=True, exist_ok=True)
        stem = slugify(Path(name).stem)
        safe = f"{int(time.time())}-{stem}{Path(name).suffix.lower()}"
        dest = dest_dir / safe
        dest.write_bytes(data)

        item = wiki_uploads.pending.add(dest, name)
        # If a session is live, let Samantha voice the keep-or-temporary question.
        try:
            await orchestrator.ask_about_upload(name)
        except Exception:
            log.debug("upload: ask_about_upload failed", exc_info=True)
        return JSONResponse({"ok": True, "id": item.id, "label": name})

    @app.post("/api/upload/{upload_id}/keep")
    async def upload_keep(upload_id: str) -> JSONResponse:
        from ..memory.wiki import uploads as wiki_uploads
        from ..memory.wiki.engine import engine as wiki_engine

        item = wiki_uploads.pending.pop(upload_id)
        if item is None:
            return JSONResponse({"ok": False, "error": "unknown upload"}, status_code=404)
        try:
            msg = await wiki_engine.ingest_file(str(item.path), label=item.label)
        except Exception as e:
            log.exception("upload keep: ingest failed")
            return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
        bus.publish("wiki.ingested", {"title": item.label})
        return JSONResponse({"ok": True, "message": msg})

    @app.post("/api/upload/{upload_id}/discard")
    async def upload_discard(upload_id: str) -> JSONResponse:
        from ..memory.wiki import uploads as wiki_uploads
        from ..memory.wiki.engine import engine as wiki_engine

        item = wiki_uploads.pending.pop(upload_id)
        if item is None:
            return JSONResponse({"ok": False, "error": "unknown upload"}, status_code=404)
        # Temporary file: Opus reads it for the current conversation, the digest
        # is injected into the live session, then the original is deleted.
        try:
            digest = await wiki_engine.read_file(str(item.path), label=item.label)
        except Exception as e:
            log.exception("upload discard: read failed")
            digest = ""
            err = str(e)
        else:
            err = ""
        finally:
            try:
                item.path.unlink(missing_ok=True)
            except Exception:
                log.debug("upload discard: unlink failed", exc_info=True)
        if err:
            return JSONResponse({"ok": False, "error": err}, status_code=500)
        try:
            await orchestrator.note_to_session(
                f"[{item.label}] {digest}"
            )
        except Exception:
            log.debug("upload discard: note_to_session failed", exc_info=True)
        return JSONResponse({"ok": True, "message": digest})

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        await orchestrator.stop()

    return app


app = create_app()
