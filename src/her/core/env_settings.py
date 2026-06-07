"""Editable settings surfaced in the UI gear (⚙️) panel.

A small declarative schema over the subset of :class:`config.Settings` that is
safe and useful to tweak at runtime. The same definitions drive:

  * ``GET /api/settings``  — the schema + current values, rendered as a form
  * ``POST /api/settings`` — validation, a write to the on-disk ``.env``, and
    an in-place update of the live ``settings`` object so most changes apply to
    the *next* session without a restart.

The ``.env`` written is the very file pydantic-settings loads (``.env`` in the
process working directory): the repo root in dev, and
``~/Library/Application Support/Her`` in the packaged app (``launcher.py``
chdirs there before the server boots). Comments and key order are preserved;
only the touched keys are rewritten or appended.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from ..config import settings

log = logging.getLogger(__name__)


def _field(
    key: str,
    label: str,
    type: str = "text",
    *,
    options: list[str] | None = None,
    help: str = "",
    secret: bool = False,
) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "type": type,            # text | password | bool | number | select
        "options": options or [],
        "help": help,
        "secret": secret,
    }


# Sections mirror the four buckets the user thinks in: modes, API keys, models
# and plain variables. Each field's ``key`` is the lowercase attribute on
# ``settings`` (== the env var lowercased), so the current value and the type to
# coerce back to are both read straight off the live object.
SECTIONS: list[dict[str, Any]] = [
    {
        "id": "modes",
        "title": "Modes",
        "fields": [
            _field("voice_backend", "Voice backend", "select",
                   options=["openai", "local"],
                   help="openai = hosted Realtime · local = faster-whisper → Ollama → Kokoro (on-device)."),
            _field("llm_backend", "Brain (text) backend", "select",
                   options=["cloud", "local"],
                   help="cloud = OpenAI + Claude · local = route every text call to Ollama."),
            _field("vision_enabled", "Vision (webcam)", "bool",
                   help="Let Samantha caption the webcam frame."),
            _field("agentic_enabled", "Agentic computer control", "bool",
                   help="Allow open-app / open-url / screenshot / Shortcuts tools (macOS)."),
            _field("memory_enabled", "Persistent memory", "bool",
                   help="Summarise each session and recall it in the next one."),
            _field("visual_memory_enabled", "Visual memory", "bool",
                   help="Also remember what Samantha saw on the webcam."),
            _field("empathy_enabled", "Empathy modulation", "bool",
                   help="Adapt tone from a persistent character profile + live mood."),
            _field("cowork_enabled", "Cowork (Claude)", "bool",
                   help="Delegate open-ended knowledge work to Claude."),
            _field("wiki_enabled", "Knowledge wiki", "bool",
                   help="Maintain an interlinked markdown wiki from ingested files."),
            _field("schedule_enabled", "Schedule (cron tasks)", "bool",
                   help="Fire prompts at fixed times while a session is active."),
            _field("world_model_enabled", "World model (experimental)", "bool",
                   help="V-JEPA 2 stub — keep off unless wired to a real model."),
        ],
    },
    {
        "id": "keys",
        "title": "API keys",
        "fields": [
            _field("openai_api_key", "OpenAI API key", "password", secret=True,
                   help="Required for the hosted Realtime voice session. Stays on this Mac."),
            _field("anthropic_api_key", "Anthropic API key", "password", secret=True,
                   help="Pay-per-use key for Cowork + wiki (platform.claude.com)."),
            _field("anthropic_auth_token", "Anthropic OAuth token", "password", secret=True,
                   help="Alternative to the key: a Claude Pro/Max token (sk-ant-oat…)."),
        ],
    },
    {
        "id": "models",
        "title": "Models",
        "fields": [
            _field("openai_realtime_model", "OpenAI Realtime model",
                   help="e.g. gpt-realtime-mini (cheap) or gpt-realtime (top quality)."),
            _field("openai_voice", "OpenAI voice", "select",
                   options=["shimmer", "sage", "coral", "alloy"]),
            _field("anthropic_model", "Anthropic model",
                   help="e.g. claude-opus-4-8."),
            _field("memory_summarizer_model", "Memory summariser model",
                   help="Cheap chat model used to write session summaries."),
            _field("skills_compiler_model", "Skill compiler model",
                   help="Vision-capable model that compiles recorded skills."),
            _field("skills_forge_model", "Skill Forge model",
                   help="Text model that forges a skill from a description."),
            _field("local_llm_base_url", "Local LLM base URL",
                   help="Ollama OpenAI-compatible endpoint (used when a backend is local)."),
            _field("local_llm_model", "Local LLM model",
                   help="e.g. qwen3:8b. Pull it first: ollama pull qwen3:8b."),
            _field("local_llm_vision_model", "Local vision model",
                   help="e.g. qwen2.5vl:7b — only for the skill compiler."),
            _field("local_stt_model", "Local speech-to-text model", "select",
                   options=["tiny", "base", "small", "medium", "large-v3"]),
            _field("local_tts_voice", "Local TTS voice",
                   help="Kokoro voice id, or af_heart to auto-pick per language."),
        ],
    },
    {
        "id": "variables",
        "title": "Variables",
        "fields": [
            _field("assistant_language", "Default language", "select",
                   options=["it", "en", "es", "fr", "de"]),
            _field("daily_budget_usd", "Daily budget (USD)", "number",
                   help="Soft, informational spend reminder — no hard cutoff."),
            _field("vision_caption_interval", "Vision caption interval (s)", "number"),
            _field("accessibility_screen_interval", "Accessibility OCR interval (s)", "number"),
            _field("pulse_default_interval_s", "Pulse default interval (s)", "number"),
            _field("wiki_max_context_pages", "Wiki context pages", "number",
                   help="Cap on wiki pages loaded into the model per ingest/query."),
            _field("upload_max_mb", "Upload size cap (MB)", "number"),
            _field("host", "Server host",
                   help="127.0.0.1 = localhost only · 0.0.0.0 = reachable on the LAN. "
                        "The packaged app forces 127.0.0.1 regardless."),
            _field("port", "Server port", "number"),
        ],
    },
]

# Changing any of these can only take effect after a restart (the server binds
# the socket / the backend pipelines are chosen at startup), so the API flags
# the save with a "restart recommended" hint when one of them moves.
_RESTART_KEYS = {"host", "port", "voice_backend", "llm_backend"}

# Fields whose suggestions are the models actually pulled in the local Ollama
# server (queried live when the panel opens). They stay free-text so a value
# can still be entered when Ollama is down or a model isn't pulled yet.
_OLLAMA_MODEL_FIELDS = {"local_llm_model", "local_llm_vision_model"}


async def list_local_models(timeout: float = 2.0) -> list[str]:
    """Model ids installed in the local Ollama server, or ``[]`` if unreachable.

    Hits the same OpenAI-compatible ``/models`` endpoint the voice preflight
    uses (``LocalRealtimeSession._preflight_llm``). Errors are swallowed — a
    missing list just means no autocomplete, never a broken panel.
    """
    import httpx  # local import: keep module import-light

    base = settings.local_llm_base_url.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.get(f"{base}/models")
            r.raise_for_status()
            ids = [m.get("id") for m in (r.json().get("data") or []) if m.get("id")]
    except Exception as e:
        log.debug("ollama model list unavailable at %s: %s", base, e)
        return []
    return sorted(ids)


def with_ollama_suggestions(sections: list[dict[str, Any]], models: list[str]) -> list[dict[str, Any]]:
    """Inject the pulled-model list as ``suggestions`` on the Ollama fields."""
    if not models:
        return sections
    for section in sections:
        for f in section["fields"]:
            if f["key"] in _OLLAMA_MODEL_FIELDS:
                f["suggestions"] = models
    return sections


def env_path() -> Path:
    """The ``.env`` pydantic-settings reads — resolved against the cwd."""
    return Path(".env").resolve()


def _coerce_str(value: Any, field_type: str) -> str:
    """Render a submitted value as the string written to ``.env``."""
    if field_type == "bool":
        return "true" if value in (True, "true", "True", "1", 1, "on") else "false"
    if field_type == "number":
        s = str(value).strip()
        return s if s != "" else "0"
    return str(value).strip()


def _apply_to_settings(key: str, raw: str) -> None:
    """Mutate the live ``settings`` object in place, coercing to its type.

    Reassigning the module global wouldn't reach the many ``from ..config
    import settings`` references, so we update the existing instance's
    attributes — read live at the next session start.
    """
    current = getattr(settings, key, None)
    coerced: Any = raw
    if isinstance(current, bool):
        coerced = raw.lower() in ("true", "1", "on", "yes")
    elif isinstance(current, int) and not isinstance(current, bool):
        try:
            coerced = int(float(raw))
        except ValueError:
            return
    elif isinstance(current, float):
        try:
            coerced = float(raw)
        except ValueError:
            return
    try:
        setattr(settings, key, coerced)
    except Exception:
        pass


def _env_line_value(value: str) -> str:
    """Quote the value if it needs it (whitespace or a comment char)."""
    if value == "" or (value.isprintable() and not any(c in value for c in ' \t#"\'')):
        return value
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def update_env(updates: dict[str, str]) -> None:
    """Write ``updates`` (attr name → string) to the ``.env``, in place.

    Existing keys are rewritten where they sit; new ones are appended. Comments
    and the order of untouched lines are preserved.
    """
    path = env_path()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []

    remaining = dict(updates)
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name = stripped.split("=", 1)[0].strip().lower()
        if name in remaining:
            env_key = name.upper()
            lines[i] = f"{env_key}={_env_line_value(remaining.pop(name))}"

    for name, value in remaining.items():
        lines.append(f"{name.upper()}={_env_line_value(value)}")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def current_schema() -> list[dict[str, Any]]:
    """The section/field schema with each field's current value injected."""
    out: list[dict[str, Any]] = []
    for section in SECTIONS:
        fields = []
        for f in section["fields"]:
            value = getattr(settings, f["key"], "")
            if f["type"] == "bool":
                value = bool(value)
            elif f["type"] == "number":
                value = value
            else:
                value = "" if value is None else str(value)
            fields.append({**f, "value": value, "suggestions": []})
        out.append({"id": section["id"], "title": section["title"], "fields": fields})
    return out


def save(values: dict[str, Any]) -> dict[str, Any]:
    """Validate, persist to ``.env`` and apply in-memory. Returns a summary."""
    known = {f["key"]: f for s in SECTIONS for f in s["fields"]}
    updates: dict[str, str] = {}
    restart = False
    for key, field in known.items():
        if key not in values:
            continue
        raw = _coerce_str(values[key], field["type"])
        # Skip an unchanged secret left as its current value (no-op write).
        updates[key] = raw

    for key, raw in updates.items():
        if str(getattr(settings, key, "")) != raw:
            if key in _RESTART_KEYS:
                restart = True
        _apply_to_settings(key, raw)
        os.environ[key.upper()] = raw

    update_env(updates)
    return {"ok": True, "saved": len(updates), "restart_recommended": restart}
