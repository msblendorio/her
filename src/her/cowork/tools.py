"""Voice tools for Cowork: status, skill listing/authoring, task delegation.

Registered with the agentic registry on import. All four degrade gracefully
when no Anthropic credential is configured — they return an actionable string
the model can read back instead of raising.
"""
from __future__ import annotations

import asyncio
import logging

from ..agentic.registry import tool
from ..core.event_bus import bus
from .client import client
from .skills_store import skill_store

log = logging.getLogger(__name__)


@tool()
async def cowork_status() -> dict:
    """Report whether the Cowork/Claude connection is ready. Use this when the
    user asks if Cowork is set up, why a Cowork action failed, or which
    Anthropic credentials are active.

    Returns a dict with ``configured`` (bool), ``credential`` ("api_key" |
    "subscription" | "none"), and ``skill_count`` (installed Cowork skills).
    """
    skills = await asyncio.to_thread(skill_store.list_skills)
    return {
        "configured": client.is_configured(),
        "credential": client.credential_kind(),
        "skill_count": len(skills),
    }


@tool()
async def list_cowork_skills() -> list[dict]:
    """List the Agent Skills installed for Cowork / Claude Code (read from
    ~/.claude/skills). Each entry has slug, name, and description. Call this
    when the user asks what Cowork skills exist or before creating a new one.
    """
    return await asyncio.to_thread(skill_store.list_skills)


@tool(safe=False)
async def create_cowork_skill(name: str, description: str, instructions: str = "") -> str:
    """Author a new Agent Skill for Cowork and install it under ~/.claude/skills
    so Claude Cowork and Claude Code can use it. Call this when the user asks to
    create/teach a new Cowork skill (e.g. "crea una skill per Cowork che…",
    "make a Cowork skill that…"). Claude writes a well-formed SKILL.md from the
    intent.

    Args:
        name: Human name/intent for the skill (becomes a kebab-case slug).
        description: One-line summary of when the skill should be used.
        instructions: What the skill should do and how — the more concrete, the
            better the generated SKILL.md.
    """
    name = (name or "").strip()
    if not name:
        raise RuntimeError("a skill name is required")
    if not client.is_configured():
        return (
            "Cowork is not connected yet — set an Anthropic API key or a Claude "
            "Pro/Max subscription token first, then I can author the skill."
        )
    spec = await client.author_skill(name, description, instructions or description or name)
    slug = await asyncio.to_thread(
        skill_store.write_skill, spec["name"], spec["description"], spec["body"]
    )
    bus.publish("cowork.skill_created", {"slug": slug})
    return (
        f"Created Cowork skill '{slug}': {spec['description'] or spec['name']}. "
        f"It's now available in Cowork and Claude Code."
    )


@tool(safe=False)
async def run_cowork_task(task: str, context: str = "") -> str:
    """Delegate an open-ended knowledge-work task to Claude (the Cowork engine)
    and return the result. Use this for multi-step requests that go beyond a
    quick spoken answer — drafting, analysis, planning, research synthesis,
    structured reasoning (e.g. "chiedi a Cowork di…", "have Cowork draft…").
    For simple chit-chat or quick facts, answer directly instead.

    Args:
        task: The task to perform, phrased as a clear instruction.
        context: Optional extra context (notes, prior decisions) to ground the
            task.
    """
    task = (task or "").strip()
    if not task:
        raise RuntimeError("a task description is required")
    if not client.is_configured():
        return (
            "I can't reach Cowork yet — add an Anthropic API key or a Claude "
            "Pro/Max subscription token and I'll handle the task."
        )
    bus.publish("cowork.task_started", {"task": task[:120]})
    result = await client.run_task(task, context)
    return result or "Cowork returned no output."
