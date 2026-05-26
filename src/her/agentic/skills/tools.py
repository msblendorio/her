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
from .recorder import slugify
from .runtime import recorder, store

log = logging.getLogger(__name__)


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
    name, description, summary, created_at, and event_count.
    """
    return await asyncio.to_thread(store.list_skills)
