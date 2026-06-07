"""Phase 2 — on-device LoRA trainer (MLX). SCAFFOLD.

Trains/updates small, composable LoRA adapters on Apple Silicon via ``mlx`` /
``mlx-lm`` (§13): a persona adapter for "Samantha-for-you" and skill adapters
for recurring domains. Runs nightly when the Mac is idle + charging with no
active session and heavy components unloaded; a 3B QLoRA pass is feasible on the
16 GB M1 baseline (batch=1 + grad-accumulation, short seq-len, modest rank).

``mlx`` / ``mlx-lm`` are optional dependencies (the ``ast`` extra) and are NOT
bundled in the desktop app by default. Not implemented yet — see
future-features/AST_MODE_PLAN.md §13.
"""
from __future__ import annotations

from pathlib import Path


def can_train() -> bool:
    """True if the MLX training stack is importable (the `ast` extra)."""
    try:
        import mlx_lm  # noqa: F401
    except Exception:
        return False
    return True


def train_adapter(dataset_dir: str | Path, base_model: str, out_dir: str | Path) -> str:
    """Train a LoRA adapter and return its versioned path. Phase 2."""
    raise NotImplementedError(
        "AST on-device LoRA training (MLX) is a Phase 2 feature — see "
        "AST_MODE_PLAN.md §13. Install the `ast` extra and supply a dataset."
    )
