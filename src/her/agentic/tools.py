"""Back-compat facade for the agentic tools registry.

The actual registration happens in :mod:`her.agentic.registry` (decorator
machinery) and the domain modules (``macos``, ``calendar``, ``screen``,
``web``, ``accessibility``) that declare ``@tool()`` async functions.
This module exists only so that pre-existing
``from her.agentic.tools import TOOLS / openai_specs / by_name`` imports
keep working.

New code should import directly from :mod:`her.agentic` instead.
"""
from __future__ import annotations

# Importing the package runs the domain submodules, which register every
# tool. We then re-export the registry surface.
from . import (  # noqa: F401  (side-effect: tool registration)
    accessibility,
    calendar,
    email,
    macos,
    screen,
    web,
)
from .registry import TOOLS, Tool, by_name, openai_specs, tool

__all__ = ["TOOLS", "Tool", "by_name", "openai_specs", "tool"]
