"""Tests for the Tree and TreeRow widgets (ui/tree/)."""

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Label, Markdown, Static

from ui.tree.tree import Tree, TreeNode, NodeSelected, NodeToggled
from ui.tree.tree_row import TreeRow, RowButton, ActionRow


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
        assert node.content is None

    def test_node_with_children(self):
        child = TreeNode("c", "Child")
        parent = TreeNode("p", "Parent", children=[child])
        assert len(parent.children) == 1
        assert parent.children[0].id == "c"

    def test_node_with_content_widget(self):
        """TreeNode accepts an optional content widget."""
        widget = Label("Hello, content!")
        node = TreeNode("x", "Label", content=widget)
        assert node.content is widget

    def test_node_with_content_and_children(self):
        """Node can have both content widget and children."""
        widget = Label("Branch content")
        child = TreeNode("c", "Child")
        node = TreeNode("b", "Branch", children=[child], content=widget)
        assert node.content is widget
        assert len(node.children) == 1

    def test_node_content_defaults_to_none(self):
        """content defaults to None when not specified."""
        node = TreeNode("x", "Label")
        assert node.content is None


# ---------------------------------------------------------------------------
# TreeRow
# ---------------------------------------------------------------------------


class TestTreeRow:
    async def test_row_composes_label_as_static(self):
        """A TreeRow composes its label as a Static widget."""
        node = TreeNode("x", "Hello")
        row = TreeRow(node, depth=0, is_branch=False)

        app = App()
        async with app.run_test() as pilot:
            await pilot.app.mount(row)
            await pilot.pause()
            statics = row.query(Static)
            assert len(statics) >= 1
            assert "Hello" in statics[0].render().plain

    async def test_row_shows_expand_indicator_for_branch(self):
        """Branch nodes show an expand/collapse indicator."""
        node = TreeNode("x", "Branch", children=[TreeNode("c", "Child")])
        row = TreeRow(node, depth=0, is_branch=True)

        app = App()
        async with app.run_test() as pilot:
            await pilot.app.mount(row)
            await pilot.pause()
            statics = row.query(Static)
            assert "▶" in statics[0].render().plain

    async def test_row_indent_increases_with_depth(self):
        """Deeper rows have more indentation."""
        node = TreeNode("x", "Deep")
        row = TreeRow(node, depth=3, is_branch=False)

        app = App()
        async with app.run_test() as pilot:
            await pilot.app.mount(row)
            await pilot.pause()
            statics = row.query(Static)
            plain = statics[0].render().plain
            assert plain.startswith("      ")  # 2 * 3 depth = 6 spaces

    async def test_row_with_content_mounts_widget(self):
        """When node has content, the widget is mounted in the row."""
        content_widget = Label("I am content!")
        node = TreeNode("x", "Label", content=content_widget)
        row = TreeRow(node, depth=1, is_branch=False)

        app = App()
        async with app.run_test() as pilot:
            await pilot.app.mount(row)
            await pilot.pause()

            # The content widget should be mounted as a child of the row
            labels = row.query(Label)
            content_labels = [l for l in labels if "I am content!" in l.render().plain]
            assert len(content_labels) == 1

    async def test_row_with_content_still_shows_indent(self):
        """Even with content widget, indent prefix is rendered."""
        content_widget = Label("Content")
        node = TreeNode("x", "Label", content=content_widget)
        row = TreeRow(node, depth=2, is_branch=False)

        app = App()
        async with app.run_test() as pilot:
            await pilot.app.mount(row)
            await pilot.pause()
            statics = row.query(Static)
            # First static is the indent prefix
            assert len(statics) >= 1
            plain = statics[0].render().plain
            assert plain.startswith("    ")  # 2 * 2 depth = 4 spaces

    async def test_row_with_markdown_content(self):
        """TreeRow can host a Markdown widget for streaming."""
        md = Markdown("# Hello\nWorld")
        node = TreeNode("x", "Response", content=md)
        row = TreeRow(node, depth=1, is_branch=False)

        app = App()
        async with app.run_test() as pilot:
            await pilot.app.mount(row)
            await pilot.pause()

            markdowns = row.query(Markdown)
            assert len(markdowns) == 1

    async def test_row_with_content_and_is_branch_shows_toggle(self):
        """Branch node with content still shows toggle indicator."""
        content_widget = Label("Content")
        node = TreeNode("x", "Branch", children=[TreeNode("c", "Child")],
                        content=content_widget)
        row = TreeRow(node, depth=0, is_branch=True)

        app = App()
        async with app.run_test() as pilot:
            await pilot.app.mount(row)
            await pilot.pause()
            statics = row.query(Static)
            assert "▶" in statics[0].render().plain


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

    async def test_tree_with_content_nodes(self):
        """Tree properly renders nodes that have content widgets."""
        content = Label("Leaf content")
        root = TreeNode("root", "root", children=[
            TreeNode("a", "Branch A", children=[
                TreeNode("a1", "Leaf", content=Label("A1 content")),
            ]),
            TreeNode("b", "Leaf B", content=Label("B content")),
        ])
        async with TreeTestApp(root).run_test() as pilot:
            tree = pilot.app.tree
            tree.expand_node("a")
            await pilot.pause()
            await pilot.pause()  # let DOM settle after async remove + rebuild

            rows = tree.query(TreeRow)
            assert len(rows) == 4  # root + a + a1 + b

            # Verify content labels are mounted inside the tree rows
            content_texts = []
            for row in rows:
                for child in row.children:
                    if isinstance(child, Label):
                        content_texts.append(child.render().plain)
            assert any("A1 content" in t for t in content_texts)
            assert any("B content" in t for t in content_texts)


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
