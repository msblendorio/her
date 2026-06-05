"""Settings loaded from environment / .env."""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    openai_api_key: str = ""
    openai_realtime_model: str = "gpt-realtime-mini"
    openai_voice: str = "shimmer"
    assistant_language: str = "it"

    # ── Local / free backends (opt-in; defaults keep OpenAI + Anthropic) ──
    # Two independent switches let you go fully on-device, model by model:
    #
    #   voice_backend = "openai" (hosted Realtime, default) | "local"
    #       "local" replaces the OpenAI Realtime speech-to-speech model with an
    #       on-device pipeline: faster-whisper (STT) → Ollama LLM → Kokoro (TTS),
    #       with webrtcvad for turn detection. No OPENAI_API_KEY required.
    #
    #   llm_backend = "cloud" (OpenAI + Anthropic, default) | "local"
    #       "local" routes every text/brain call — Cowork, the knowledge wiki,
    #       the memory summarizer, the character profiler and the skill
    #       compiler — to the same Ollama endpoint instead of Claude / gpt-4o.
    #
    # Both are free and run on an Apple-Silicon Mac with 16 GB RAM. They share
    # one Ollama server (OpenAI-compatible API). See local_session.py.
    voice_backend: str = "openai"
    llm_backend: str = "cloud"

    # Ollama OpenAI-compatible endpoint + models (used when a backend is
    # "local"). Pull the models first: ``ollama pull qwen3:8b`` etc.
    local_llm_base_url: str = "http://localhost:11434/v1"
    local_llm_model: str = "qwen3:8b"
    # Vision-capable local model, used only by the skill compiler (it reads
    # screenshots). Leave as-is if you don't record skills in local mode.
    local_llm_vision_model: str = "qwen2.5vl:7b"

    # Local speech-to-text (faster-whisper / CTranslate2). Model sizes:
    # tiny/base/small/medium/large-v3. "small" balances speed and accuracy on
    # an M1; "int8" compute keeps the memory footprint low. Leave
    # local_stt_language blank to auto-detect, or pin it (e.g. "it") for speed.
    local_stt_model: str = "small"
    local_stt_compute: str = "int8"
    local_stt_device: str = "cpu"
    local_stt_language: str = ""

    # Local text-to-speech (Kokoro, ONNX runtime). The voice id is paired with
    # an espeak language ("it", "en-us", "es", "fr-fr", "pt-br"); leave
    # local_tts_lang blank to derive it from the session language. espeak-ng is
    # bundled (via espeakng-loader), so no system install is needed. The model
    # files are downloaded once to local_tts_model_path / local_tts_voices_path
    # if missing (~340 MB total).
    local_tts_voice: str = "af_heart"
    local_tts_lang: str = ""
    local_tts_speed: float = 1.0
    local_tts_model_path: str = "data/kokoro/kokoro-v1.0.onnx"
    local_tts_voices_path: str = "data/kokoro/voices-v1.0.bin"

    # Turn detection (webrtcvad). Aggressiveness 0-3 (higher = more
    # aggressive about classifying frames as non-speech); a turn ends after
    # local_vad_silence_ms of continuous silence following speech.
    local_vad_aggressiveness: int = 2
    local_vad_silence_ms: int = 700

    vision_enabled: bool = True
    vision_caption_interval: float = 4.0
    vision_model_id: str = "vikhyatk/moondream2"
    vision_device: str = "mps"

    world_model_enabled: bool = False

    host: str = "0.0.0.0"
    port: int = 8765

    daily_budget_usd: float = 2.0

    # Persistent memory across sessions.
    memory_enabled: bool = True
    memory_path: str = "data/memory.jsonl"
    memory_recall_count: int = 5
    memory_summarizer_model: str = "gpt-4o-mini"

    # Visual memory track. When on (and vision_enabled), the webcam captions
    # produced during a session are summarized at session-end into a short
    # "what Samantha saw" block, persisted alongside the textual summary,
    # and replayed in the recall block of the next session.
    visual_memory_enabled: bool = True

    # Agentic computer control (macOS only). When enabled, Samantha can call
    # tools like open_app / open_url / take_screenshot / set_volume / etc.
    # See src/her/agentic/tools.py for the full registry.
    agentic_enabled: bool = True

    # Accessibility mode (opt-in via the voice tool toggle_accessibility_mode).
    # When on, the screen is OCR'd via Apple Vision and the text is injected
    # as ambient context every N seconds.
    accessibility_screen_interval: float = 6.0

    # Persistent user preferences (currently: whether accessibility mode is
    # on). Saved every time the mode is toggled, loaded at the next session
    # start so a visually impaired user does not have to reactivate it.
    preferences_path: str = "data/preferences.json"

    # Empathy modulation. Combines a persistent character profile (refined
    # by a cheap chat model at the end of each session) with a live mood
    # signal inferred from user utterances. The profile lives in its own
    # tiny JSON file so it survives across sessions.
    empathy_enabled: bool = True
    character_path: str = "data/character.json"

    # Skill learning. Samantha can record the user's clicks/shortcuts on
    # demand and have a cheap chat model compile the trace into an
    # AppleScript that replays the same intent. Stored per-skill under
    # ``skills_path``; the model used for compilation must be vision-capable.
    skills_path: str = "data/skills"
    skills_compiler_model: str = "gpt-4o-mini"
    # Skill Forge: Samantha can also forge a skill from a *spoken description*
    # (no demonstration) — the user explains the action and a chat model turns
    # it into the same AppleScript artefact, saved into the same store. This
    # model only ever sees text (no screenshots), so it need not be
    # vision-capable and can be cheaper/local.
    skills_forge_model: str = "gpt-4o-mini"

    # ── Cowork / Anthropic ────────────────────────────────────────────────
    # Samantha can delegate open-ended knowledge-work tasks to Claude (the
    # engine behind Claude Cowork) and author new Agent Skills that Cowork and
    # Claude Code pick up from ``cowork_skills_path``. Two credential paths are
    # supported, in this order: a pay-per-use Anthropic API key, or a Claude
    # Pro/Max subscription OAuth token (``ant auth login`` / Claude Code,
    # ``sk-ant-oat...``). The ``anthropic`` SDK also falls back to the same env
    # vars if these are blank. Cowork features stay dormant until one is set.
    anthropic_api_key: str = ""
    anthropic_auth_token: str = ""
    anthropic_model: str = "claude-opus-4-8"
    cowork_enabled: bool = True
    # Where authored Agent Skills are written. ``~`` is expanded. The global
    # ``~/.claude/skills`` dir is read by both Claude Cowork and Claude Code.
    cowork_skills_path: str = "~/.claude/skills"

    # ── Knowledge-base LLM wiki (Karpathy pattern) ────────────────────────
    # A persistent, interlinked markdown wiki maintained by Claude: ingest a
    # source -> update pages; query -> answer + file findings; lint -> health
    # check. Lives under ``wiki_path`` as index.md + log.md + pages/. Powered
    # by the same Anthropic client as Cowork.
    wiki_enabled: bool = True
    wiki_path: str = "data/wiki"
    # Cap on how many existing wiki pages are loaded into the model's context
    # for an ingest/query, to bound token cost.
    wiki_max_context_pages: int = 12

    # File uploads → wiki. A file dropped in the UI (pdf/md/txt/docx/jpg/png)
    # is saved here, read by Claude Opus (natively for pdf/images, extracted
    # text for docx/txt/md), and ingested into the wiki. The size cap stays
    # below Anthropic's 32MB document limit.
    uploads_path: str = "data/uploads"
    upload_max_mb: int = 25

    # ── Time-based autonomy (see core/scheduler.py) ───────────────────────
    # Schedule: user-defined cron jobs that hand Samantha a prompt at fixed
    # times. Pulse: a recurring ambient self-check where she decides whether
    # to say anything proactively. Both run only while a session is active.
    # The schedule store is polled every ``schedule_poll_interval`` seconds;
    # keeping it under a minute guarantees minute-granular cron never slips.
    schedule_enabled: bool = True
    schedule_path: str = "data/schedule.json"
    schedule_poll_interval: float = 20.0
    # Default pulse cadence; the live on/off + interval are persisted per-user
    # in preferences.json (toggled via the /pulse command).
    pulse_default_interval_s: float = 180.0


settings = Settings()
