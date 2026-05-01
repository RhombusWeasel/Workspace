"""Cody event system — single-envelope message bus for skill-to-app communication.

Skills and components communicate with the app by posting :class:`CodyEvent`
messages.  Handlers are registered via the ``@register_handler(...)``
decorator — the same self-registration pattern used by ``@register_tool()``.

TuiApp needs exactly **one** handler, forever::

    def on_cody_event(self, msg: CodyEvent) -> None:
        dispatch(msg, self.context)

Every new skill or feature adds handlers via the decorator; the app file
never grows.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from textual.message import Message

if TYPE_CHECKING:
    from context import AppContext

# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_handler_registry: dict[str, list] = {}
"""event_type → list of callable(data: dict, ctx: AppContext)"""


# ---------------------------------------------------------------------------
# Message
# ---------------------------------------------------------------------------


class CodyEvent(Message):
    """Single-envelope message posted to communicate with the app.

    Example::

        self.post_message(CodyEvent("analysis.complete", {"count": 5}))
    """

    namespace = "cody"

    def __init__(self, event_type: str, data: dict[str, Any] | None = None) -> None:
        super().__init__()
        self.event_type: str = event_type
        self.data: dict[str, Any] = data or {}


# ---------------------------------------------------------------------------
# Decorator
# ---------------------------------------------------------------------------


def register_handler(event_type: str):
    """Register the decorated function as a handler for *event_type*.

    Usage::

        @register_handler("analysis.complete")
        def on_analysis_complete(data: dict, ctx: AppContext) -> None:
            ...
    """

    def decorator(fn):
        _handler_registry.setdefault(event_type, []).append(fn)
        return fn

    return decorator


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


def dispatch(event: CodyEvent, ctx: AppContext) -> None:
    """Call every handler registered for *event.event_type*."""
    for handler in _handler_registry.get(event.event_type, []):
        handler(event.data, ctx)


# ---------------------------------------------------------------------------
# Test isolation
# ---------------------------------------------------------------------------


def reset_handlers() -> None:
    """Clear all registered handlers.

    Call this between tests to prevent cross-test pollution.
    """
    _handler_registry.clear()
