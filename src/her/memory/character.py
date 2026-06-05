"""Persistent character profile of the user.

Samantha modulates her empathy on top of two signals: this slow-moving
profile (what kind of person is talking to her, refined across sessions),
and a fast live mood signal (see `reasoning/empathy.py`).

The profile is one small JSON file. It is refined fire-and-forget at the
end of each session: we hand the previous profile and the new transcript
to a cheap chat model and ask it to produce an updated profile in the
same schema. If the call fails we just keep the previous profile.

Kept deliberately short — every field ends up in the realtime system
prompt at the next session start, and a bloated profile hurts latency
and quality.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from ..config import settings
from ..reasoning.text_backend import chat_json
from .store import MemoryEntry, now_iso

log = logging.getLogger(__name__)

# Allowed values for the discrete fields. Kept narrow so the addendum
# template stays predictable.
COMMUNICATION_STYLES = ("direct", "playful", "reflective", "verbose", "terse")
EMOTIONAL_TONES = ("warm", "neutral", "guarded", "anxious", "buoyant")
EMPATHY_MIN, EMPATHY_MAX = 1, 5


@dataclass
class CharacterProfile:
    communication_style: str = "reflective"   # see COMMUNICATION_STYLES
    emotional_tone: str = "neutral"           # see EMOTIONAL_TONES
    empathy_baseline: int = 3                 # 1 (light touch) … 5 (very warm)
    sensitivities: list[str] = field(default_factory=list)   # topics to handle gently
    interests: list[str] = field(default_factory=list)       # things they care about
    notes: str = ""                           # one short free-form line
    updated_at: str = ""                      # ISO-8601, UTC
    sessions_observed: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "CharacterProfile":
        known = {f.name for f in fields(cls)}
        p = cls(**{k: v for k, v in d.items() if k in known})
        return p.clamped()

    def clamped(self) -> "CharacterProfile":
        """Return a copy with values forced into the allowed ranges/enums."""
        if self.communication_style not in COMMUNICATION_STYLES:
            self.communication_style = "reflective"
        if self.emotional_tone not in EMOTIONAL_TONES:
            self.emotional_tone = "neutral"
        self.empathy_baseline = max(EMPATHY_MIN, min(EMPATHY_MAX, int(self.empathy_baseline or 3)))
        self.sensitivities = [str(s).strip() for s in (self.sensitivities or []) if str(s).strip()][:5]
        self.interests = [str(s).strip() for s in (self.interests or []) if str(s).strip()][:5]
        self.notes = (self.notes or "").strip()[:240]
        return self

    def is_empty(self) -> bool:
        """True if we have observed no session yet — used by the addendum
        builder to skip the profile block entirely on the very first run."""
        return self.sessions_observed <= 0


class CharacterStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def load(self) -> CharacterProfile:
        try:
            raw = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return CharacterProfile()
        except OSError:
            log.warning("character: could not read %s", self.path)
            return CharacterProfile()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            log.warning("character: %s is not valid JSON — starting empty", self.path)
            return CharacterProfile()
        if not isinstance(data, dict):
            return CharacterProfile()
        return CharacterProfile.from_dict(data)

    def save(self, profile: CharacterProfile) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(
            dir=str(self.path.parent), prefix=".character_", suffix=".json"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(profile.clamped().to_dict(), f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise


_REFINE_PROMPT = (
    "You maintain a small JSON profile of Samantha's user so she can modulate "
    "her empathy. Given the previous profile and the transcript of the session "
    "that just ended, return an UPDATED profile in the SAME JSON schema.\n"
    "Schema (all fields required):\n"
    "{\n"
    "  \"communication_style\": one of [direct, playful, reflective, verbose, terse],\n"
    "  \"emotional_tone\":      one of [warm, neutral, guarded, anxious, buoyant],\n"
    "  \"empathy_baseline\":    integer 1..5 (how much warmth this person seems to want),\n"
    "  \"sensitivities\":       up to 5 short topics to handle gently,\n"
    "  \"interests\":           up to 5 short topics they care about,\n"
    "  \"notes\":               one short line (<=240 chars) of useful context\n"
    "}\n"
    "Be conservative: keep prior values unless this session clearly contradicts them. "
    "Reply ONLY with the JSON object, no markdown."
)


def _profile_block(profile: CharacterProfile) -> str:
    return json.dumps(profile.to_dict(), ensure_ascii=False, indent=2)


def _transcript_block(turns: list[tuple[str, str]]) -> str:
    return "\n".join(
        f"{'User' if role == 'user' else 'Samantha'}: {text}"
        for role, text in turns
    )


async def refine_character(
    previous: CharacterProfile,
    turns: list[tuple[str, str]],
    recent_entries: list[MemoryEntry] | None = None,
) -> CharacterProfile | None:
    """Ask the cheap chat model to refine the profile.

    Returns the new profile on success, or None on any failure — the caller
    should fall back to keeping the previous one.
    """
    if len(turns) < 2:
        return None

    facts_block = ""
    if recent_entries:
        bullets = []
        for e in recent_entries[-3:]:
            for fact in (e.key_facts or [])[:3]:
                bullets.append(f"- {fact}")
        if bullets:
            facts_block = "Recent key facts:\n" + "\n".join(bullets) + "\n\n"

    user_msg = (
        f"Previous profile:\n{_profile_block(previous)}\n\n"
        f"{facts_block}"
        f"Transcript of the session that just ended:\n{_transcript_block(turns)}"
    )

    parsed = await chat_json(
        [
            {"role": "system", "content": _REFINE_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        cloud_model=settings.memory_summarizer_model,
        temperature=0.2,
    )
    if not isinstance(parsed, dict):
        return None

    new_profile = CharacterProfile.from_dict(parsed)
    new_profile.sessions_observed = previous.sessions_observed + 1
    new_profile.updated_at = now_iso()
    return new_profile
