"""Generic tree widget — hierarchical list with expand/collapse.

Rows are mounted once for all nodes and stay in the DOM.  Expand/collapse
toggles a ``-hidden`` CSS class (``display: none``) instead of removing
and re-mounting rows.  This means content widgets (e.g. ``Markdown``)
survive collapse/expand cycles without special handling.

Every row is a :class:`TreeRow`, whether or not it has action buttons.
Lazy nodes (``loaded=False``) are treated as branches; expanding them
posts :class:`NodeNeedsChildren` instead of expanding immediately.
"""

from __future__ import annotations

from typing import Any

from textual.containers import VerticalScroll
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget

from ui.tree.tree_row import (
    TreeNode,
    TreeRow,
    RowButton,
    ActionRow,
    _LINE_VERTICAL,
    _BRANCH,
    _LAST_BRANCH,
    _INDENT,
)


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


class NodeNeedsChildren(Message):
    """Posted when a lazy node (``loaded=False``) is expanded for the
    first time.

    The handler should populate ``node.children``, set ``node.loaded = True``,
    then call ``tree.rebuild()`` followed by ``tree.expand_node(node_id)``.
    """

    def __init__(self, node_id: str, node: TreeNode) -> None:
        super().__init__()
        self.node_id = node_id
        self.node = node


# ---------------------------------------------------------------------------
# Tree
# ---------------------------------------------------------------------------


