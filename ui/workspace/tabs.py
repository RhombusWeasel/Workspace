"""WorkspaceTabs — custom tabbed container with closeable tabs.

Provides a tab bar at the top with label buttons and close (×) buttons,
and a content area below showing the active tab's content widget.

Tabs are identified by string IDs.  Opening a tab with an existing ID
switches to it instead of duplicating it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Button

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
    content_factory: Callable[[], Widget | None] | None = None
    """Callable to recreate *content* after a DOM recomposition.

    When set, this is preferred over storing a stale widget reference.
    Called by :meth:`WorkspaceTabs.restore_state` to build a fresh widget.
    """


# ---------------------------------------------------------------------------
# Saved state (for persistence across recomposition)
# ---------------------------------------------------------------------------


@dataclass
class SavedTab:
    """Serializable snapshot of a single tab for persistence across recompose."""

    id: str
    label: str
    content_factory: Callable[[], Widget | None] | None = None
    inherited_snapshot: Any = None
    """TerminalSnapshot from a previous TerminalView instance.

    When set, the freshly-created TerminalView will adopt the live
    emulator and restore the saved screen/display in
    :meth:`~ui.terminal.terminal.TerminalView.on_mount`, keeping the
    shell session alive and its visible output intact across workspace
    recompositions.
    """
    editor_snapshot: Any = None
    """QueryEditorSnapshot from a previous QueryEditor instance.

    When set, the freshly-created QueryEditor will restore the query
    text, results, and pagination state in
    :meth:`~ui.workspace.query_editor.QueryEditor.on_mount`, keeping
    the editor's content intact across workspace recompositions.
    """


@dataclass
class SavedTabState:
    """Full snapshot of a WorkspaceTabs instance for persistence across recompose."""

    tabs: list[SavedTab]
    active_id: str | None = None


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------


class _TabLabelButton(Button):
    """Button representing a tab label in the tab bar."""

    def __init__(self, tab_id: str, label: str):
        super().__init__(label, id=f"tab-label-{tab_id}")
        self.tab_id = tab_id


class _TabCloseButton(Button):
    """Close (×) button for a tab."""

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

    def open_tab(
        self,
        tab_id: str,
        label: str,
        content: Widget | None = None,
        *,
        content_factory: Callable[[], Widget | None] | None = None,
    ) -> None:
        """Open a new tab or switch to an existing one.

        If a tab with *tab_id* already exists, it is switched to
        (and the *content* widget is NOT replaced).

        Parameters
        ----------
        tab_id:
            Unique identifier for the tab.
        label:
            Display label for the tab bar button.
        content:
            Widget to show in the content area.  May be ``None`` if
            *content_factory* is provided instead.
        content_factory:
            Callable that recreates the content widget.  Used by
            :meth:`save_state` / :meth:`restore_state` to rebuild
            tabs after a DOM recomposition.  When provided, the
            factory is stored alongside the widget so that the tab
            can survive recomposition even if the original widget is
            destroyed.
        """
        if tab_id in self._tabs:
            self.switch_tab(tab_id)
            return

        # Build content from factory if needed
        if content is None and content_factory is not None:
            content = content_factory()

        self._tabs[tab_id] = TabInfo(
            id=tab_id,
            label=label,
            content=content,
            content_factory=content_factory,
        )
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
    # State persistence (survives DOM recomposition)
    # ------------------------------------------------------------------

    def save_state(self) -> SavedTabState:
        """Return a snapshot of all open tabs so they can be restored later.

        ``content_factory`` callables are saved for all tab types.
        For terminal tabs, the live PTY emulator is also extracted
        (via :meth:`TerminalView.detach_emulator`) so the shell
        session can be kept alive across the DOM rebuild.
        For query editor tabs, the editor state (query text, results,
        pagination) is captured via :meth:`QueryEditor.detach_state`
        so the user doesn't lose their work across recomposition.
        """
        from ui.workspace.file_editor import FileEditor
        from ui.terminal.terminal import TerminalView
        from ui.workspace.query_editor import QueryEditor

        saved_tabs: list[SavedTab] = []
        for tab_id, info in self._tabs.items():
            factory = info.content_factory
            # Auto-derive factory for known content types
            if factory is None and isinstance(info.content, FileEditor):
                filepath = info.content.filepath
                factory = lambda fp=filepath: FileEditor(fp)
            # For terminal tabs, extract the live PTY emulator and
            # screen/display so the shell session and its visible output
            # survive workspace recomposition.
            inherited_snapshot = None
            if isinstance(info.content, TerminalView):
                inherited_snapshot = info.content.detach_emulator()
            # For query editor tabs, capture the query text, results,
            # and pagination state so the editor survives recomposition.
            editor_snapshot = None
            if isinstance(info.content, QueryEditor):
                editor_snapshot = info.content.detach_state()
            saved_tabs.append(SavedTab(
                id=tab_id,
                label=info.label,
                content_factory=factory,
                inherited_snapshot=inherited_snapshot,
                editor_snapshot=editor_snapshot,
            ))

        return SavedTabState(tabs=saved_tabs, active_id=self._active)

    def restore_state(self, state: SavedTabState) -> None:
        """Rebuild tabs from a previously saved state.

        Preserves any content widgets that are already mounted and in the
        ``_tabs`` dict — only the tab bar and content visibility are
        updated.  Content widgets that no longer appear in the saved
        state are removed; new content is created from factories.
        """
        # Remove tab bar entries (will be rebuilt)
        if hasattr(self, "_tab_bar"):
            for child in list(self._tab_bar.children):
                child.remove()

        # Remove content widgets that are NOT in the incoming state
        new_tab_ids = {saved.id for saved in state.tabs}
        for tab_id in list(self._tabs):
            if tab_id not in new_tab_ids:
                info = self._tabs.pop(tab_id)
                if info.content is not None:
                    try:
                        info.content.remove()
                    except Exception:
                        pass

        # Clear stale content-area widgets that aren't tracked by any tab
        surviving_content = {
            info.content
            for info in self._tabs.values()
            if info.content is not None and info.content.is_mounted
        }
        for child in list(self._content_area.children):
            if child not in surviving_content:
                try:
                    child.remove()
                except Exception:
                    pass

        # Rebuild _tabs from saved state, creating fresh content from
        # factories.  Terminal tabs receive an inherited_emulator to keep
        # the shell session alive.
        rebuilt_tabs: dict[str, TabInfo] = {}
        for saved in state.tabs:
            existing = self._tabs.get(saved.id)
            if existing is not None and existing.content is not None:
                # Keep the existing content widget (e.g. a running terminal)
                rebuilt_tabs[saved.id] = TabInfo(
                    id=saved.id,
                    label=saved.label
                    if saved.label is not None
                    else existing.label,
                    content=existing.content,
                    content_factory=saved.content_factory
                    if saved.content_factory is not None
                    else existing.content_factory,
                )
            else:
                # Create fresh content from the factory.
                content = None
                if saved.content_factory is not None:
                    content = saved.content_factory()
                # If this is a terminal tab with an inherited snapshot,
                # transfer it so the shell session and visible output survive.
                if saved.inherited_snapshot is not None:
                    from ui.terminal.terminal import TerminalView
                    if isinstance(content, TerminalView):
                        content._inherited_snapshot = saved.inherited_snapshot
                # If this is a query editor tab with a captured snapshot,
                # transfer it so the query text and results survive.
                if saved.editor_snapshot is not None:
                    from ui.workspace.query_editor import QueryEditor
                    if isinstance(content, QueryEditor):
                        content._inherited_snapshot = saved.editor_snapshot
                rebuilt_tabs[saved.id] = TabInfo(
                    id=saved.id,
                    label=saved.label,
                    content=content,
                    content_factory=saved.content_factory,
                )

        self._tabs.clear()
        self._tabs.update(rebuilt_tabs)
        self._active = state.active_id
        self._refresh()

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
        """Show the active tab's content; hide all others.

        Instead of removing and remounting content widgets on every tab
        switch (which destroys terminal PTY processes), we keep all
        content widgets mounted and toggle their visibility.  Widgets
        that don't exist in the DOM yet are mounted; existing ones are
        simply shown or hidden.
        """
        active_info = (
            self._tabs.get(self._active) if self._active else None
        )

        for tab_id, info in self._tabs.items():
            if info.content is None:
                continue
            is_active = tab_id == self._active
            if info.content.is_mounted:
                # Widget is already in the DOM — just toggle visibility.
                # Using .display instead of .visible so hidden widgets
                # are excluded from the layout.
                info.content.display = is_active
            elif is_active:
                # Active tab's content isn't mounted yet — mount it.
                self._content_area.mount(info.content)
                # .display defaults to True so nothing else to do.

        # Remove any children that don't belong to a tab (stale from
        # a previous state that wasn't in _tabs when mounted).
        active_content = (
            active_info.content if active_info and active_info.content else None
        )
        for child in list(self._content_area.children):
            if child is active_content:
                continue
            # Only remove children that aren't tracked in any tab
            tracked = any(
                t.content is child for t in self._tabs.values()
            )
            if not tracked:
                child.remove()

    # ------------------------------------------------------------------
    # Button handlers
    # ------------------------------------------------------------------

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses from tab label and close buttons."""
        button = event.button
        if isinstance(button, _TabLabelButton):
            self.switch_tab(button.tab_id)
            event.stop()
        elif isinstance(button, _TabCloseButton):
            self.close_tab(button.tab_id)
            event.stop()