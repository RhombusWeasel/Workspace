"""Recursively splitting workspace — the main UI container.

The workspace owns a :class:`~core.pane_tree.Pane` tree and composes it
into Textual ``Horizontal`` / ``Vertical`` containers.  Each leaf pane is
wrapped in a :class:`PaneContainer` that draws a border and manages focus.

Every pane launches with a :class:`~ui.workspace.tabs.WorkspaceTabs` so
the user immediately sees a tabbed interface.  A "Welcome" tab is opened
in the initial pane on startup.

Tab state survives workspace recomposition (splits / closes) via the
:class:`~ui.workspace.tabs.TabState` model.  Each tab owns a persistent
state object that outlives any widget instance — the widget simply reads
from and writes to the state.  No snapshot extraction or injection is
needed.

Navigation: vim-style ``Ctrl+hjkl`` or mouse click.
Leader chords post :class:`~core.events.CodyEvent` messages.
"""

from __future__ import annotations

import uuid
from textual.containers import Horizontal, Vertical
from textual.widget import Widget
from textual.message import Message
from textual.reactive import reactive
from textual.binding import Binding

from core.pane_tree import (
    Pane,
    LeafPane,
    SplitPane,
    create_leaf,
    split,
    close,
    find_neighbor,
    set_content,
    get_leaves,
)
from core.events import CodyEvent
from core.terminal_passthrough import register_terminal_passthrough
from ui.workspace.tabs import TabState, WorkspaceTabs


# ---------------------------------------------------------------------------
# PaneContainer — bordered wrapper for a leaf's content widget
# ---------------------------------------------------------------------------


class PaneContainer(Widget):
    """Wraps a leaf pane's content with a border and focus management.

    When clicked, it posts a :class:`PaneFocus` message so the workspace
    can update its ``focused_id``.
    """

    class PaneFocus(Message):
        """Posted when this container receives focus (click or programmatic)."""

        def __init__(self, pane_id: str) -> None:
            super().__init__()
            self.pane_id = pane_id

    focused: reactive[bool] = reactive(False)
    """Whether this pane has workspace-level focus."""

    def __init__(self, pane_id: str):
        super().__init__(id=f"pane-{pane_id}")
        self.pane_id = pane_id

    def watch_focused(self, value: bool) -> None:
        self.set_class(value, "focused")

    def on_click(self, event) -> None:
        """Mouse click focuses this pane."""
        self.post_message(self.PaneFocus(self.pane_id))
        event.stop()


# ---------------------------------------------------------------------------
# Workspace
# ---------------------------------------------------------------------------


