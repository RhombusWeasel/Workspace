"""Tool call formatting — renders LLM tool calls for display and persistence.

Provides helpers to format tool calls as markdown for the chat display
and to serialise them as JSON for database storage.
"""

from __future__ import annotations

import json
from typing import Any


def format_tool_call_display(name: str, arguments: dict[str, Any]) -> str:
    """Format a single tool call for the chat display.

    Returns a markdown-friendly string like::

        🔧 `read_file(path="foo.py")`

    Parameters
    ----------
    name:
        Tool name (e.g. ``"read_file"``).
    arguments:
        Tool arguments as a dict.
    """
    args_str = _format_args(arguments)
    return f"🔧 `{name}({args_str})`\n"


def format_tool_call_json(name: str, arguments: dict[str, Any]) -> str:
    """Serialise a tool call as JSON for database storage.

    Returns a JSON string like::

        {"name": "read_file", "arguments": {"path": "foo.py"}}

    This can be decoded by :meth:`DatabaseManager.reconstruct_history`
    when rebuilding LLM-consumable history from flat sections.
    """
    return json.dumps({"name": name, "arguments": arguments})


def format_tool_call_branch_label(name: str, arguments: dict[str, Any]) -> str:
    """Format a tool call for a tree branch collapsed label.

    Returns a Rich-markup string like::

        🔧 `read_file(path="foo.py")`

    Shows a short argument summary so the user can identify the
    call without expanding the branch.
    """
    args_str = _format_args(arguments)
    return f"\U0001f527 `{name}({args_str})`"


def format_tool_call_branch_label_expanded(name: str) -> str:
    """Format the expanded label for a tool call branch.

    Returns a Rich-markup string like::

        🔧 read_file

    When the branch is expanded, the detail leaf is visible so
    the label only needs the tool name.
    """
    return f"\U0001f527 {name}"


def format_tool_call_detail(name: str, arguments: dict[str, Any]) -> str:
    """Format tool call arguments as Markdown for the detail leaf.

    Returns a Markdown string with key-value pairs, one per line::

        **path**: `"foo.py"`
        **content**: `"Hello world"`

    Long values are truncated to 200 characters.
    """
    lines: list[str] = []
    for key, value in arguments.items():
        val_repr = repr(value)
        if len(val_repr) > 200:
            val_repr = val_repr[:197] + "..."
        lines.append(f"**{key}**: `{val_repr}`")
    return "\n".join(lines)


def _format_args(args: dict[str, Any]) -> str:
    """Render *args* as a compact ``key=value`` string for display."""
    items = [f"{k}={v!r}" for k, v in args.items()]
    return ", ".join(items)[:60]