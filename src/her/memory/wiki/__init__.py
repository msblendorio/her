"""Knowledge-base LLM wiki (Karpathy pattern).

A persistent, interlinked markdown wiki that Claude maintains: ingest a source
to update pages, query to answer from them, lint to keep them healthy. The
store is pure filesystem; the engine drives the three LLM operations through
the shared Cowork Anthropic client.

Importing this package registers the wiki voice tools with the agentic
registry (via :mod:`her.memory.wiki.tools`).
"""
from __future__ import annotations

from .engine import WikiEngine, engine
from .store import WikiStore, store

__all__ = ["WikiStore", "store", "WikiEngine", "engine"]
