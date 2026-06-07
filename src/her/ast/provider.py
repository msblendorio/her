"""Phase 2/4 — local student serving + adapter library. SCAFFOLD.

Serves the fine-tuned local model through MLX behind the same tool-call
interface as the teachers, with a hot-swappable library of composable LoRA
adapters (persona + skills, S-LoRA/LoRAX style). This is what lets the
``router`` route a request to the student transparently.

Not implemented yet — see future-features/AST_MODE_PLAN.md §6.4 / §13.5.
"""
from __future__ import annotations


class LocalStudent:
    """Inference wrapper around the local fine-tuned model + adapter library."""

    def available(self) -> bool:
        return False

    async def respond(self, messages: list[dict], **kwargs) -> str:
        raise NotImplementedError(
            "AST local student serving is a Phase 2 feature — see AST_MODE_PLAN.md §13.5."
        )

    def load_adapter(self, name: str, version: str | None = None) -> None:
        raise NotImplementedError(
            "AST adapter library (hot-swap) is a Phase 2+ feature — see AST_MODE_PLAN.md §6.4."
        )
