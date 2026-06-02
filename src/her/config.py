"""Settings loaded from environment / .env."""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    openai_api_key: str = ""
    openai_realtime_model: str = "gpt-realtime-mini"
    openai_voice: str = "shimmer"
    assistant_language: str = "it"

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
