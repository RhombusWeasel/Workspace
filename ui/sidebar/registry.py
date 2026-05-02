"""Sidebar tab registry — decorator-based registration for sidebar panels.

Skills and core modules register their sidebar panels via the
``@register_sidebar_tab()`` decorator.  Tabs specify which side
they appear on (``"left"`` or ``"right"``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------


@dataclass
class SidebarTab:
    """Metadata for a registered sidebar tab."""

    name: str
    icon: str
    side: str
    widget_class: type


# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_sidebar_tabs: dict[str, SidebarTab] = {}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def register_sidebar_tab(
    *, name: str, icon: str, side: str = "left"
):
    """Decorator that registers a Widget subclass as a sidebar tab.

    Example::

        @register_sidebar_tab(name="vault", icon="\\ueb97", side="left")
        class VaultPanel(Widget):
            ...

    Parameters
    ----------
    name:
        Unique tab name.
    icon:
        Nerd Font icon character for the tab button.
    side:
        ``"left"`` or ``"right"``.
    """

    def decorator(cls):
        if name in _sidebar_tabs:
            raise ValueError(
                f"Sidebar tab '{name}' is already registered."
            )
        _sidebar_tabs[name] = SidebarTab(
            name=name, icon=icon, side=side, widget_class=cls
        )
        return cls

    return decorator


def get_sidebar_tabs(side: str | None = None) -> list[SidebarTab]:
    """Return registered tabs, optionally filtered by *side*.

    Returns tabs in registration order.
    """
    tabs = list(_sidebar_tabs.values())
    if side:
        tabs = [t for t in tabs if t.side == side]
    return tabs


def reset_sidebar_tabs() -> None:
    """Clear all registered tabs (test isolation)."""
    _sidebar_tabs.clear()
