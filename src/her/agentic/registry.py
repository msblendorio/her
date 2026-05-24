"""Decorator-based registry for agentic tools.

Decorating an async function with :func:`tool` registers it and derives the
JSON schema sent to OpenAI from the function signature, type hints, and
docstring. Adding a new tool then collapses to:

    @tool()
    async def my_tool(query: str, limit: int = 5) -> dict:
        '''One-line tool description that the model will see.

        Longer descriptions can span multiple lines and will be flattened
        into a single paragraph for the model.

        Args:
            query: What to search for.
            limit: Maximum number of results (default 5).
        '''
        ...

Required vs optional is driven by whether a parameter has a default. The
first paragraph of the docstring (everything before ``Args:``) becomes the
tool description. Each ``name: text`` entry under ``Args:`` becomes the
description of that parameter.

Supported type annotations:
    str, int, float, bool       -> primitive JSON-schema types
    list[T] (T as above)        -> array of T
    dict / dict[str, ...]       -> object (free-form)
    Literal["a", "b", ...]      -> string + enum
    Optional[T] / T | None      -> T (None handled by the default value)

Per-parameter overrides (min/max, custom enum, description tweak) go via
``params=`` on the decorator and are merged on top of the auto-derived
schema:

    @tool(params={"level": {"minimum": 0, "maximum": 100}})
    async def set_volume(level: int) -> str: ...

Other knobs:
    name=         override the tool name (defaults to the function name)
    description=  override the description (defaults to the docstring)
    safe=         False if the tool should require confirmation
"""
from __future__ import annotations

import inspect
import logging
import re
import types
import typing
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Literal, get_args, get_origin, get_type_hints

log = logging.getLogger(__name__)

ToolFunc = Callable[..., Awaitable[Any]]

TOOLS: list["Tool"] = []
_BY_NAME: dict[str, "Tool"] = {}


@dataclass
class Tool:
    """A registered tool. Produced by the :func:`tool` decorator."""

    name: str
    description: str
    parameters: dict
    func: ToolFunc
    safe: bool = True

    def to_openai_spec(self) -> dict:
        # GA Realtime tool shape: flat (no nested {"function": {...}}).
        return {
            "type": "function",
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }


_PY_TO_JSON: dict[type, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
}

_NONE_TYPE = type(None)


def _unwrap_optional(t: Any) -> Any:
    """Return X for ``Optional[X]`` / ``X | None``, else return ``t`` unchanged."""
    origin = get_origin(t)
    if origin is typing.Union or origin is types.UnionType:
        args = [a for a in get_args(t) if a is not _NONE_TYPE]
        if len(args) == 1:
            return args[0]
        raise TypeError(
            f"Union types other than Optional[X] are not supported: {t!r}"
        )
    return t


def _type_to_schema(t: Any) -> dict:
    """Map a Python type annotation to a JSON-schema fragment."""
    t = _unwrap_optional(t)
    origin = get_origin(t)

    if origin is Literal:
        values = list(get_args(t))
        if not values:
            raise TypeError("Literal[] needs at least one value")
        head_type = type(values[0])
        if not all(type(v) is head_type for v in values):
            raise TypeError(f"Literal with mixed types is not supported: {values!r}")
        json_type = _PY_TO_JSON.get(head_type)
        if json_type is None:
            raise TypeError(f"Literal with unsupported value type {head_type}: {values!r}")
        return {"type": json_type, "enum": list(values)}

    if origin in (list, typing.List):  # noqa: UP006 (typing.List is a runtime check)
        item_args = get_args(t)
        if not item_args:
            return {"type": "array"}
        return {"type": "array", "items": _type_to_schema(item_args[0])}

    if origin in (dict, typing.Dict):  # noqa: UP006
        return {"type": "object"}

    if t in _PY_TO_JSON:
        return {"type": _PY_TO_JSON[t]}

    raise TypeError(f"Cannot map type to JSON schema: {t!r}")


_ARGS_HEADER = re.compile(r"^(Args|Arguments|Parameters|Params):\s*$", re.MULTILINE)
_ARG_LINE = re.compile(r"^(?P<indent>[ \t]+)(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*:\s*(?P<desc>.*)$")
_STOP_HEADER = re.compile(r"^(Returns?|Raises|Yields|Examples?|Note|Notes|See Also):\s*$")


def _flatten(text: str) -> str:
    """Collapse all runs of whitespace in ``text`` to a single space."""
    return " ".join(text.split())


