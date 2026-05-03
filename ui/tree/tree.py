"""Generic tree widget — hierarchical list with expand/collapse."""

from __future__ import annotations

from typing import Any

from textual.containers import VerticalScroll
from textual.message import Message
from textual.reactive import reactive

from ui.tree.tree_row import TreeNode, TreeRow, RowButton, ActionRow


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------


class NodeSelected(Message):
    """Posted when a node is selected."""

    def __init__(self, node_id: str, node: TreeNode) -> None:
        super().__init__()
        self.node_id = node_id
        self.node = node


class NodeToggled(Message):
    """Posted when a node is expanded or collapsed."""

    def __init__(self, node_id: str, node: TreeNode, expanded: bool) -> None:
        super().__init__()
        self.node_id = node_id
        self.node = node
        self.expanded = expanded


# ---------------------------------------------------------------------------
# Tree
# ---------------------------------------------------------------------------


class Tree(VerticalScroll, can_focus=True):
    """A generic tree widget that renders :class:`TreeNode` data as
    :class:`TreeRow` widgets.

    Supports expand/collapse, keyboard navigation, and selection.
    """

    selected_id: reactive[str | None] = reactive(None)

    def __init__(self, root: TreeNode):
        super().__init__()
        self._root = root
        self._expanded: set[str] = {root.id}
        self._node_map: dict[str, TreeNode] = {}
        self._build_node_map(root)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def root(self) -> TreeNode:
        return self._root

    def set_root(self, new_root: TreeNode) -> None:
        """Replace the entire tree with a new root node.

        Resets the expand state — only the new root is expanded.
        Use :meth:`rebuild` for incremental updates to the same root.
        """
        self._root = new_root
        self._node_map.clear()
        self._build_node_map(new_root)
        self._expanded = {new_root.id}
        self._rebuild_rows()

    def rebuild(self) -> None:
        """Rebuild visible rows for the current root *without* resetting
        the expand state.

        Call this after modifying the tree data model in-place
        (adding/removing children) to reflect changes in the UI.
        Content widgets on existing, still-visible nodes are preserved.
        """
        # Re-scan node map in case children were added/removed
        self._node_map.clear()
        self._build_node_map(self._root)
        self._rebuild_rows()

    def update_node_label(self, node_id: str, label: str) -> None:
        """Update the display label of a node in-place (no full rebuild)."""
        if node_id not in self._node_map:
            return
        self._node_map[node_id].label = label
        for row in self.query("TreeRow"):
            if row.node.id == node_id:
                row.refresh(layout=True)

    def select_node(self, node_id: str) -> None:
        """Programmatically select a node by id."""
        if node_id not in self._node_map:
            return
        self.selected_id = node_id
        self._update_selection()
        node = self._node_map[node_id]
        self.post_message(NodeSelected(node_id, node))

    def expand_node(self, node_id: str) -> None:
        """Expand a branch node, revealing its children."""
        if node_id not in self._node_map:
            return
        node = self._node_map[node_id]
        if not node.children:
            return
        if node_id in self._expanded:
            return
        self._expanded.add(node_id)
        self._rebuild_rows()
        self.post_message(NodeToggled(node_id, node, True))

    def collapse_node(self, node_id: str) -> None:
        """Collapse a branch node, hiding its children."""
        if node_id not in self._expanded:
            return
        self._expanded.discard(node_id)
        self._rebuild_rows()
        node = self._node_map[node_id]
        self.post_message(NodeToggled(node_id, node, False))

    def toggle_node(self, node_id: str) -> None:
        """Toggle expand/collapse for a branch node."""
        if node_id in self._expanded:
            self.collapse_node(node_id)
        else:
            self.expand_node(node_id)

    def expand_all(self) -> None:
        """Expand every branch node in the tree."""
        for node_id, node in self._node_map.items():
            if node.children:
                self._expanded.add(node_id)
        self._rebuild_rows()

    def is_expanded(self, node_id: str) -> bool:
        return node_id in self._expanded

    # ------------------------------------------------------------------
    # Composition
    # ------------------------------------------------------------------

    def on_mount(self) -> None:
        self._rebuild_rows()

    def _build_node_map(self, node: TreeNode) -> None:
        self._node_map[node.id] = node
        for child in node.children:
            self._build_node_map(child)

    def _get_visible_nodes(self) -> list[tuple[TreeNode, int]]:
        """Walk the tree and return (node, depth) for visible nodes."""
        result: list[tuple[TreeNode, int]] = []

        def walk(node: TreeNode, depth: int) -> None:
            result.append((node, depth))
            if node.id in self._expanded:
                for child in node.children:
                    walk(child, depth + 1)

        walk(self._root, 0)
        return result

    def _rebuild_rows(self) -> None:
        """Update tree rows to match the current expand state.

        Uses a diff approach: rows for nodes that are still visible are
        kept in place (preserving any content widgets).  Rows for newly
        visible nodes are created; rows for now-hidden nodes are removed.
        """
        visible = self._get_visible_nodes()
        visible_ids = {node.id for node, _ in visible}

        # Remove rows whose node is no longer visible
        for row in self.query("TreeRow, ActionRow"):
            if row.node.id not in visible_ids:
                row.remove()

        # Collect existing row node ids
        existing = {row.node.id for row in self.query("TreeRow, ActionRow")}

        # Mount rows for newly visible nodes
        for node, depth in visible:
            if node.id in existing:
                continue
            is_branch = bool(node.children)
            if node.buttons:
                row: Widget = ActionRow(node, depth=depth)
            else:
                row = TreeRow(node, depth=depth, is_branch=is_branch)
                if node.id == self.selected_id:
                    row.is_selected = True
            self.mount(row)

    def _update_selection(self) -> None:
        """Update is_selected on all rows to match selected_id."""
        for row in self.query(TreeRow):
            row.is_selected = (row.node.id == self.selected_id)

    # ------------------------------------------------------------------
    # Message handlers
    # ------------------------------------------------------------------

    def on_tree_row_selected(self, msg: TreeRow.Selected) -> None:
        msg.stop()
        self.select_node(msg.node.id)

    def on_tree_row_toggled(self, msg: TreeRow.Toggled) -> None:
        msg.stop()
        self.toggle_node(msg.node.id)

    def on_action_row_button_pressed(self, msg: ActionRow.ButtonPressed) -> None:
        """Re-bubble ActionRow.ButtonPressed so owners can listen.

        The message is NOT stopped — it bubbles up to the vault panel.
        """
