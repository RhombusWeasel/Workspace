"""WorkspaceTabs — custom tabbed container with closeable tabs.

Provides a tab bar at the top with label buttons and close (×) buttons,
and a content area below showing the active tab's content widget.

Tabs are identified by string IDs.  Opening a tab with an existing ID
switches to it instead of duplicating it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Button, Static

from utils.icons import CLOSE


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------


@dataclass
class TabInfo:
    """Metadata for an open tab."""

    id: str
    label: str
    content: Widget | None = None


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------


class _TabLabelButton(Button):
    """Button representing a tab label in the tab bar."""

    DEFAULT_CSS = """
    _TabLabelButton {
        height: 1;
        min-width: 6;
        max-width: 24;
        padding: 0 1;
        border: none;
        background: $surface;
        color: $text;
    }
    _TabLabelButton.-active {
        background: $primary;
        color: $text;
    }
    _TabLabelButton:hover {
        background: $primary-lighten-1;
    }
    """

    def __init__(self, tab_id: str, label: str):
        super().__init__(label, id=f"tab-label-{tab_id}")
        self.tab_id = tab_id


class _TabCloseButton(Button):
    """Close (×) button for a tab."""

    DEFAULT_CSS = """
    _TabCloseButton {
        height: 1;
        width: 2;
        min-width: 2;
        max-width: 2;
        border: none;
        padding: 0;
        background: transparent;
        color: $text-muted;
    }
    _TabCloseButton:hover {
        background: $error;
        color: $text;
    }
    """

    def __init__(self, tab_id: str):
        super().__init__(CLOSE, id=f"tab-close-{tab_id}")
        self.tab_id = tab_id


# ---------------------------------------------------------------------------
# WorkspaceTabs
# ---------------------------------------------------------------------------


class WorkspaceTabs(Widget):
    """Tabbed container with closeable tabs in the title bar.

    Use ``open_tab()`` to add tabs, ``close_tab()`` to remove them,
    and ``switch_tab()`` to activate a tab.

    Posts:
    - ``TabSwitched`` when the active tab changes.
    - ``TabClosed`` when a tab is removed.
    """

    DEFAULT_CSS = """
    WorkspaceTabs {
        height: 1fr;
        width: 1fr;
    }
    WorkspaceTabs > Vertical {
        height: 1fr;
        width: 1fr;
    }
    WorkspaceTabs .tab-bar {
        height: 1;
        width: 1fr;
        background: $surface;
    }
    WorkspaceTabs .tab-item {
        height: 1;
        width: auto;
    }
    WorkspaceTabs .tab-content {
        height: 1fr;
        width: 1fr;
    }
    """

    class TabSwitched(Message):
        """Posted when the active tab changes."""

        def __init__(self, tab_id: str) -> None:
            super().__init__()
            self.tab_id = tab_id

    class TabClosed(Message):
        """Posted when a tab is closed."""

        def __init__(self, tab_id: str) -> None:
            super().__init__()
            self.tab_id = tab_id

    def __init__(self):
        super().__init__()
        self._tabs: dict[str, TabInfo] = {}
        self._active: str | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def tab_count(self) -> int:
        """Number of open tabs."""
        return len(self._tabs)

    @property
    def active_tab_id(self) -> str | None:
        """ID of the currently active tab, or None if no tabs."""
        return self._active

    def open_tab(self, tab_id: str, label: str, content: Widget) -> None:
        """Open a new tab or switch to an existing one.

        If a tab with *tab_id* already exists, it is switched to
        (and the *content* widget is NOT replaced).
        """
        if tab_id in self._tabs:
            self.switch_tab(tab_id)
            return

        self._tabs[tab_id] = TabInfo(id=tab_id, label=label, content=content)
        self._active = tab_id
        self._refresh()

    def close_tab(self, tab_id: str) -> None:
        """Close a tab and remove its content.

        If the closed tab was active, switches to a neighboring tab.
        If it was the last tab, sets active to None.
        """
        if tab_id not in self._tabs:
            return

        info = self._tabs.pop(tab_id)

        # Determine new active tab
        if self._active == tab_id:
            tabs_list = list(self._tabs.keys())
            if tabs_list:
                # Try to switch to the previous or next tab
                old_index = list(self._tabs.keys()).index(tab_id) if tab_id in self._tabs else -1
                # Pick the first available tab
                self._active = tabs_list[0]
            else:
                self._active = None

        # Remove the content widget from the DOM if it's mounted
        if info.content is not None:
            try:
                info.content.remove()
            except Exception:
                pass

        self._refresh()
        self.post_message(self.TabClosed(tab_id))

    def switch_tab(self, tab_id: str) -> None:
        """Activate a tab."""
        if tab_id not in self._tabs:
            return
        if self._active == tab_id:
            return
        self._active = tab_id
        self._refresh()
        self.post_message(self.TabSwitched(tab_id))

    # ------------------------------------------------------------------
    # Compose
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        self._tab_bar = Horizontal(classes="tab-bar")
        yield self._tab_bar
        self._content_area = Container(classes="tab-content")
        yield self._content_area

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _refresh(self) -> None:
        """Rebuild the tab bar and content area to reflect current state."""
        self._refresh_tab_bar()
        self._refresh_content()

    def _refresh_tab_bar(self) -> None:
        """Rebuild the tab bar with current tabs."""
        # Remove existing tab items
        for child in list(self._tab_bar.children):
            child.remove()

        for tab_id, info in self._tabs.items():
            lbl_btn = _TabLabelButton(tab_id, info.label)
            close_btn = _TabCloseButton(tab_id)
            if tab_id == self._active:
                lbl_btn.add_class("-active")
            self._tab_bar.mount(Horizontal(lbl_btn, close_btn, classes="tab-item"))

    def _refresh_content(self) -> None:
        """Show the active tab's content; hide all others."""
        # Remove all existing content widgets from the content area
        for child in list(self._content_area.children):
            child.remove()

        # Mount the active tab's content
        if self._active and self._active in self._tabs:
            info = self._tabs[self._active]
            if info.content is not None:
                self._content_area.mount(info.content)

    # ------------------------------------------------------------------
    # Button handlers
    # ------------------------------------------------------------------

    def on__tab_label_button_pressed(self, event: _TabLabelButton.Pressed) -> None:
        event.stop()
        tab_id = event.button.tab_id
        self.switch_tab(tab_id)

    def on__tab_close_button_pressed(self, event: _TabCloseButton.Pressed) -> None:
        event.stop()
        tab_id = event.button.tab_id
        self.close_tab(tab_id)