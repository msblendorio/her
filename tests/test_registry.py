"""Unit tests for the agentic tool registry.

These tests use a clean registry per test (via ``clear_registry()``) so
they don't observe or pollute the real TOOLS list.
"""
from __future__ import annotations

from typing import Literal

import pytest

from her.agentic import registry
from her.agentic.registry import (
    _parse_docstring,
    _type_to_schema,
    by_name,
    clear_registry,
    openai_specs,
    tool,
)


@pytest.fixture(autouse=True)
def _clean_registry():
    clear_registry()
    yield
    clear_registry()


# ---------- _type_to_schema ----------------------------------------------


def test_type_to_schema_primitives():
    assert _type_to_schema(str) == {"type": "string"}
    assert _type_to_schema(int) == {"type": "integer"}
    assert _type_to_schema(float) == {"type": "number"}
    assert _type_to_schema(bool) == {"type": "boolean"}


def test_type_to_schema_list_of_strings():
    assert _type_to_schema(list[str]) == {
        "type": "array",
        "items": {"type": "string"},
    }


def test_type_to_schema_list_of_ints():
    assert _type_to_schema(list[int]) == {
        "type": "array",
        "items": {"type": "integer"},
    }


def test_type_to_schema_optional_unwraps():
    assert _type_to_schema(str | None) == {"type": "string"}
    assert _type_to_schema(list[str] | None) == {
        "type": "array",
        "items": {"type": "string"},
    }


def test_type_to_schema_literal_becomes_enum():
    schema = _type_to_schema(Literal["a", "b", "c"])
    assert schema == {"type": "string", "enum": ["a", "b", "c"]}


def test_type_to_schema_rejects_unsupported():
    with pytest.raises(TypeError):
        _type_to_schema(tuple)
    with pytest.raises(TypeError):
        _type_to_schema(set[str])


# ---------- _parse_docstring ---------------------------------------------


def test_parse_docstring_no_args_section():
    desc, params = _parse_docstring("Just a one-liner.")
    assert desc == "Just a one-liner."
    assert params == {}


def test_parse_docstring_flattens_paragraphs():
    desc, _ = _parse_docstring(
        """First line that
        spans across lines.

        Second paragraph here.
        """
    )
    assert desc == "First line that spans across lines. Second paragraph here."


def test_parse_docstring_args_section():
    desc, params = _parse_docstring(
        """Short description.

        Args:
            query: What to search for.
            limit: Max results.
        """
    )
    assert desc == "Short description."
    assert params == {"query": "What to search for.", "limit": "Max results."}


def test_parse_docstring_arg_continuation():
    _, params = _parse_docstring(
        """Desc.

        Args:
            query: A query that wraps
                across multiple lines.
            other: Single line.
        """
    )
    assert params["query"] == "A query that wraps across multiple lines."
    assert params["other"] == "Single line."


def test_parse_docstring_stops_at_returns():
    desc, params = _parse_docstring(
        """Desc.

        Args:
            query: A search query.

        Returns:
            The matching items.
        """
    )
    assert desc == "Desc."
    assert params == {"query": "A search query."}


# ---------- @tool decorator ----------------------------------------------


def test_tool_registers_minimal():
    @tool()
    async def echo(text: str) -> str:
        """Echo back the input."""
        return text

    assert by_name("echo") is not None
    spec = openai_specs()[0]
    assert spec == {
        "type": "function",
        "name": "echo",
        "description": "Echo back the input.",
        "parameters": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
            "additionalProperties": False,
        },
    }


def test_tool_required_vs_optional_from_defaults():
    @tool()
    async def search(query: str, limit: int = 5, verbose: bool = False) -> str:
        """Run a search."""
        return ""

    spec = by_name("search").parameters
    assert spec["required"] == ["query"]
    assert set(spec["properties"]) == {"query", "limit", "verbose"}


def test_tool_attaches_param_descriptions():
    @tool()
    async def echo(text: str, times: int = 1) -> str:
        """Repeat text.

        Args:
            text: The message.
            times: Repetitions (default 1).
        """
        return text * times

    props = by_name("echo").parameters["properties"]
    assert props["text"]["description"] == "The message."
    assert props["times"]["description"] == "Repetitions (default 1)."


def test_tool_params_override_merges():
    @tool(params={"level": {"minimum": 0, "maximum": 100}})
    async def set_vol(level: int) -> str:
        """Set volume.

        Args:
            level: 0 to 100.
        """
        return ""

    schema = by_name("set_vol").parameters["properties"]["level"]
    assert schema["type"] == "integer"
    assert schema["minimum"] == 0
    assert schema["maximum"] == 100
    assert schema["description"] == "0 to 100."


