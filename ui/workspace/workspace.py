"""Recursively splitting workspace — the main UI container.

The workspace owns a :class:`~core.pane_tree.Pane` tree and composes it
into Textual ``Horizontal`` / ``Vertical`` containers.  Each leaf pane is
wrapped in a :class:`PaneContainer` that draws a border and manages focus.

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
        Binding("ctrl+left, ctrl+h", "navigate_left", "← Pane", show=True),
        Binding("ctrl+right, ctrl+l", "navigate_right", "→ Pane", show=True),
        Binding("ctrl+up, ctrl+k", "navigate_up", "↑ Pane", show=True),
        Binding("ctrl+down, ctrl+j", "navigate_down", "↓ Pane", show=True),
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
        await self.recompose()

    async def close_pane(self) -> None:
        """Close the currently focused pane."""
        try:
            self._tree = close(self._tree, self.focused_id)
        except ValueError:
            return
        leaves = get_leaves(self._tree)
        self.focused_id = leaves[0].id if leaves else ""
        await self.recompose()

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
        await self.recompose()

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
            if content is not None:
                with container:
                    yield content
            else:
                yield container
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
    # Focus from click
    # ------------------------------------------------------------------

    def on_pane_container_pane_focus(self, msg: PaneContainer.PaneFocus) -> None:
        """Handle PaneFocus messages from PaneContainer clicks."""
        self.focused_id = msg.pane_id
        self._update_focus_styles()

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

def register_workspace_leader_chords() -> None:
    """Register workspace leader chords with the global leader registry.

    Called by bootstrap after the leader registry and workspace are
    initialised.  Chords:

    - ``Ctrl+Space w s h`` → split horizontal
    - ``Ctrl+Space w s v`` → split vertical
    - ``Ctrl+Space w s c`` → close pane
    """
    from core.leader import register_action, register_submenu

    register_submenu(["w"], "Workspace")

    register_action(
        ["w", "s", "h"],
        "Split H",
        lambda: None,  # dispatched via CodyEvent by action_* methods
        labels={"s": "Split"},
    )
    register_action(
        ["w", "s", "v"],
        "Split V",
        lambda: None,
        labels={"s": "Split"},
    )
    register_action(
        ["w", "c"],
        "Close",
        lambda: None,
    )
