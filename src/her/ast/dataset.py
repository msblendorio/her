"""Phase 2 — dataset builder (distillation + preference pairs). SCAFFOLD.

Turns captured raw turns into training examples: distillation examples that
pair a prompt with the *teacher's* output (§8.2), and preference pairs derived
from implicit feedback — corrections, rephrasings, barge-in interruptions (§8.3).
Quality filtering / anomaly rejection lives here too (anti data-poisoning).

Not implemented yet — see future-features/AST_MODE_PLAN.md §8.
"""
from __future__ import annotations

from .store import AstStore


def build_distillation_set(store: AstStore, run: str) -> str:
    """Write a distillation dataset for ``run`` under data/ast/datasets/<run>/."""
    raise NotImplementedError(
        "AST dataset builder is a Phase 2 feature — see AST_MODE_PLAN.md §8.2."
    )


def build_preference_pairs(store: AstStore, run: str) -> str:
    """Write DPO/KTO preference pairs from implicit feedback (§8.3)."""
    raise NotImplementedError(
        "AST preference-pair builder is a Phase 3 feature — see AST_MODE_PLAN.md §8.3."
    )