class Tree(VerticalScroll, can_focus=True):
    """A generic tree widget that renders :class:`TreeNode` data as
    :class:`TreeRow` widgets.

    Supports expand/collapse, lazy loading, keyboard navigation, and
    selection.  Rows are mounted once — expand/collapse toggles CSS
    visibility.

    Tree lines use box-drawing characters (│ ├── └──) to show
    hierarchical structure.  Branch nodes display a ▼ / ▶ toggle
    that updates dynamically with expand/collapse state.

    Action buttons on :class:`TreeRow` are rendered inline;
    clicking a button posts :class:`TreeRow.ButtonPressed`.
    """

    selected_id: reactive[str | None] = reactive(None)

    def __init__(self, root: TreeNode):
        super().__init__()
        self._root = root
        self._expanded: set[str] = {root.id}
        # IDs of branches the user has manually collapsed.
        # These persist across rebuild() calls so that user collapse
        # decisions survive data-model changes.
        self._user_collapsed: set[str] = set()
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
        Clears user collapse decisions.  All rows are removed
        and re-created.
        """
        self._root = new_root
        self._node_map.clear()
        self._build_node_map(new_root)
        self._expanded = {new_root.id}
        self._user_collapsed.clear()
        # Detach content widgets so they don't get destroyed with rows
        self._orphan_content_widgets()
        self._remove_all_rows()
        self._mount_all_rows()
        self._refresh_visibility()

    def rebuild(self) -> None:
        """Sync rows to the current data model without resetting expand state.

        Call after adding/removing children in-place.  Rows for nodes
        that still exist are preserved (including their content widgets).
        Rows for removed nodes are unmounted; rows for new nodes are mounted.
        Visibility is refreshed from ``_expanded``.
        """
        self._node_map.clear()
        self._build_node_map(self._root)

        # Remove rows whose node no longer exists.
        for row in list(self.query(TreeRow)):
            if row.node.id not in self._node_map:
                # Detach content widgets first so they survive.
                if row.node.content is not None:
                    row.node.content = None
                row.remove()

        # Sync existing rows — a node may have gained or lost children
        # since the last rebuild, transitioning between leaf and branch.
        # Also update the tree-line prefix which depends on sibling order.
        prefixes = self._compute_prefixes()
        for row in self.query(TreeRow):
            node = row.node
            new_branch = bool(node.children) or not node.loaded
            new_prefix = prefixes.get(node.id, "")
            if row.is_branch != new_branch or row.prefix != new_prefix:
                row.is_branch = new_branch
                row.prefix = new_prefix
                row.set_expanded(node.id in self._expanded)

        # Mount rows for new nodes.
        existing_ids = {row.node.id for row in self.query(TreeRow)}
        order: dict[str, int] = {}
        for i, (node, depth) in enumerate(self._get_all_nodes_depth()):
            order[node.id] = i
            if node.id in existing_ids:
                continue
            is_branch = bool(node.children) or not node.loaded
            prefix = prefixes.get(node.id, "")
            expanded = node.id in self._expanded
            row = TreeRow(
                node, depth=depth, is_branch=is_branch,
                prefix=prefix, expanded=expanded,
            )
            if node.id == self.selected_id:
                row.is_selected = True
            self.mount(row)

        # Re-sort into depth-first order.
        self.sort_children(
            key=lambda w: order.get(w.node.id, 9999)
            if hasattr(w, 'node') else 9999
        )

        self._refresh_visibility()

    def update_node_label(self, node_id: str, label: str) -> None:
        """Update the display label of a node in-place (no full rebuild)."""
        if node_id not in self._node_map:
            return
        self._node_map[node_id].label = label
        for row in self.query(TreeRow):
            if row.node.id == node_id:
                row.set_expanded(row.expanded)  # forces label re-render

    def select_node(self, node_id: str) -> None:
        """Programmatically select a node by id."""
        if node_id not in self._node_map:
            return
        self.selected_id = node_id
        self._update_selection()
        node = self._node_map[node_id]
        self.post_message(NodeSelected(node_id, node))

    def expand_node(self, node_id: str) -> None:
        """Expand a branch node, revealing its descendants.

        If the node is lazy (``loaded=False``), posts
        :class:`NodeNeedsChildren` instead of expanding.

        Removes the node from ``_user_collapsed`` so that
        :meth:`restore_expand_state` will keep it expanded.
        """
        if node_id not in self._node_map:
            return
        node = self._node_map[node_id]
        # Lazy node: request children instead of expanding
        if not node.loaded:
            self.post_message(NodeNeedsChildren(node_id, node))
            return
        if not node.children:
            return
        if node_id in self._expanded:
            return
        self._expanded.add(node_id)
        self._user_collapsed.discard(node_id)
        self._refresh_visibility()
        self.post_message(NodeToggled(node_id, node, True))

    def collapse_node(self, node_id: str) -> None:
        """Collapse a branch node, hiding its descendants.

        Records the collapse in ``_user_collapsed`` so that
        :meth:`restore_expand_state` can preserve the user's choice
        across rebuilds.
        """
        if node_id not in self._expanded:
            return
        self._expanded.discard(node_id)
        self._user_collapsed.add(node_id)
        self._refresh_visibility()
        node = self._node_map[node_id]
        self.post_message(NodeToggled(node_id, node, False))

    def toggle_node(self, node_id: str) -> None:
        """Toggle expand/collapse for a branch node."""
        if node_id in self._expanded:
            self.collapse_node(node_id)
        else:
            self.expand_node(node_id)

    def expand_all(self) -> None:
        """Expand every branch node in the tree.

        Clears ``_user_collapsed`` since the user's intent is to
        see everything.
        """
        for node_id, node in self._node_map.items():
            if node.children and node.loaded:
                self._expanded.add(node_id)
        self._user_collapsed.clear()
        self._refresh_visibility()

    def restore_expand_state(self) -> None:
        """Expand all branch nodes except those the user has manually collapsed.

        Called after a :meth:`rebuild` to restore the visual state.
        New nodes (not previously in the tree) are expanded by default;
        nodes the user manually collapsed stay collapsed.

        This is the preferred alternative to :meth:`expand_all` when you
        want to respect user collapse decisions across rebuilds.
        """
        # Remove stale IDs (nodes that no longer exist in the tree).
        self._user_collapsed &= set(self._node_map.keys())

        # Start fresh: expand every branch node.
        for node_id, node in self._node_map.items():
            if node.children or not node.loaded:
                self._expanded.add(node_id)

        # Then collapse any that the user manually collapsed.
        self._expanded -= self._user_collapsed
        self._refresh_visibility()

    def is_expanded(self, node_id: str) -> bool:
        return node_id in self._expanded

    def is_user_collapsed(self, node_id: str) -> bool:
        """Return True if the node has been manually collapsed by the user.

        User collapses persist across :meth:`rebuild` calls via
        ``_user_collapsed``.  Use this to check whether a force-expand
        would override the user's explicit choice.
        """
        return node_id in self._user_collapsed

    # ------------------------------------------------------------------
    # Mount / rebuild internals
    # ------------------------------------------------------------------

    def on_mount(self) -> None:
        self._mount_all_rows()
        self._refresh_visibility()

    def _build_node_map(self, node: TreeNode) -> None:
        self._node_map[node.id] = node
        for child in node.children:
            self._build_node_map(child)

    def _compute_prefixes(self) -> dict[str, str]:
        """Compute box-drawing tree-line prefixes for every node.

        Uses ``│   `` for ancestor levels with more siblings below,
        ``    `` for ancestor levels that were the last sibling,
        ``├── `` for non-last children, and ``└── `` for last children.

        The root node has an empty prefix.
        """
        prefixes: dict[str, str] = {}
        # Root has no prefix
        prefixes[self._root.id] = ""

        def walk(parent: TreeNode, parent_indent: str) -> None:
            children = parent.children
            for i, child in enumerate(children):
                is_last = (i == len(children) - 1)
                connector = _LAST_BRANCH if is_last else _BRANCH
                prefixes[child.id] = parent_indent + connector
                # For grandchildren: vertical line or blank indent
                child_indent = parent_indent + (_INDENT if is_last else _LINE_VERTICAL)
                walk(child, child_indent)

        walk(self._root, "")
        return prefixes

    def _get_all_nodes_depth(self) -> list[tuple[TreeNode, int]]:
        """Walk the entire tree (ignoring expand state) and return
        (node, depth) for every node in depth-first order."""
        result: list[tuple[TreeNode, int]] = []

        def walk(node: TreeNode, depth: int) -> None:
            result.append((node, depth))
            for child in node.children:
                walk(child, depth + 1)

        walk(self._root, 0)
        return result

    def _get_visible_nodes(self) -> list[tuple[TreeNode, int]]:
        """Walk the tree respecting expand state; return (node, depth)
        for every visible node."""
        result: list[tuple[TreeNode, int]] = []

        def walk(node: TreeNode, depth: int) -> None:
            result.append((node, depth))
            if node.id in self._expanded:
                for child in node.children:
                    walk(child, depth + 1)

        walk(self._root, 0)
        return result

    def _mount_all_rows(self) -> None:
        """Mount a row for every node in the entire tree."""
        prefixes = self._compute_prefixes()
        order: dict[str, int] = {}
        for i, (node, depth) in enumerate(self._get_all_nodes_depth()):
            order[node.id] = i
            is_branch = bool(node.children) or not node.loaded
            prefix = prefixes.get(node.id, "")
            expanded = node.id in self._expanded
            row = TreeRow(
                node, depth=depth, is_branch=is_branch,
                prefix=prefix, expanded=expanded,
            )
            if node.id == self.selected_id:
                row.is_selected = True
            self.mount(row)

        # Sort into depth-first order.
        self.sort_children(
            key=lambda w: order.get(w.node.id, 9999)
            if hasattr(w, 'node') else 9999
        )

    def _remove_all_rows(self) -> None:
        for row in list(self.query(TreeRow)):
            row.remove()

    def _orphan_content_widgets(self) -> None:
        """Detach content and inline-edit widgets from rows so they aren't destroyed on remove."""
        for row in self.query(TreeRow):
            row.node.content = None
            row.node.inline_edit = None

    def _refresh_visibility(self) -> None:
        """Toggle the ``-hidden`` CSS class on every row based on
        the current expand state.  Also updates the ▼ / ▶ toggle
        indicator on branch rows.
        """
        visible_ids = {node.id for node, _ in self._get_visible_nodes()}
        for row in self.query(TreeRow):
            if row.node.id in visible_ids:
                row.remove_class("-hidden")
            else:
                row.add_class("-hidden")
            # Update ▼ / ▶ toggle on branch rows
            if row.is_branch:
                row.set_expanded(row.node.id in self._expanded)

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

    def on_tree_row_button_pressed(self, msg: TreeRow.ButtonPressed) -> None:
        """Re-bubble TreeRow.ButtonPressed so owners can listen.

        The message is NOT stopped — it bubbles up to the panel.
        """