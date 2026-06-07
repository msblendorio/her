"""Phase 3 — the Reasoning Router (teacher ↔ student). SCAFFOLD.

Decides, per request, who answers — frontier teacher vs. local student — based
on confidence, risk, latency, cost and network availability. Starts fully
conservative (teachers only; student in shadow), then lets the student earn
low-risk/high-confidence traffic as it passes YouBench, always with automatic
fallback to the teacher when confidence is low.

Not implemented yet — see future-features/AST_MODE_PLAN.md §6.3 (policy D3:
conservative).
"""
from __future__ import annotations

from ..config import settings


def route(request: dict) -> str:
    """Return which engine should serve the request: "teacher" | "student".

    Until Phases 2-3 land this always returns "teacher" — the student is never
    on the live path — which is the documented conservative default (D3)."""
    # Conservative invariant: with no trained/evaluated student, always teacher.
    _ = settings.ast_router_policy
    return "teacher"
