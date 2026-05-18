"""Terminal passthrough key registry.

Keys registered here will never be consumed by the terminal widget,
allowing the app to handle them even while the terminal has focus.

Modules that define key bindings (workspace navigation, app shortcuts,
etc.) register the same keys here so the terminal knows to let them
through.
"""

from __future__ import annotations

_terminal_passthrough_keys: set[str] = set()


def register_terminal_passthrough(keys: set[str]) -> None:
    """Register keys that should pass through the terminal to the app.

    Call this at module level, next to the module's ``BINDINGS``.
    """
    _terminal_passthrough_keys.update(keys)


def get_terminal_passthrough_keys() -> frozenset[str]:
    """Return all registered passthrough keys."""
    return frozenset(_terminal_passthrough_keys)


def reset_terminal_passthrough() -> None:
    """Clear all registered keys (test isolation)."""
    _terminal_passthrough_keys.clear()