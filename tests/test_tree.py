"""Tests for the Tree and TreeRow widgets (ui/tree/)."""

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Label

from ui.tree.tree import Tree, TreeNode, NodeSelected, NodeToggled
from ui.tree.tree_row import TreeRow


# ---------------------------------------------------------------------------
# Test app
# ---------------------------------------------------------------------------


class TreeTestApp(App):
    """Minimal app hosting a Tree for testing."""

    CSS = """
    Tree {
        height: 100%;
        width: 100%;
    }
    """

    def __init__(self, root: TreeNode):
        super().__init__()
        self._root = root

    def compose(self) -> ComposeResult:
        self.tree_widget = Tree(self._root)
        yield self.tree_widget

    @property
    def tree(self) -> Tree:
        return self.tree_widget


def _make_tree():
    """Build a simple tree for tests:
    root
    ├── A
    │   ├── A1
    │   └── A2
    └── B
    """
    return TreeNode("root", "root", children=[
        TreeNode("a", "Node A", children=[
            TreeNode("a1", "A.1"),
            TreeNode("a2", "A.2"),
        ]),
        TreeNode("b", "Node B"),
    ])


# ---------------------------------------------------------------------------
# TreeNode
# ---------------------------------------------------------------------------


class TestTreeNode:
    def test_node_attributes(self):
        node = TreeNode("x", "Label X", data={"key": "val"})
        assert node.id == "x"
        assert node.label == "Label X"
        assert node.data == {"key": "val"}
        assert node.children == []

    def test_node_with_children(self):
        child = TreeNode("c", "Child")
        parent = TreeNode("p", "Parent", children=[child])
        assert len(parent.children) == 1
        assert parent.children[0].id == "c"


# ---------------------------------------------------------------------------
# TreeRow
# ---------------------------------------------------------------------------


class TestTreeRow:
    async def test_row_renders_label(self):
        """A TreeRow displays its label."""
        node = TreeNode("x", "Hello")
        row = TreeRow(node, depth=0, is_branch=False)

        app = App()
        async with app.run_test() as pilot:
            await pilot.app.mount(row)
            await pilot.pause()
            rendered = row.render()
            assert "Hello" in rendered.plain

    async def test_row_shows_expand_indicator_for_branch(self):
        """Branch nodes show an expand/collapse indicator."""
        node = TreeNode("x", "Branch", children=[TreeNode("c", "Child")])
        row = TreeRow(node, depth=0, is_branch=True)

        app = App()
        async with app.run_test() as pilot:
            await pilot.app.mount(row)
            await pilot.pause()
            rendered = row.render()
            # Should show some expand indicator
            assert "▶" in rendered.plain

    async def test_row_indent_increases_with_depth(self):
        """Deeper rows have more indentation."""
        node = TreeNode("x", "Deep")
        row = TreeRow(node, depth=3, is_branch=False)

        app = App()
        async with app.run_test() as pilot:
            await pilot.app.mount(row)
            await pilot.pause()
            rendered = row.render()
            # Should start with spaces for indent
            plain = rendered.plain
            # At least some indentation
            assert plain.startswith(" ") or "    " in plain


# ---------------------------------------------------------------------------
# Tree
# ---------------------------------------------------------------------------


class TestTreeRendering:
    async def test_tree_renders_all_visible_nodes(self):
        """Initially, root + direct children are visible, deeper children hidden."""
        root = _make_tree()
        async with TreeTestApp(root).run_test() as pilot:
            tree = pilot.app.tree
            await pilot.pause()

            rows = tree.query(TreeRow)
            # root + A + B = 3 visible (A1, A2 hidden until A expanded)
            assert len(rows) == 3

    async def test_expand_shows_children(self):
        """Expanding a branch reveals its children."""
        root = _make_tree()
        async with TreeTestApp(root).run_test() as pilot:
            tree = pilot.app.tree
            await pilot.pause()

            tree.expand_node("a")
            await pilot.pause()

            rows = tree.query(TreeRow)
            # root + A + A1 + A2 + B = 5
            assert len(rows) == 5

    async def test_collapse_hides_children(self):
        """Collapsing a branch hides its children."""
        root = _make_tree()
        async with TreeTestApp(root).run_test() as pilot:
            tree = pilot.app.tree
            await pilot.pause()

            tree.expand_node("a")
            await pilot.pause()
            tree.collapse_node("a")
            await pilot.pause()

            rows = tree.query(TreeRow)
            assert len(rows) == 3

    async def test_expand_all_shows_everything(self):
        """expand_all reveals the entire tree."""
        root = _make_tree()
        async with TreeTestApp(root).run_test() as pilot:
            tree = pilot.app.tree
            tree.expand_all()
            await pilot.pause()

            rows = tree.query(TreeRow)
            assert len(rows) == 5


class TestTreeNavigation:
    async def test_select_node_by_id(self):
        """select_node changes the selected node."""
        root = _make_tree()
        async with TreeTestApp(root).run_test() as pilot:
            tree = pilot.app.tree
            await pilot.pause()

            tree.select_node("a")
            assert tree.selected_id == "a"

    async def test_selected_node_has_focus_style(self):
        """The selected node's row has a highlighted style."""
        root = _make_tree()
        async with TreeTestApp(root).run_test() as pilot:
            tree = pilot.app.tree
            await pilot.pause()

            tree.select_node("a")
            await pilot.pause()

            rows = tree.query(TreeRow)
            selected = [r for r in rows if r.is_selected]
            assert len(selected) == 1
            assert selected[0].node.id == "a"

    async def test_select_nonexistent_node_ignored(self):
        """select_node with an invalid id does nothing."""
        root = _make_tree()
        async with TreeTestApp(root).run_test() as pilot:
            tree = pilot.app.tree
            tree.select_node("nonexistent")
            assert tree.selected_id is None or tree.selected_id == "root"

    async def test_toggle_node_expands_and_collapses(self):
        """toggle_node flips expand state."""
        root = _make_tree()
        async with TreeTestApp(root).run_test() as pilot:
            tree = pilot.app.tree
            await pilot.pause()

            tree.toggle_node("a")
            await pilot.pause()
            assert tree.is_expanded("a") is True
            assert len(tree.query(TreeRow)) == 5

            tree.toggle_node("a")
            await pilot.pause()
            assert tree.is_expanded("a") is False
            assert len(tree.query(TreeRow)) == 3


class TestTreeEvents:
    async def test_node_selected_updates_selected_id(self):
        """select_node updates selected_id and highlights the row."""
        root = _make_tree()
        async with TreeTestApp(root).run_test() as pilot:
            tree = pilot.app.tree
            await pilot.pause()

            tree.select_node("b")
            await pilot.pause()

            assert tree.selected_id == "b"
            rows = tree.query(TreeRow)
            selected = [r for r in rows if r.is_selected]
            assert len(selected) == 1
            assert selected[0].node.id == "b"

    async def test_node_toggled_handled(self):
        """toggle_node flips expand state and child visibility."""
        root = _make_tree()
        async with TreeTestApp(root).run_test() as pilot:
            tree = pilot.app.tree
            await pilot.pause()

            assert not tree.is_expanded("a")
            tree.toggle_node("a")
            await pilot.pause()

            assert tree.is_expanded("a")
            # Children should now be visible
            rows = tree.query(TreeRow)
            assert len(rows) == 5  # root + A + A1 + A2 + B
