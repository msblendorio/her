"""AST — Auto Self-Training mode.

Turns every conversation with the frontier models (OpenAI Realtime + Claude
Opus) into training signal for a local model that learns to *be Samantha — for
you*. See ``future-features/AST_MODE_PLAN.md`` for the full design.

What is implemented here (zero-GPU, opt-in, privacy-first):

* **Phase 0 — data foundation:** opt-in capture of raw turns with secret
  redaction, retention and wipe (``capture.py`` + ``store.py`` + ``redact.py``).
* **Phase 1 — in-context personalization:** a measurable **Style Card**
  (``style.py``) and **few-shot retrieval** over the raw turns (``retrieval.py``),
  rebuilt by a nightly/after-N consolidation pass (``consolidate.py``) and
  injected into both teachers' prompts.

The later phases (distillation, LoRA training via MLX, the teacher/student
reasoning router, YouBench eval) are scaffolded as documented stubs in
``dataset.py`` / ``trainer.py`` / ``router.py`` / ``provider.py`` / ``eval.py``
and raise ``NotImplementedError`` until built.

The single entry point is the :data:`ast_manager` singleton in ``manager.py``.
"""
from __future__ import annotations

from .manager import ast_manager

__all__ = ["ast_manager"]