def test_tool_name_override():
    @tool(name="calendar_create_event")
    async def create_event(title: str) -> dict:
        """Create."""
        return {}

    assert by_name("calendar_create_event") is not None
    assert by_name("create_event") is None


def test_tool_safe_flag_default_and_override():
    @tool()
    async def a(x: str) -> str:
        """A."""
        return x

    @tool(safe=False)
    async def b(x: str) -> str:
        """B."""
        return x

    assert by_name("a").safe is True
    assert by_name("b").safe is False


def test_tool_rejects_sync_function():
    with pytest.raises(TypeError, match="async function"):
        @tool()
        def not_async(x: str) -> str:  # type: ignore[misc]
            """Sync."""
            return x


def test_tool_rejects_missing_type_hint():
    with pytest.raises(TypeError, match="no type hint"):
        @tool()
        async def missing(x) -> str:  # type: ignore[no-untyped-def]
            """Missing hint."""
            return x


def test_tool_rejects_missing_description():
    with pytest.raises(ValueError, match="no description"):
        @tool()
        async def no_doc(x: str) -> str:
            return x


def test_tool_rejects_duplicate_name():
    @tool()
    async def dup(x: str) -> str:
        """First."""
        return x

    with pytest.raises(ValueError, match="duplicate name"):
        @tool(name="dup")
        async def dup2(x: str) -> str:
            """Second."""
            return x


def test_tool_rejects_unknown_params_override():
    with pytest.raises(ValueError, match="unknown"):
        @tool(params={"nonexistent": {"minimum": 0}})
        async def something(real: int) -> str:
            """Doc.

            Args:
                real: A real param.
            """
            return ""


def test_tool_rejects_var_args():
    with pytest.raises(TypeError, match=r"\*args"):
        @tool()
        async def varargs(*args: str) -> str:
            """Doc."""
            return ""


def test_tool_call_through():
    @tool()
    async def adder(a: int, b: int = 0) -> int:
        """Add two ints.

        Args:
            a: First.
            b: Second.
        """
        return a + b

    import asyncio
    assert asyncio.run(by_name("adder").func(2, 3)) == 5


# ---------- Integration: all real tools register -------------------------


def test_all_real_tools_register_cleanly():
    """Smoke test: importing the agentic package registers every real tool."""
    # Reload the package so registrations land in our cleaned registry.
    import importlib

    import her.agentic

    importlib.reload(her.agentic.registry)  # type: ignore[attr-defined]
    clear_registry()
    # Reload domain modules so their @tool() decorators rebind to the fresh
    # registry instance.
    for mod_name in ("accessibility", "macos", "calendar", "email", "screen", "web"):
        importlib.reload(importlib.import_module(f"her.agentic.{mod_name}"))

    names = {t.name for t in registry.TOOLS}
    expected = {
        "open_app",
        "open_url",
        "focus_window",
        "list_running_apps",
        "take_screenshot",
        "set_volume",
        "run_shortcut",
        "type_text",
        "press_key",
        "browser_new_tab",
        "calendar_list_events",
        "calendar_search_events",
        "calendar_create_event",
        "email_list_unread",
        "email_search",
        "email_send",
        "look_at_screen",
        "read_screen",
        "web_search",
        "toggle_accessibility_mode",
    }
    missing = expected - names
    assert not missing, f"missing tools: {missing}"


def test_every_real_tool_has_well_formed_schema():
    """Every registered tool must have a syntactically valid OpenAI spec."""
    import importlib

    importlib.reload(registry)
    clear_registry()
    for mod_name in ("accessibility", "macos", "calendar", "email", "screen", "web"):
        importlib.reload(importlib.import_module(f"her.agentic.{mod_name}"))

    for t in registry.TOOLS:
        spec = t.to_openai_spec()
        assert spec["type"] == "function"
        assert spec["name"]
        assert spec["description"], f"{t.name} has empty description"
        params = spec["parameters"]
        assert params["type"] == "object"
        assert params["additionalProperties"] is False
        assert set(params["required"]).issubset(params["properties"]), (
            f"{t.name}: required keys not in properties"
        )
        # Every required param should *not* have a default in the underlying func.
        # And every property should have a type.
        for pname, pschema in params["properties"].items():
            assert "type" in pschema or "enum" in pschema, (
                f"{t.name}.{pname}: missing type/enum"
            )
