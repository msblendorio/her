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


settings = Settings()