def _parse_docstring(doc: str | None) -> tuple[str, dict[str, str]]:
    """Return ``(description, {param: description})`` from a Google-style docstring.

    Description = the prose before ``Args:``. Multi-line is flattened to a
    single paragraph. Each ``Args:`` entry of the form ``name: text``
    becomes a param description; further-indented continuation lines are
    appended to the current param.
    """
    if not doc:
        return "", {}

    cleaned = inspect.cleandoc(doc)
    header = _ARGS_HEADER.search(cleaned)
    if header is None:
        return _flatten(cleaned), {}

    description = _flatten(cleaned[: header.start()])
    body = cleaned[header.end():]

    params: dict[str, str] = {}
    current: str | None = None
    base_indent: int | None = None

    for raw_line in body.splitlines():
        if not raw_line.strip():
            continue
        if _STOP_HEADER.match(raw_line.strip()):
            break
        match = _ARG_LINE.match(raw_line)
        if match:
            arg_indent = len(match.group("indent").expandtabs())
            if base_indent is None:
                base_indent = arg_indent
            if arg_indent == base_indent:
                current = match.group("name")
                params[current] = match.group("desc").strip()
                continue
        if current is not None:
            params[current] = _flatten(params[current] + " " + raw_line.strip())

    return description, params


def tool(
    *,
    name: str | None = None,
    description: str | None = None,
    params: dict[str, dict] | None = None,
    safe: bool = True,
) -> Callable[[ToolFunc], ToolFunc]:
    """Register an async function as an agentic tool.

    See the module docstring for the conventions. Raises ``TypeError`` /
    ``ValueError`` at decoration time on bad input — registration is fail-
    fast so misconfigured tools never reach the running session.
    """

    def decorator(func: ToolFunc) -> ToolFunc:
        if not inspect.iscoroutinefunction(func):
            raise TypeError(
                f"@tool requires an async function: {func.__module__}.{func.__name__} "
                f"is sync. Wrap blocking work with asyncio.to_thread()."
            )

        sig = inspect.signature(func)
        try:
            hints = get_type_hints(func)
        except Exception as e:
            raise TypeError(
                f"@tool {func.__name__}: cannot resolve type hints ({e})"
            ) from e

        doc_desc, doc_params = _parse_docstring(func.__doc__)
        final_desc = description if description is not None else doc_desc
        if not final_desc:
            raise ValueError(
                f"@tool {func.__name__}: no description. Add a docstring "
                f"or pass description= to the decorator."
            )

        overrides = params or {}
        unknown_overrides = set(overrides) - set(sig.parameters)
        if unknown_overrides:
            raise ValueError(
                f"@tool {func.__name__}: params override refers to unknown "
                f"parameter(s): {sorted(unknown_overrides)}"
            )

        properties: dict[str, dict] = {}
        required: list[str] = []

        for pname, param in sig.parameters.items():
            if param.kind in (
                inspect.Parameter.VAR_POSITIONAL,
                inspect.Parameter.VAR_KEYWORD,
            ):
                raise TypeError(
                    f"@tool {func.__name__}: *args / **kwargs are not supported "
                    f"(param {pname!r})"
                )
            if pname not in hints:
                raise TypeError(
                    f"@tool {func.__name__}: parameter {pname!r} has no type hint"
                )

            try:
                schema = _type_to_schema(hints[pname])
            except TypeError as e:
                raise TypeError(
                    f"@tool {func.__name__}: parameter {pname!r}: {e}"
                ) from e

            if pname in doc_params:
                schema["description"] = doc_params[pname]
            if pname in overrides:
                schema = {**schema, **overrides[pname]}

            properties[pname] = schema
            if param.default is inspect.Parameter.empty:
                required.append(pname)

        tool_name = name or func.__name__
        if tool_name in _BY_NAME:
            existing = _BY_NAME[tool_name]
            raise ValueError(
                f"@tool: duplicate name {tool_name!r} "
                f"(already registered by {existing.func.__module__}.{existing.func.__name__})"
            )

        parameters_schema = {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        }

        registered = Tool(
            name=tool_name,
            description=final_desc,
            parameters=parameters_schema,
            func=func,
            safe=safe,
        )
        TOOLS.append(registered)
        _BY_NAME[tool_name] = registered
        log.debug("registered tool %s (%d param(s))", tool_name, len(properties))
        return func

    return decorator


def by_name(name: str) -> Tool | None:
    return _BY_NAME.get(name)


def openai_specs() -> list[dict]:
    return [t.to_openai_spec() for t in TOOLS]


def clear_registry() -> None:
    """Reset the registry. Intended for tests only."""
    TOOLS.clear()
    _BY_NAME.clear()