class Workspace(Widget):
    """Recursively splitting workspace.

    Owns a pane tree and renders it as nested Textual containers.
    Supports split, close, navigate, and content swapping.
    """

    can_focus = True

    BINDINGS = [
        Binding("ctrl+left, ctrl+h", "navigate_left", "← Pane", show=False),
        Binding("ctrl+right, ctrl+l", "navigate_right", "→ Pane", show=False),
        Binding("ctrl+up, ctrl+k", "navigate_up", "↑ Pane", show=False),
        Binding("ctrl+down, ctrl+j", "navigate_down", "↓ Pane", show=False),
    ]

    def __init__(self):
        super().__init__(id="workspace")
        self._tree: Pane = create_leaf("main")
        self.focused_id: str = "main"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def tree(self) -> Pane:
        return self._tree

    async def split_pane(self, direction: str, ratio: float = 0.5) -> None:
        """Split the currently focused pane.

        Args:
            direction: ``"h"`` or ``"v"``.
            ratio: Fraction for the first (original) child.
        """
        new_id = uuid.uuid4().hex[:8]
        try:
            self._tree = split(self._tree, self.focused_id, direction, ratio, new_id)
        except ValueError:
            return
        await self._recompose_preserving_content()

    async def close_pane(self) -> None:
        """Close the currently focused pane."""
        try:
            self._tree = close(self._tree, self.focused_id)
        except ValueError:
            return
        leaves = get_leaves(self._tree)
        self.focused_id = leaves[0].id if leaves else ""
        await self._recompose_preserving_content()

    def navigate(self, direction: str) -> None:
        """Move focus in *direction* (``"left"``, ``"right"``, ``"up"``, ``"down"``).

        Posts a ``workspace.navigated`` event on success.
        """
        neighbor = find_neighbor(self._tree, self.focused_id, direction)
        if neighbor is not None:
            self.focused_id = neighbor
            self._update_focus_styles()
            self.post_message(
                CodyEvent("workspace.navigated", {"pane_id": neighbor})
            )

    async def set_pane_content(self, pane_id: str, content: Widget) -> None:
        """Mount *content* into the leaf with *pane_id*.

        If the pane already has content, it is replaced.
        """
        try:
            self._tree = set_content(self._tree, pane_id, content)
        except ValueError:
            return
        await self._recompose_preserving_content()

    def get_leaf_ids(self) -> list[str]:
        return [leaf.id for leaf in get_leaves(self._tree)]

    # ------------------------------------------------------------------
    # Composition
    # ------------------------------------------------------------------

    def compose(self):
        """Yield the entire widget tree using Textual's context-manager nesting."""
        yield from self._compose_tree(self._tree)

    def _compose_tree(self, pane: Pane):
        if isinstance(pane, LeafPane):
            container = PaneContainer(pane.id)
            if pane.id == self.focused_id:
                container.focused = True
            content = pane.content
            with container:
                if content is not None:
                    yield content
                else:
                    yield WorkspaceTabs()
        else:
            layout_cls = Horizontal if pane.direction == "h" else Vertical
            layout = layout_cls(id=f"split-{pane.id}")
            with layout:
                for child in pane.children:
                    yield from self._compose_tree(child)
            # layout is auto-yielded by the `with` context manager

    def _update_focus_styles(self) -> None:
        """Update ``focused`` reactive on all PaneContainers in the DOM."""
        for leaf in get_leaves(self._tree):
            try:
                container = self.query_one(f"#pane-{leaf.id}", PaneContainer)
                container.focused = (leaf.id == self.focused_id)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Content preservation around recomposition
    # ------------------------------------------------------------------

    def _save_pane_tab_states(self) -> dict[str, "SavedTabState"]:
        """Collect tab state from every pane that has a WorkspaceTabs."""
        from ui.workspace.tabs import WorkspaceTabs, SavedTabState

        states: dict[str, SavedTabState] = {}
        for leaf in get_leaves(self._tree):
            try:
                container = self.query_one(f"#pane-{leaf.id}", PaneContainer)
                tabs = container.query_one(WorkspaceTabs)
                states[leaf.id] = tabs.save_state()
            except Exception:
                pass
        return states



    def _restore_pane_tab_states(
        self, states: dict[str, "SavedTabState"]
    ) -> set[str]:
        """Restore tab state into any pane that previously had tabs.

        After a recompose, each ``PaneContainer`` whose leaf has no
        direct content already contains a fresh ``WorkspaceTabs``
        (yielded by ``_compose_tree``).  This method restores saved
        tab state into that existing instance rather than creating a
        redundant one.

        Panes whose leaf has direct content (set via
        :meth:`set_pane_content`) are skipped — they display a widget
        directly, not a tabbed interface.

        Returns the set of pane IDs that were successfully restored.
        """
        from ui.workspace.tabs import SavedTabState

        # Panes with direct content don't use WorkspaceTabs.
        direct_content_ids = {
            leaf.id
            for leaf in get_leaves(self._tree)
            if leaf.content is not None
        }

        restored: set[str] = set()
        for pane_id, state in states.items():
            if pane_id in direct_content_ids:
                continue
            try:
                container = self.query_one(f"#pane-{pane_id}", PaneContainer)
                try:
                    tabs = container.query_one(WorkspaceTabs)
                except Exception:
                    # Fallback: create a new one if compose didn't
                    tabs = WorkspaceTabs()
                    container.mount(tabs)
                tabs.restore_state(state)
                restored.add(pane_id)
            except Exception:
                pass
        return restored

    def _cleanup_orphaned_states(
        self, states: dict[str, "SavedTabState"], restored: set[str]
    ) -> None:
        """Dispose tab state for tabs whose pane was closed.

        When a pane is closed, its saved state is not restored (because
        the pane no longer exists in the tree).  This method calls
        ``dispose()`` on each orphaned tab's state, releasing external
        resources like PTY processes or database connections.
        """
        for pane_id, state in states.items():
            if pane_id in restored:
                continue
            for tab in state.tabs:
                tab.state.dispose()

    async def _recompose_preserving_content(self) -> None:
        """Recompose the widget tree while preserving WorkspaceTabs content.

        Saves all tab state (including persistent TabState objects) before
        recomposing and restores it afterward so that open files and
        running terminals survive workspace splits and closes.

        Each widget's ``flush_state()`` is called before recomposition to
        sync any unsaved UI state back to the TabState object.  After
        recomposition, fresh widgets are created from factories that
        receive the same TabState — so they read from state in on_mount().
        Orphaned tabs (whose pane was closed) have their state disposed,
        releasing external resources like PTY processes.
        """
        saved = self._save_pane_tab_states()
        await self.recompose()
        restored = self._restore_pane_tab_states(saved)
        self._cleanup_orphaned_states(saved, restored)

    # ------------------------------------------------------------------
    # Initial welcome tab
    # ------------------------------------------------------------------

    def on_mount(self) -> None:
        """Open a Welcome tab in the initially focused pane."""
        self.run_worker(self._open_welcome_tab())

    async def _open_welcome_tab(self) -> None:
        """Open the Welcome tab in the focused pane's WorkspaceTabs."""
        from ui.workspace.welcome_view import WelcomeView
        from ui.workspace.tabs import TabState

        # WelcomeView is stateless, but we still need a TabState for
        # the new architecture.  A bare TabState suffices.
        welcome_state = TabState()

        try:
            container = self.query_one(f"#pane-{self.focused_id}", PaneContainer)
            tabs = container.query_one(WorkspaceTabs)
        except Exception:
            return

        tabs.open_tab(
            "welcome",
            "Welcome",
            state=welcome_state,
            content_factory=lambda s: WelcomeView(),
        )

    # ------------------------------------------------------------------
    # Focus from click
    # ------------------------------------------------------------------

    def on_pane_container_pane_focus(self, msg: PaneContainer.PaneFocus) -> None:
        """Handle PaneFocus messages from PaneContainer clicks."""
        self.focused_id = msg.pane_id
        self._update_focus_styles()

    # ------------------------------------------------------------------
    # Leader event listeners
    # ------------------------------------------------------------------

    def on_cody_event(self, event: CodyEvent) -> None:
        """Route CodyEvents dispatched from leader chord handlers."""
        et = event.event_type
        if et == "leader.workspace.split_h":
            self.run_worker(self.action_split_horizontal())
            event.stop()
        elif et == "leader.workspace.split_v":
            self.run_worker(self.action_split_vertical())
            event.stop()
        elif et == "leader.workspace.close":
            self.run_worker(self.action_close_pane())
            event.stop()

    # ------------------------------------------------------------------
    # Leader key actions
    # ------------------------------------------------------------------

    async def action_split_horizontal(self) -> None:
        # vim convention: "horizontal split" = horizontal divider = top/bottom
        await self.split_pane("v")
        self.post_message(CodyEvent("workspace.split", {"direction": "h"}))

    async def action_split_vertical(self) -> None:
        # vim convention: "vertical split" = vertical divider = left/right
        await self.split_pane("h")
        self.post_message(CodyEvent("workspace.split", {"direction": "v"}))

    async def action_close_pane(self) -> None:
        await self.close_pane()
        self.post_message(CodyEvent("workspace.closed", {"pane_id": self.focused_id}))

    def action_navigate_left(self) -> None:
        self.navigate("left")

    def action_navigate_right(self) -> None:
        self.navigate("right")

    def action_navigate_up(self) -> None:
        self.navigate("up")

    def action_navigate_down(self) -> None:
        self.navigate("down")


