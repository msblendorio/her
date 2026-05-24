"""Builds the 'what you remember' block that is appended to Samantha's
system instructions at the start of a new session.

Kept short on purpose: a long recall block bloats every turn's input tokens.
For each remembered session we emit:

    - [YYYY-MM-DD] textual summary
        · key fact 1
        · key fact 2
      visto: short visual summary
        · visual fact (one only)

The `visto:` sub-block is omitted entirely when the visual track is empty
(older sessions written before visual memory, or sessions with vision off).
"""
from __future__ import annotations

from ..i18n import recall_header, visual_recall_label
from .store import MemoryEntry

# Token budget: at most one visual fact per recalled session — anything more
# is redundant for the realtime prompt and just bloats every turn's input.
_MAX_VISUAL_FACTS = 1


def build_recall_block(entries: list[MemoryEntry], language: str = "it") -> str:
    if not entries:
        return ""
    lines = [recall_header(language)]
    v_label = visual_recall_label(language)
    for e in entries:
        date = e.timestamp[:10]  # YYYY-MM-DD
        lines.append(f"- [{date}] {e.summary}")
        for fact in e.key_facts:
            lines.append(f"    · {fact}")
        if e.visual_summary:
            lines.append(f"  {v_label} {e.visual_summary}")
            for vfact in e.visual_facts[:_MAX_VISUAL_FACTS]:
                lines.append(f"    · {vfact}")
    return "\n".join(lines)
