"""Process-wide singletons for the skill subsystem.

We deliberately keep these module-level so the `@tool()` functions in
``tools.py`` share the same recorder/store/forge state — there is one user,
one Mac, one recording (and one pending forge) at a time.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ...config import settings
from .compiler_text import ForgeResult
from .recorder import SkillRecorder
from .store import SkillStore

_BASE = Path(settings.skills_path)
recorder = SkillRecorder(_BASE)
store = SkillStore(_BASE)


@dataclass
class PendingForge:
    """A forged skill awaiting the user's confirmation before it is saved."""
    name: str
    description: str
    result: ForgeResult


class ForgeSession:
    """Holds the single in-flight :class:`PendingForge`, if any.

    Skill Forge is conversational: ``forge_skill`` proposes a skill and the
    user confirms (or corrects) in a *later* turn, so the proposal must
    survive between tool calls. One user → one pending forge at a time.
    """

    def __init__(self) -> None:
        self.pending: PendingForge | None = None

    def set(self, name: str, description: str, result: ForgeResult) -> None:
        self.pending = PendingForge(name=name, description=description, result=result)

    def clear(self) -> None:
        self.pending = None


forge_session = ForgeSession()
