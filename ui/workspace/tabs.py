"""WorkspaceTabs — custom tabbed container with closeable tabs.

Provides a tab bar at the top with label buttons and close (×) buttons,
and a content area below showing the active tab's content widget.

Tabs are identified by string IDs.  Opening a tab with an existing ID
switches to it instead of duplicating it.

Tab state survives workspace recomposition (splits / closes) via the
:class:`TabState` model.  Each tab owns a :class:`TabState` object that
persists across widget destruction — widget instances are freely
recreated from the state by the ``content_factory``.
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
# TabState — base class for persistent tab state
# ---------------------------------------------------------------------------


class TabState:
    """Base class for tab state that survives workspace recomposition.

    Subclass this for each widget type that has in-memory state.
    The TabState object is owned by the tab slot, not by the widget
    — it outlives any particular widget instance.

    Call ``dispose()`` when the tab is permanently closed to release
    external resources (PTY processes, database connections, etc.).
    """

    def dispose(self) -> None:
        """Release external resources.  No-op in the base class.

        Called when the tab is permanently closed (not during
        recomposition).  Subclasses that own external resources
        (e.g. PTY processes) override this to clean them up.
        """


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------


@dataclass
class TabInfo:
    """Metadata for an open tab."""

    id: str
    label: str
    state: TabState | None = None
    """Persistent state for this tab.  Survives widget destruction."""
    content: Widget | None = None
    content_factory: Callable[[TabState], Widget | None] | None = None
    """Callable to recreate *content* after a DOM recomposition.

    Receives the tab's :class:`TabState` so the fresh widget can
    read from it in ``on_mount()``.
    """


# ---------------------------------------------------------------------------
# Saved state (for persistence across recomposition)
# ---------------------------------------------------------------------------


@dataclass
class SavedTab:
    """Snapshot of a single tab for persistence across recompose."""

    id: str
    label: str
    state: TabState
    """Persistent state object — survives recomposition unchanged."""
    content_factory: Callable[[TabState], Widget | None] | None = None


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
        self._focus_generation: int = 0
        """Monotonically increasing counter to invalidate stale focus requests."""
        self._batch_depth: int = 0
        """When > 0, :meth:`_refresh` calls are deferred until the batch ends."""

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
        *,
        state: TabState,
        content: Widget | None = None,
        content_factory: Callable[[TabState], Widget | None] | None = None,
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
        state:
            Persistent state object for this tab.  Survives widget
            destruction and is passed to ``content_factory`` when
            recreating content after recomposition.
        content:
            Widget to show in the content area.  May be ``None`` if
            *content_factory* is provided instead.
        content_factory:
            Callable that recreates the content widget.  Receives the
            tab's ``state`` so the fresh widget can read from it in
            ``on_mount()``.
        """
        if tab_id in self._tabs:
            self.switch_tab(tab_id)
            return

        # Build content from factory if needed
        if content is None and content_factory is not None:
            content = content_factory(state)

        self._tabs[tab_id] = TabInfo(
            id=tab_id,
            label=label,
            state=state,
            content=content,
            content_factory=content_factory,
        )
        self._active = tab_id
        self._refresh()

    def close_tab(self, tab_id: str) -> None:
        """Close a tab and remove its content.

        If the closed tab was active, switches to a neighboring tab.
        If it was the last tab, sets active to None.  Calls
        ``dispose()`` on the tab's state to release external resources.
        """
        if tab_id not in self._tabs:
            return

        info = self._tabs.pop(tab_id)

        # Determine new active tab
        if self._active == tab_id:
            tabs_list = list(self._tabs.keys())
            if tabs_list:
                self._active = tabs_list[0]
            else:
                self._active = None

        # Remove the content widget from the DOM if it's mounted
        if info.content is not None:
            try:
                info.content.remove()
            except Exception:
                pass

        # Release external resources owned by the state
        if info.state is not None:
            info.state.dispose()

        self._refresh()
        self.post_message(self.TabClosed(tab_id))

    def begin_batch(self) -> None:
        """Defer :meth:`_refresh` calls until :meth:`end_batch` is called.

        Use this when opening multiple tabs in quick succession (e.g.
        session restore) to avoid the race condition where a previous
        tab's content hasn't finished mounting when the next tab is
        opened, causing both content widgets to be visible at once.

        Calls can be nested — only the outermost :meth:`end_batch`
        triggers the final :meth:`_refresh`.
        """
        self._batch_depth += 1

    def end_batch(self) -> None:
        """End batch mode and refresh the widget.

        Must be called once for each :meth:`begin_batch` call.  When
        the outermost batch ends, :meth:`_refresh` is called to update
        the tab bar and content area.
        """
        if self._batch_depth > 0:
            self._batch_depth -= 1
        if self._batch_depth == 0:
            self._refresh()

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

    def save_state(self, *, disconnect: bool = False) -> SavedTabState:
        """Return a snapshot of all open tabs so they can be restored later.

        ``content_factory`` callables and ``state`` objects are carried
        directly — no extraction or snapshot logic is needed.  Widgets
        that have a ``flush_state()`` method are asked to sync their
        current UI state back to the ``state`` object.

        When ``disconnect`` is True (used during recomposition), widgets
        that have a ``disconnect_from_emulator()`` method are also asked
        to sever their connection to live resources (PTY processes, etc.)
        so that the emulator's queues are not read by two recv tasks
        simultaneously after the DOM rebuild.
        """
        saved_tabs: list[SavedTab] = []
        for tab_id, info in self._tabs.items():
            # Ask the widget to flush any unsynchronised UI state
            # back to the persistent state object.
            if info.content is not None and hasattr(info.content, "flush_state"):
                info.content.flush_state()

            # During recomposition, ask widgets to disconnect from
            # live resources so queues don't conflict after rebuild.
            if disconnect and info.content is not None and hasattr(info.content, "disconnect_from_emulator"):
                info.content.disconnect_from_emulator()

            # state and content_factory are carried directly — they
            # survive recomposition without any widget-specific logic.
            if info.state is None:
                continue  # skip stateless tabs (shouldn't happen)

            saved_tabs.append(SavedTab(
                id=tab_id,
                label=info.label,
                state=info.state,
                content_factory=info.content_factory,
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
        # factories.  Each factory receives the tab's state object.
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
                    state=saved.state,
                    content=existing.content,
                    content_factory=saved.content_factory
                    if saved.content_factory is not None
                    else existing.content_factory,
                )
            else:
                # Create fresh content from the factory, passing the state.
                content = None
                if saved.content_factory is not None:
                    content = saved.content_factory(saved.state)
                rebuilt_tabs[saved.id] = TabInfo(
                    id=saved.id,
                    label=saved.label,
                    state=saved.state,
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
        if self._batch_depth > 0:
            return
        self._focus_generation += 1
        self._refresh_tab_bar()
        self._refresh_content()
        self._focus_active_content()

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

    def _focus_active_content(self) -> None:
        """Focus the active tab's content (or its first focusable descendant).

        When a tab becomes active — whether opened, switched to, or after
        closing another tab — the user expects to be able to interact
        immediately.  This method locates the first focusable widget inside
        the active tab's content and gives it keyboard focus.

        When the content widget is already mounted (e.g. tab switch), focus
        is set immediately.  When a newly-opened tab's content is still
        being mounted, a short retry loop waits for the mount to complete
        before focusing.

        A generation counter ensures that stale focus requests from
        previous tab activations are cancelled — e.g. if a retry timer
        from tab-1 fires after tab-2 has already been activated and
        focused, it is silently ignored.
        """
        if self._active is None:
            return
        info = self._tabs.get(self._active)
        if info is None or info.content is None:
            return

        content = info.content
        generation = self._focus_generation

        def _try_focus(retries: int = 10) -> None:
            # If a newer focus request has been issued, abort.
            if self._focus_generation != generation:
                return
            if content is None or not content.is_mounted:
                if retries > 0:
                    self.set_timer(0.01, lambda: _try_focus(retries - 1))
                return
            # If the content widget itself is focusable, focus it.
            if content.focusable:
                content.focus()
                return
            # Otherwise, find the first focusable descendant.
            try:
                for widget in content.query("*").results(Widget):
                    if widget.focusable:
                        widget.focus()
                        return
            except Exception:
                pass

        _try_focus()

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