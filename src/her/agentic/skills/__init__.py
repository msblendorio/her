"""Skill-learning subsystem: record → compile → store → replay.

Importing this package registers four tools with the agentic registry
via :mod:`her.agentic.skills.tools`. ``runtime`` is imported first so
the recorder/store singletons exist before the tools reference them.
"""
from __future__ import annotations

from . import runtime  # noqa: F401  (creates the recorder/store singletons)
from . import tools  # noqa: F401  (registers the @tool() functions)
from .runtime import recorder, store

__all__ = ["recorder", "store"]
