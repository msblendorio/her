"""Agentic tools for learning, listing, and executing user-taught skills.

The four tools registered here close the loop:

* ``start_learning_skill`` — begin capturing the user's clicks/shortcuts.
* ``stop_learning_skill`` — end the capture, ask the LLM to compile it
  into AppleScript, persist it.
* ``run_skill`` — execute a previously learned skill via ``osascript``.
* ``list_skills`` — enumerate what Samantha already knows.
"""
from __future__ import annotations

import asyncio
import logging

from ...core.event_bus import bus
from ..registry import tool
from .compiler import compile_to_applescript
from .compiler_text import forge_to_applescript
from .recorder import slugify
from .runtime import forge_session, recorder, store

log = logging.getLogger(__name__)


def _format_preview(name: str, summary: str, warnings: list[str]) -> str:
    """Human-readable proposal shown to the user before a forge is saved."""
    lines = [f"proposed skill '{name}': {summary or '(no summary)'}"]
    if warnings:
        lines.append("heads-up:")
        lines.extend(f"- {w}" for w in warnings)
    lines.append("say 'save' to keep it, or tell me what to change.")
    return "\n".join(lines)


@tool(safe=False)
async def start_learning_skill(name: str, description: str = "") -> str:
    """Begin recording the user's mouse clicks and keyboard shortcuts so
    they can be saved as a reusable skill. Call this whenever the user
    asks to teach or memorize an action (e.g. "Samantha, impara questa
    azione come 'manda mail al CEO'", "learn this as X", "memorizza
    questa procedura come X").

    AFTER calling this tool, STAY SILENT. Do not narrate, do not ask
    questions — let the user perform the action with their mouse and
    keyboard. Wait for them to say "done", "fatto", "salva", "stop", or
    similar, then call stop_learning_skill().

    Requires macOS Accessibility AND Screen Recording permissions for
    the parent process (each surfaces a one-time TCC dialog).

    Args:
        name: Short, descriptive name for the skill; used later to invoke
            it via run_skill(). Italian/English/etc. all fine.
        description: Optional one-line description of the goal (helps
            the compiler understand intent when the trace is ambiguous).
    """
    name = (name or "").strip()
    if not name:
        raise RuntimeError("skill name is required")
    if recorder.active:
        raise RuntimeError("a recording is already in progress — call stop_learning_skill first")
    await asyncio.to_thread(recorder.start, name, description)
    return f"recording skill '{name}' — perform the action, then say 'done'"


@tool(safe=False)
async def stop_learning_skill() -> str:
    """End the current skill recording, compile the trace into an
    AppleScript via the LLM, and save it. Call this when the user says
    "done", "fatto", "salva", "stop", or signals that they have finished
    demonstrating the action.

    Returns a short status string (success summary or failure reason).
    """
    if not recorder.active:
        return "no recording in progress"
    rec = await asyncio.to_thread(recorder.stop)
    if not rec.events:
        return f"recording '{rec.name}' had no captured events; nothing saved"
    result = await compile_to_applescript(rec)
    if result is None:
        return f"recording '{rec.name}' captured {len(rec.events)} event(s) but compilation failed; not saved"
    script, summary = result
    slug = await asyncio.to_thread(store.save_recording, rec, script, summary)
    # Tell the orchestrator to re-push the system prompt with the new
    # skill in the index so Samantha can invoke it immediately.
    bus.publish("skills.saved", {"slug": slug})
    return f"saved skill '{slug}' ({len(rec.events)} events): {summary or rec.description or rec.name}"


@tool(safe=False)
async def run_skill(name: str) -> str:
    """Execute a previously learned skill by name. Looks up the
    AppleScript on disk and runs it via osascript. Returns the script's
    stdout (or a brief error message on failure).

    Args:
        name: Skill name as taught (matched case-insensitively after
            normalizing whitespace).
    """
    slug = slugify(name)
    entry = await asyncio.to_thread(store.get, slug)
    if entry is None:
        known = [s["slug"] for s in await asyncio.to_thread(store.list_skills)]
        return f"no skill named '{name}' (known: {known or 'none'})"
    script_path = store.script_path(slug)
    if not script_path.exists():
        return f"skill '{slug}' has no script on disk"
    proc = await asyncio.create_subprocess_exec(
        "osascript", str(script_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=60.0)
    except asyncio.TimeoutError:
        proc.kill()
        return f"skill '{slug}' timed out after 60s"
    if proc.returncode != 0:
        msg = (err.decode(errors="replace").strip() or "osascript failed")
        return f"skill '{slug}' failed: {msg}"
    return out.decode(errors="replace").strip() or f"ran skill '{slug}'"


@tool()
async def list_skills() -> list[dict]:
    """List every skill Samantha has been taught. Each entry has slug,
    name, description, summary, created_at, origin, and (for demonstrated
    skills) event_count.
    """
    return await asyncio.to_thread(store.list_skills)


@tool(safe=False)
async def forge_skill(name: str, description: str) -> str:
    """Forge a new skill from the user's spoken DESCRIPTION — no
    demonstration. Use this when the user TELLS you what they want you to
    learn instead of showing you: "impara a fare X", "quando dico Y fai Z",
    "voglio insegnarti una cosa: ...", "learn to ...". (When they instead
    want to *demonstrate* by clicking, use start_learning_skill.)

    This does NOT save anything yet: it returns a PREVIEW of what the skill
    will do plus any caveats. ALWAYS read the preview back to the user and
    let them confirm. They save it by triggering confirm_forge (e.g. they
    say "save"/"salva"/"yes") or change it by calling forge_skill again with
    a refined description; discard_forge throws the proposal away.

    Args:
        name: Short, descriptive name used later to invoke the skill via
            run_skill(). Italian/English/etc. all fine.
        description: What the skill should do, in plain language.
    """
    name = (name or "").strip()
    if not name:
        raise RuntimeError("skill name is required")
    result = await forge_to_applescript(name, description)
    if result is None:
        forge_session.clear()
        return f"could not forge '{name}' from that description — try explaining it differently"
    forge_session.set(name, description, result)
    return _format_preview(name, result.summary, result.warnings)


@tool(safe=False)
async def confirm_forge() -> str:
    """Save the skill currently proposed by forge_skill. Call this when the
    user confirms the preview ("save", "salva", "yes", "ok keep it"). Fails
    gracefully if there is nothing pending.
    """
    pending = forge_session.pending
    if pending is None:
        return "nothing to save — forge a skill first"
    slug = await asyncio.to_thread(
        store.save_forged,
        pending.name,
        pending.description,
        pending.result.script,
        pending.result.summary,
    )
    forge_session.clear()
    # Re-push the system prompt so the new skill is immediately invocable,
    # exactly as stop_learning_skill does for demonstrated skills.
    bus.publish("skills.saved", {"slug": slug})
    return f"forged skill '{slug}': {pending.result.summary or pending.name}"


@tool(safe=False)
async def discard_forge() -> str:
    """Throw away the skill currently proposed by forge_skill without saving
    it. Call this when the user declines the preview ("no", "annulla",
    "scarta", "forget it").
    """
    if forge_session.pending is None:
        return "nothing to discard"
    name = forge_session.pending.name
    forge_session.clear()
    return f"discarded the proposed skill '{name}'"
