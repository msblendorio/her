"""Process-wide singletons for the skill subsystem.

We deliberately keep these module-level so the four `@tool()` functions
in ``tools.py`` share the same recorder/store instance — there is one
user, one Mac, one recording at a time.
"""
from __future__ import annotations

from pathlib import Path

from ...config import settings
from .recorder import SkillRecorder
from .store import SkillStore

_BASE = Path(settings.skills_path)
recorder = SkillRecorder(_BASE)
store = SkillStore(_BASE)
