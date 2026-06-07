"""Secret redaction for captured raw turns.

Run over every piece of text *before* it is written to disk (see
``capture.py``). The goal is not perfect DLP — it is to keep obvious
high-risk secrets (API keys, bearer tokens, passwords, card numbers) out of
the training data the user opted to keep locally. Better to over-redact: a
``[redacted]`` in a training example is harmless, a leaked key is not.
"""
from __future__ import annotations

import re

_PLACEHOLDER = "[redacted]"

# Each pattern matches a secret-shaped token. Order doesn't matter — they're
# applied in sequence. Kept deliberately conservative-but-broad.
_PATTERNS: tuple[re.Pattern[str], ...] = (
    # Anthropic keys / OAuth tokens: sk-ant-..., sk-ant-oat...
    re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{8,}"),
    # OpenAI-style keys: sk-..., plus project/service variants sk-proj-...
    re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}"),
    # GitHub tokens (ghp_, gho_, ghu_, ghs_, ghr_), Slack (xox.-), Google (AIza)
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}"),
    re.compile(r"\bAIza[A-Za-z0-9_\-]{20,}"),
    # AWS access key ids.
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    # Bearer tokens in an Authorization header style.
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{12,}"),
    # Credit-card-shaped 13-19 digit runs (optionally separated by spaces/dashes).
    re.compile(r"\b(?:\d[ -]?){13,19}\b"),
)

# Labelled secrets — keep the label, replace only the value. Handles both the
# code form ("password: x", "pwd=x") and the natural-language form the user
# actually types out loud ("la mia password è hunter2", "my password is x",
# "mein Passwort ist x"). The separator is either ``:``/``=`` or a spaced verb
# (is/are/è/é/sono/est/ist/sind), so we don't over-match unrelated prose.
_LABELLED = re.compile(
    r"(?i)\b(password|passwort|passwd|pwd|secret|secreto|contrase[nñ]a|"
    r"api[_-]?key|token|pin|otp)\b"
    r"(\s*[:=]\s*|\s+(?:is|are|è|é|es|sono|est|ist|sind|son)\s+)"
    r"(\S+)"
)


def redact(text: str) -> str:
    """Return ``text`` with obvious secrets replaced by ``[redacted]``."""
    if not text:
        return text
    out = text
    # Labelled secrets first, so we preserve the label ("password: [redacted]").
    out = _LABELLED.sub(lambda m: f"{m.group(1)}{m.group(2)}{_PLACEHOLDER}", out)
    for pat in _PATTERNS:
        out = pat.sub(_PLACEHOLDER, out)
    return out
