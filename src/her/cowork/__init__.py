"""Cowork integration: delegate knowledge-work to Claude and author skills.

Importing this package registers the Cowork voice tools with the agentic
registry (via :mod:`her.cowork.tools`). The shared :class:`CoworkClient`
singleton (:data:`client`) is also reused by the knowledge-base wiki engine
(:mod:`her.memory.wiki`), so both features run on one Anthropic credential.
"""
from __future__ import annotations

from .client import CoworkClient, client
from .skills_store import CoworkSkillStore, skill_store

__all__ = ["CoworkClient", "client", "CoworkSkillStore", "skill_store"]
