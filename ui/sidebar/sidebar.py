"""Sidebar — tabbed panel container for left/right workspace edges.

Renders registered sidebar tabs as a ``TabbedContent`` widget.
Wrapped by ``SidebarContainer`` for show/hide animation.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container
from textual.widgets import TabbedContent, TabPane

from ui.sidebar.registry import get_sidebar_tabs


class Sidebar(Container):
    """Tabbed sidebar that hosts panels registered for one side.

    Parameters
    ----------
    side:
        ``"left"`` or ``"right"`` — only tabs registered for this
        side are shown.
    """

    def __init__(self, side: str):
        super().__init__()
        self._side = side

    def compose(self) -> ComposeResult:
        tabs = get_sidebar_tabs(self._side)
        if not tabs:
            return

        with TabbedContent():
            for tab in tabs:
                with TabPane(tab.icon, id=f"tab-{tab.name}"):
                    yield tab.widget_class()

    def on_mount(self) -> None:
        """Set tooltips on tab buttons after mount."""
        tabs = get_sidebar_tabs(self._side)
        if not tabs:
            return
        try:
            tabbed = self.query_one(TabbedContent)
        except Exception:
            return
        for tab_meta in tabs:
            pane_id = f"tab-{tab_meta.name}"
            tab_widget = tabbed.get_tab(pane_id)
            if tab_widget is not None and tab_meta.tooltip:
                tab_widget.tooltip = tab_meta.tooltip

# ---------------------------------------------------------------------------
# SidebarContainer — animated show/hide wrapper
# ---------------------------------------------------------------------------


class SidebarContainer(Container):
    """Wraps a :class:`Sidebar` with animated show/hide via CSS transitions.

    Parameters
    ----------
    sidebar:
        The sidebar widget to wrap.
    side:
        ``"left"`` or ``"right"``.
    start_hidden:
        Whether the sidebar starts collapsed.
    """

    def __init__(
        self, sidebar: Sidebar, *, side: str, start_hidden: bool = True
    ):
        super().__init__()
        self.sidebar = sidebar
        self._hidden = start_hidden

    def compose(self) -> ComposeResult:
        yield self.sidebar

    def on_mount(self) -> None:
        if self._hidden:
            self.add_class("hidden")

    @property
    def is_hidden(self) -> bool:
        return self._hidden

    def toggle(self) -> None:
        """Toggle visibility with slide animation."""
        self._hidden = not self._hidden
        if self._hidden:
            self.add_class("hidden")
        else:
            self.remove_class("hidden")

    def show(self) -> None:
        if self._hidden:
            self.toggle()

    def hide(self) -> None:
        if not self._hidden:
            self.toggle()
