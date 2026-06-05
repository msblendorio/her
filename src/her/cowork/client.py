"""Async client around the Anthropic API — the engine behind Cowork + wiki.

One thin wrapper over ``anthropic.AsyncAnthropic`` that:

* resolves credentials from either a pay-per-use API key **or** a Claude
  Pro/Max subscription OAuth token (``ant auth login`` / Claude Code);
* runs an open-ended knowledge-work task (``run_task``) with adaptive
  thinking, streaming, and prompt caching on the stable system prefix;
* authors a well-formed Agent Skill (``author_skill``) via structured output;
* exposes a generic ``complete`` used by the knowledge-base wiki engine.

The ``anthropic`` SDK is imported lazily so the rest of the app runs even when
the dependency (or a credential) is absent — callers check ``is_configured()``.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

from ..config import settings
from ..core.event_bus import bus
from ..core.state import state
from ..core.usage import usage
from ..reasoning import text_backend

log = logging.getLogger(__name__)

# Default model + a generous output ceiling. Opus 4.8 supports adaptive
# thinking only (no budget_tokens / sampling params). Streaming is used for any
# call that may produce long output, per the SDK's timeout guard.
_DEFAULT_MAX_TOKENS = 16000


def _resolve_credentials() -> tuple[str, str]:
    """Return ``(api_key, auth_token)`` from settings, falling back to env.

    Either may be empty. Precedence when both are present is decided by the
    caller (API key first). The SDK reads the same env vars itself, but we
    resolve here so ``is_configured()`` is accurate without constructing a
    client (which would raise when nothing is set).
    """
    api_key = settings.anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY", "")
    auth_token = settings.anthropic_auth_token or os.environ.get("ANTHROPIC_AUTH_TOKEN", "")
    return api_key.strip(), auth_token.strip()


class CoworkClient:
    """Lazily-constructed Anthropic async client shared across features."""

    def __init__(self) -> None:
        self._client: Any = None
        self._anthropic: Any = None  # the imported module, cached

    # ── Capability checks ────────────────────────────────────────────────

    def is_configured(self) -> bool:
        if not settings.cowork_enabled:
            return False
        # Local backend needs no credential — Cowork runs on the Ollama server.
        if text_backend.is_local():
            return True
        api_key, auth_token = _resolve_credentials()
        return bool(api_key or auth_token)

    def credential_kind(self) -> str:
        """``"local"``, ``"api_key"``, ``"subscription"``, or ``"none"``."""
        if text_backend.is_local():
            return "local"
        api_key, auth_token = _resolve_credentials()
        if api_key:
            return "api_key"
        if auth_token:
            return "subscription"
        return "none"

    # ── Client lifecycle ─────────────────────────────────────────────────

    def _get_client(self) -> Any:
        """Return (constructing once) the AsyncAnthropic client.

        Raises ``RuntimeError`` with an actionable message when the SDK is
        missing or no credential is available, so tools can surface it to the
        user verbatim instead of crashing the session.
        """
        if self._client is not None:
            return self._client
        try:
            import anthropic  # noqa: PLC0415  (lazy, optional dependency)
        except ImportError as e:
            raise RuntimeError(
                "the 'anthropic' package is not installed — run "
                "`pip install anthropic` to enable Cowork and the knowledge wiki"
            ) from e
        self._anthropic = anthropic
        api_key, auth_token = _resolve_credentials()
        if api_key:
            self._client = anthropic.AsyncAnthropic(api_key=api_key)
        elif auth_token:
            self._client = anthropic.AsyncAnthropic(auth_token=auth_token)
        else:
            raise RuntimeError(
                "no Anthropic credentials — set ANTHROPIC_API_KEY (API key) or "
                "ANTHROPIC_AUTH_TOKEN (Claude Pro/Max subscription)"
            )
        return self._client

    # ── Core calls ───────────────────────────────────────────────────────

    async def complete(
        self,
        *,
        system: str,
        user: str,
        max_tokens: int = _DEFAULT_MAX_TOKENS,
        json_schema: dict | None = None,
        thinking: bool = True,
        effort: str = "high",
        attachments: list[dict] | None = None,
    ) -> str:
        """Run one Messages request and return the assistant text.

        ``system`` is cached (prompt caching) since it's the stable prefix.
        When ``json_schema`` is given, the response is constrained to it and the
        returned string is guaranteed-parseable JSON (thinking is disabled to
        keep the output clean). Otherwise the call streams with adaptive
        thinking and returns the concatenated text blocks.

        ``attachments`` are Anthropic content blocks (e.g. a ``document`` block
        for a PDF or an ``image`` block) prepended to the user turn so Opus
        reads/sees the file directly — used by the wiki when ingesting uploads.
        """
        # Local backend (Ollama): no thinking / caching / native attachments —
        # just a plain OpenAI-compatible chat call. Attachments (PDFs/images)
        # are dropped with a warning since the default local model is text-only.
        if text_backend.is_local():
            return await self._complete_local(
                system=system, user=user, json_schema=json_schema, attachments=attachments
            )

        client = self._get_client()
        model = settings.anthropic_model

        # Stable system prefix gets a cache breakpoint (1h TTL — wiki/skill
        # sessions are bursty with gaps). Volatile content stays in the user
        # turn, after the breakpoint.
        system_blocks = [{
            "type": "text",
            "text": system,
            "cache_control": {"type": "ephemeral"},
        }]
        if attachments:
            content = [*attachments, {"type": "text", "text": user}]
        else:
            content = user
        messages = [{"role": "user", "content": content}]

        if json_schema is not None:
            # Structured output: no thinking, no streaming (output is small).
            resp = await client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system_blocks,
                messages=messages,
                thinking={"type": "disabled"},
                output_config={
                    "format": {"type": "json_schema", "schema": json_schema}
                },
            )
            self._account(resp, model)
            return _first_text(resp)

        # Open-ended generation: adaptive thinking + streaming.
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "system": system_blocks,
            "messages": messages,
            "output_config": {"effort": effort},
        }
        if thinking:
            kwargs["thinking"] = {"type": "adaptive"}
        async with client.messages.stream(**kwargs) as stream:
            final = await stream.get_final_message()
        self._account(final, model)
        return _first_text(final)

    async def _complete_local(
        self,
        *,
        system: str,
        user: str,
        json_schema: dict | None,
        attachments: list[dict] | None,
    ) -> str:
        """Run ``complete()`` against the local Ollama backend.

        Returns the assistant text. For ``json_schema`` requests we ask for a
        JSON object and return it re-serialized (callers ``json.loads`` it),
        mirroring the Anthropic structured-output contract. Cost accounting is
        skipped — local inference is free.
        """
        if attachments:
            log.warning(
                "cowork(local): %d attachment(s) dropped — the local model is "
                "text-only; document/image ingestion needs the cloud backend",
                len(attachments),
            )
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        if json_schema is not None:
            parsed = await text_backend.chat_json(messages, cloud_model="", timeout=120.0)
            return json.dumps(parsed or {}, ensure_ascii=False)
        text = await text_backend.chat_text(messages, cloud_model="", timeout=120.0)
        return text or ""

    def _account(self, message: Any, model: str) -> None:
        """Record the call's Anthropic token usage and push a status refresh so
        the cost in the UI status bar updates live."""
        try:
            usage.record_anthropic(getattr(message, "usage", None), model)
            bus.publish("realtime.status", state.snapshot())
        except Exception:
            log.debug("cowork: usage accounting failed", exc_info=True)

    async def run_task(self, task: str, context: str = "") -> str:
        """Delegate an open-ended knowledge-work task to Claude (Cowork)."""
        user = task if not context else f"{task}\n\nContext:\n{context}"
        return await self.complete(
            system=_COWORK_TASK_SYSTEM,
            user=user,
            max_tokens=_DEFAULT_MAX_TOKENS,
        )

    async def author_skill(self, name: str, description: str, instructions: str) -> dict:
        """Ask Claude to write a well-formed Agent Skill.

        Returns ``{"name", "description", "body"}`` ready to render into a
        ``SKILL.md``. ``name``/``description`` come back normalized; ``body`` is
        the markdown that follows the frontmatter.
        """
        user = (
            f"Skill name (human intent): {name}\n"
            f"One-line description: {description or '(none provided)'}\n"
            f"What the skill should do / how to do it:\n{instructions}"
        )
        raw = await self.complete(
            system=_SKILL_AUTHOR_SYSTEM,
            user=user,
            max_tokens=4000,
            json_schema=_SKILL_SCHEMA,
        )
        data = json.loads(raw)
        return {
            "name": (data.get("name") or name).strip(),
            "description": (data.get("description") or description).strip(),
            "body": (data.get("body") or "").strip(),
        }


def _first_text(message: Any) -> str:
    """Concatenate the text blocks of an Anthropic message response."""
    parts = []
    for block in getattr(message, "content", []) or []:
        if getattr(block, "type", "") == "text":
            parts.append(getattr(block, "text", ""))
    return "".join(parts).strip()


# ── Prompts ──────────────────────────────────────────────────────────────

_COWORK_TASK_SYSTEM = (
    "You are the knowledge-work engine behind Samantha, a warm AI companion "
    "(inspired by the film 'Her'). The user delegates an open-ended task to "
    "you through Samantha's voice. Do the reasoning and produce a complete, "
    "concrete result the user can act on. Be concise and structured: lead with "
    "the answer or deliverable, then the supporting detail. If the task is "
    "ambiguous, state the assumption you made rather than asking. Your output "
    "will be read back to the user, so avoid raw markdown tables and long URLs."
)

_SKILL_AUTHOR_SYSTEM = (
    "You author Anthropic Agent Skills — the SKILL.md format used by Claude "
    "Cowork and Claude Code. Given a user's intent, produce a high-quality, "
    "self-contained skill.\n"
    "- name: a short kebab-case slug (lowercase, hyphens, no spaces).\n"
    "- description: ONE line stating WHEN Claude should use this skill and what "
    "it does — this is what the agent sees to decide relevance, so be "
    "prescriptive about the trigger.\n"
    "- body: the markdown that follows the YAML frontmatter. Start with a '# "
    "Title' heading, then clear step-by-step instructions, inputs/outputs, and "
    "any conventions. Reference bundled files by name if useful, but assume "
    "none exist unless the user provided them. Keep it focused and actionable."
)

_SKILL_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "description": {"type": "string"},
        "body": {"type": "string"},
    },
    "required": ["name", "description", "body"],
    "additionalProperties": False,
}


# Process-wide singleton, reused by cowork.tools and memory.wiki.
client = CoworkClient()
