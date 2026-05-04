"""Tool registry — decorator-based self-registration for agent-callable tools.

Tools are plain Python functions registered via ``@register_tool()`` at
import time.  The registry exposes them as JSON Schema definitions suitable
for passing to ``BaseProvider.chat()`` / ``stream_chat()``.

Tag-based grouping, enable/disable (per-tool and per-group), and a
``reset()`` for test isolation are all provided.

This module intentionally uses module-level globals rather than a class
wrapper — the decorator pattern is the backbone of skill extensibility
(see design document § 6.1).

Async + context injection
--------------------------
* :func:`execute_tool` is async — tools can be ``async def``.
* Tools that declare a ``ctx`` parameter receive the :class:`AppContext`
  when executed.  This lets tools push confirmation modals, read config,
  and access the working directory for path validation.
"""

from __future__ import annotations

import inspect
from typing import Any, Callable

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from context import AppContext


# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

# _tools:  name → (callable, tags, description, parameters)
_tools: dict[str, tuple[Callable[..., Any], list[str], str, dict[str, Any]]] = {}

# _disabled_tools:  set of individually-disabled tool names
_disabled_tools: set[str] = set()

# _disabled_groups:  set of disabled tag groups
_disabled_groups: set[str] = set()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def register_tool(
    *,
    name: str,
    tags: list[str] | None = None,
    description: str,
    parameters: dict[str, Any],
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator that registers a function as an agent-callable tool.

    Parameters
    ----------
    name:
        Unique name for the tool.  Must not already be registered.
    tags:
        Optional tag-list for grouping (e.g. ``["system"]``, ``["skills"]``).
        Defaults to an empty list.
    description:
        Human-readable description injected into the JSON Schema sent to the
        LLM provider.
    parameters:
        JSON Schema ``parameters`` object describing the tool's input shape.
    """

    tags = list(tags) if tags else []

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        if name in _tools:
            raise ValueError(
                f"Tool '{name}' is already registered. "
                f"Use reset() to clear the registry first."
            )
        _tools[name] = (fn, tags, description, parameters)
        return fn

    return decorator


def get_tools(
    tags: str | list[str] | None = None,
) -> list[dict[str, Any]]:
    """Return enabled tools as JSON Schema function-definition dicts.

    Parameters
    ----------
    tags:
        Optional filter.  When a single string, only tools tagged with it
        are returned.  When a list, tools matching **any** tag are returned
        (union).  When ``None``, all enabled tools are returned.
    """
    # Normalise tag filter to a set (None means "match all").
    tag_set: set[str] | None
    if tags is None:
        tag_set = None
    elif isinstance(tags, str):
        tag_set = {tags}
    else:
        tag_set = set(tags)

    result: list[dict[str, Any]] = []
    for name, (fn, tool_tags, desc, params) in _tools.items():
        # --- visibility checks ---
        if name in _disabled_tools:
            continue
        if any(tag in _disabled_groups for tag in tool_tags):
            continue
        if tag_set is not None and not tag_set.intersection(tool_tags):
            continue

        result.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": desc,
                    "parameters": params,
                },
            }
        )
    return result


def execute_tool(name: str, args: dict[str, Any], ctx: AppContext | None = None) -> Any:
    """Look up a tool by *name* and call it with **args.

    Tools may be synchronous or ``async def`` — this function handles
    both.  If the tool's signature includes a ``ctx`` parameter, the
    supplied *ctx* is injected automatically.

    Raises
    ------
    KeyError
        If *name* is not registered.
    """
    try:
        fn, _tags, _desc, _params = _tools[name]
    except KeyError:
        raise KeyError(f"Tool '{name}' is not registered.")

    # Inspect the function signature to optionally inject ctx.
    sig = inspect.signature(fn)
    call_args = dict(args)
    if "ctx" in sig.parameters:
        call_args["ctx"] = ctx

    result = fn(**call_args)
    if inspect.iscoroutine(result):
        return result  # caller must await
    return result


def disable_tool(name: str) -> None:
    """Hide *name* from ``get_tools()`` output.

    Does **not** prevent ``execute_tool()`` from calling the function.

    Raises
    ------
    KeyError
        If *name* is not registered.
    """
    if name not in _tools:
        raise KeyError(f"Tool '{name}' is not registered.")
    _disabled_tools.add(name)


def enable_tool(name: str) -> None:
    """Restore *name* to ``get_tools()`` output.

    Raises
    ------
    KeyError
        If *name* is not registered.
    """
    if name not in _tools:
        raise KeyError(f"Tool '{name}' is not registered.")
    _disabled_tools.discard(name)


def disable_group(tag: str) -> None:
    """Hide all tools tagged with *tag* from ``get_tools()`` output.

    Safe to call for tags that aren't assigned to any tools (no-op).
    """
    _disabled_groups.add(tag)


def enable_group(tag: str) -> None:
    """Restore all tools tagged with *tag* to ``get_tools()`` output.

    Safe to call for tags that aren't disabled (no-op).
    """
    _disabled_groups.discard(tag)


def reset() -> None:
    """Clear all registered tools, disabled state, and disabled groups.

    Intended for test isolation.  After calling this the registry is
    completely empty and ready for fresh registrations.
    """
    _tools.clear()
    _disabled_tools.clear()
    _disabled_groups.clear()
