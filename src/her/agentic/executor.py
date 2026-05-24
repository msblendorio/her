"""Executes one tool call coming from the Realtime model.

Returns the JSON-serializable payload that will be sent back to the model as
the function_call_output.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from ..core.event_bus import bus
from .tools import by_name

log = logging.getLogger(__name__)


def _trim(value: Any, limit: int = 400) -> Any:
    if isinstance(value, str) and len(value) > limit:
        return value[:limit] + "…"
    return value


async def execute_tool_call(call_id: str, name: str, raw_args: str) -> dict:
    tool = by_name(name)
    if tool is None:
        result = {"ok": False, "error": f"unknown tool: {name}"}
        bus.publish("agentic.tool_call", {"call_id": call_id, "name": name, "args": raw_args, "result": result})
        return result

    try:
        args = json.loads(raw_args) if raw_args else {}
        if not isinstance(args, dict):
            raise ValueError("arguments must be a JSON object")
    except Exception as e:
        result = {"ok": False, "error": f"bad arguments: {e}"}
        bus.publish("agentic.tool_call", {"call_id": call_id, "name": name, "args": raw_args, "result": result})
        return result

    log.info("agentic: %s(%s)", name, args)
    try:
        out = await tool.func(**args)
        result = {"ok": True, "result": _trim(out)}
    except Exception as e:
        log.exception("tool failed: %s", name)
        result = {"ok": False, "error": str(e)}

    bus.publish("agentic.tool_call", {"call_id": call_id, "name": name, "args": args, "result": result})
    return result