# ---------------------------------------------------------------------------
# Leader chord registration
# ---------------------------------------------------------------------------

# These keys must not be consumed by the embedded terminal widget
# so workspace navigation works even when the terminal has focus.
register_terminal_passthrough({"ctrl+h", "ctrl+l", "ctrl+k", "ctrl+j", "ctrl+left", "ctrl+right", "ctrl+up", "ctrl+down"})


def register_workspace_leader_chords() -> None:
    """Register workspace leader chords with the global leader registry.

    Called by bootstrap after the leader registry and workspace are
    initialised.  Chords:

    - ``Ctrl+Space w s h`` → split horizontal
    - ``Ctrl+Space w s v`` → split vertical
    - ``Ctrl+Space w c`` → close pane
    """
    from core.leader import register_action, register_submenu

    register_submenu(["w"], "Workspace")

    register_action(
        ["w", "s", "h"],
        "Split H",
        event_type="leader.workspace.split_h",
        labels={"s": "Split"},
    )
    register_action(
        ["w", "s", "v"],
        "Split V",
        event_type="leader.workspace.split_v",
        labels={"s": "Split"},
    )
    register_action(
        ["w", "c"],
        "Close",
        event_type="leader.workspace.close",
    )
    register_action(
        ["w", "t", "l"],
        "Toggle Left",
        event_type="leader.workspace.toggle_left",
        labels={"t": "Toggle"},
    )
    register_action(
        ["w", "t", "r"],
        "Toggle Right",
        event_type="leader.workspace.toggle_right",
        labels={"t": "Toggle"},
    )
