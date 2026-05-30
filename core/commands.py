"""Slash-command registry — user-typed ``/command`` handlers.

Commands are registered via ``@register_command()`` and discovered from
Python modules in tiered ``cmd/`` directories (core + skills).  Distinct
from tools (agent-invoked) and leader chords (keyboard-driven menu).

Each command handler is an async callable ``(app, args: str) → Any``.
"""

from __future__ import annotations

import importlib.util
import os
from dataclasses import dataclass
from typing import Any, Callable, Coroutine


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------


@dataclass
class Command:
    """A registered slash command."""

    name: str
    description: str
    handler: Callable[[Any, str], Coroutine[Any, Any, Any]]


# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_commands: dict[str, Command] = {}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def register_command(
    *, name: str, description: str
) -> Callable[
    [Callable[[Any, str], Coroutine[Any, Any, Any]]],
    Callable[[Any, str], Coroutine[Any, Any, Any]],
]:
    """Decorator that registers an async function as a slash command.

    Example::

        @register_command(name="clear", description="Clear the chat")
        async def clear(app, args: str) -> None:
            ...
    """

    def decorator(
        fn: Callable[[Any, str], Coroutine[Any, Any, Any]],
    ) -> Callable[[Any, str], Coroutine[Any, Any, Any]]:
        if name in _commands:
            raise ValueError(
                f"Command '{name}' is already registered. "
                f"Use reset_commands() to clear the registry first."
            )
        _commands[name] = Command(name=name, description=description, handler=fn)
        return fn

    return decorator


def get_commands() -> dict[str, Command]:
    """Return all registered commands as a ``{name: Command}`` dict."""
    return dict(_commands)


def list_commands() -> list[str]:
    """Return sorted list of registered command names."""
    return sorted(_commands.keys())


async def execute_command(name: str, app: Any, args: str) -> Any:
    """Look up a command by *name* and call its handler with *(app, args)*.

    Raises
    ------
    KeyError
        If *name* is not registered.
    """
    try:
        cmd = _commands[name]
    except KeyError:
        raise KeyError(f"Command '{name}' is not registered.")
    return await cmd.handler(app, args)


def load_commands_from_paths(paths: list[str]) -> None:
    """Import every ``.py`` file (except ``__init__.py``) in each *path*,
    triggering ``@register_command()`` decorators at import time.

    Directories that don't exist are silently skipped.
    """
    for dir_path in paths:
        if not os.path.isdir(dir_path):
            continue
        try:
            entries = sorted(os.listdir(dir_path))
        except OSError:
            continue
        for entry in entries:
            if not entry.endswith(".py") or entry.startswith("_"):
                continue
            mod_path = os.path.join(dir_path, entry)
            mod_name = entry[:-3]  # strip .py
            spec = importlib.util.spec_from_file_location(
                f"workspace.cmd.{mod_name}", mod_path
            )
            if spec is None or spec.loader is None:
                continue
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)


def reset_commands() -> None:
    """Clear all registered commands (test isolation)."""
    _commands.clear()
