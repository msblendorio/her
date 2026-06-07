"""Phase 2 — YouBench + the promotion gate. SCAFFOLD.

YouBench is a *personal* benchmark auto-generated from the user's real requests,
held out from training — "an exam made of you" (§12). It scores the student vs.
the teacher on style-match, held-out perplexity, preference win-rate (judged by
a frontier model in shadow), tool-calling fidelity, and safety/persona
regressions. An adapter is promoted to ``primary`` only if it beats threshold
*without* regressions; otherwise it stays in shadow or is rolled back.

Not implemented yet — see future-features/AST_MODE_PLAN.md §12.
"""
from __future__ import annotations

from .store import AstStore


def build_youbench(store: AstStore) -> str:
    """Generate/refresh the held-out personal benchmark under data/ast/youbench/."""
    raise NotImplementedError(
        "YouBench generation is a Phase 2 feature — see AST_MODE_PLAN.md §12."
    )


def evaluate(store: AstStore, adapter_path: str) -> dict:
    """Score an adapter on YouBench and return metrics + a promote/rollback call."""
    raise NotImplementedError(
        "YouBench evaluation + promotion gate is a Phase 2 feature — see AST_MODE_PLAN.md §12."
    )
