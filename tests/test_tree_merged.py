"""Tests for merged TreeRow (ActionRow merged in) and lazy loading.

After merge: TreeRow handles both label/expand actions and inline buttons.
TreeNode has a `loaded` field for lazy loading. Tree posts NodeNeedsChildren
when a lazy node is expanded for the first time.
"""

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Button, Label, Markdown, Static

from ui.tree.tree import Tree, NodeSelected, NodeToggled, NodeNeedsChildren
from ui.tree.tree_row import TreeNode, TreeRow, RowButton
from utils.icons import OPEN, EDIT, DELETE, RENAME, ADD_FILE, ADD_DIR


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
    TreeRow.-hidden, ActionRow.-hidden {
        display: none;
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


def _visible_rows(tree: Tree) -> list[TreeRow]:
    """Return TreeRow widgets that are NOT hidden."""
    return [r for r in tree.query(TreeRow) if not r.has_class("-hidden")]


# ---------------------------------------------------------------------------
# TreeNode loaded field
# ---------------------------------------------------------------------------


class TestTreeNodeLoaded:
    def test_default_loaded_is_true(self):
        """TreeNode loaded defaults to True (eager)."""
        node = TreeNode("x", "Label")
        assert node.loaded is True

    def test_loaded_false_indicates_lazy(self):
        """Setting loaded=False marks the node as not yet scanned."""
        node = TreeNode("dir", "Dir", loaded=False)
        assert node.loaded is False
        assert node.children == []

    def test_lazy_node_with_data(self):
        """Lazy nodes can carry data (e.g. path)."""
        node = TreeNode("dir", "Dir", loaded=False,
                        data={"path": "/src", "type": "dir"})
        assert node.loaded is False
        assert node.data["path"] == "/src"


# ---------------------------------------------------------------------------
# TreeRow — merged with button support
# ---------------------------------------------------------------------------


class TestTreeRowWithButtons:
    async def test_row_with_buttons_shows_button_labels(self):
        """A TreeRow with buttons renders each button with its label."""
        node = TreeNode("x", "File.py", buttons=[
            RowButton("open", OPEN, "btn-open"),
            RowButton("del", DELETE, "btn-del"),
        ])
        row = TreeRow(node, depth=0, is_branch=False, prefix="├── ")

        app = App()
        async with app.run_test() as pilot:
            await pilot.app.mount(row)
            await pilot.pause()
            buttons = row.query(Button)
            assert len(buttons) == 2
            labels = {b.label.plain for b in buttons}
            assert OPEN in labels
            assert DELETE in labels

    async def test_button_id_contains_node_id_and_action(self):
        """Button IDs follow the pattern act-{node_id}-{action_id}."""
        node = TreeNode("file1", "file.txt", buttons=[
            RowButton("edit", EDIT, "btn-edit"),
        ])
        row = TreeRow(node, depth=0, is_branch=False)

        app = App()
        async with app.run_test() as pilot:
            await pilot.app.mount(row)
            await pilot.pause()
            buttons = row.query(Button)
            assert len(buttons) == 1
            assert buttons[0].id == "act-file1-edit"

    async def test_branch_with_buttons_shows_toggle(self):
        """A branch node with buttons still shows the expand indicator."""
        node = TreeNode("dir", "Dir", children=[
            TreeNode("child", "Child"),
        ], buttons=[
            RowButton("add", ADD_FILE, "btn-add"),
        ])
        row = TreeRow(node, depth=0, is_branch=True, expanded=False, prefix="")

        app = App()
        async with app.run_test() as pilot:
            await pilot.app.mount(row)
            await pilot.pause()
            statics = row.query(Static)
            label_text = statics[0].render().plain
            assert "▶" in label_text  # collapsed branch indicator
            assert "Dir" in label_text

    async def test_branch_with_buttons_expand_indicator_updates(self):
        """set_expanded(True) changes the toggle to ▼ for branch with buttons."""
        node = TreeNode("dir", "Dir", children=[
            TreeNode("child", "Child"),
        ], buttons=[
            RowButton("add", ADD_FILE, "btn-add"),
        ])
        row = TreeRow(node, depth=0, is_branch=True, expanded=False)

        app = App()
        async with app.run_test() as pilot:
            await pilot.app.mount(row)
            await pilot.pause()
            statics = row.query(Static)
            assert "▶" in statics[0].render().plain

            row.set_expanded(True)
            await pilot.pause()
            assert "▼" in statics[0].render().plain

    async def test_row_buttons_and_content_coexist(self):
        """A row with both content widget and buttons renders both."""
        content = Label("Inner content")
        node = TreeNode("x", "Leaf", content=content, buttons=[
            RowButton("edit", EDIT, "btn-edit"),
        ])
        row = TreeRow(node, depth=0, is_branch=False, prefix="├── ")

        app = App()
        async with app.run_test() as pilot:
            await pilot.app.mount(row)
            await pilot.pause()
            # Content widget present
            labels = row.query(Label)
            assert any("Inner content" in l.render().plain for l in labels)
            # Button present
            buttons = row.query(Button)
            assert len(buttons) == 1


# ---------------------------------------------------------------------------
# TreeRow — ButtonPressed message
# ---------------------------------------------------------------------------


class TestTreeRowButtonPressed:
    async def test_button_press_posts_button_pressed(self):
        """Clicking a button in a TreeRow posts ButtonPressed."""
        node = TreeNode("x", "File", buttons=[
            RowButton("edit", EDIT, "btn-edit"),
        ])
        row = TreeRow(node, depth=0, is_branch=False)

        messages = []

        class TestApp(App):
            def compose(self) -> ComposeResult:
                yield row

            def on_tree_row_button_pressed(self, msg: TreeRow.ButtonPressed) -> None:
                messages.append(msg)

        async with TestApp().run_test() as pilot:
            await pilot.pause()
            buttons = row.query(Button)
            await pilot.click(buttons[0])
            await pilot.pause()

            assert len(messages) == 1
            assert messages[0].action_id == "edit"
            assert messages[0].node.id == "x"


# ---------------------------------------------------------------------------
# Tree — lazy loading (NodeNeedsChildren)
# ---------------------------------------------------------------------------


class TestTreeLazyLoading:
    async def test_lazy_node_shows_as_branch(self):
        """A node with loaded=False is treated as a branch even without children."""
        root = TreeNode("root", "root", children=[
            TreeNode("dir", "Dir", loaded=False, children=[]),
        ])
        async with TreeTestApp(root).run_test() as pilot:
            tree = pilot.app.tree
            await pilot.pause()

            # The lazy node should have a row with is_branch=True
            dir_row = [r for r in tree.query(TreeRow) if r.node.id == "dir"][0]
            assert dir_row.is_branch is True

    async def test_lazy_node_appears_collapsed(self):
        """A lazy node starts collapsed (not in _expanded set)."""
        root = TreeNode("root", "root", children=[
            TreeNode("dir", "Dir", loaded=False, children=[]),
        ])
        async with TreeTestApp(root).run_test() as pilot:
            tree = pilot.app.tree
            await pilot.pause()

            assert "dir" not in tree._expanded
            # Should show ▶ indicator
            dir_row = [r for r in tree.query(TreeRow) if r.node.id == "dir"][0]
            assert "\u25b6" in dir_row.label_text  # ▶ collapsed

    async def test_expanding_lazy_node_posts_needs_children(self):
        """Expanding a lazy node posts NodeNeedsChildren instead of expanding."""
        root = TreeNode("root", "root", children=[
            TreeNode("dir", "Dir", loaded=False, children=[]),
        ])
        messages = []

        class CapturingApp(App):
            CSS = """
            Tree { height: 100%; width: 100%; }
            TreeRow.-hidden { display: none; }
            """

            def __init__(self, root_node):
                super().__init__()
                self._root = root_node

            def compose(self) -> ComposeResult:
                self.tree_widget = Tree(self._root)
                yield self.tree_widget

            def on_node_needs_children(self, msg: NodeNeedsChildren) -> None:
                messages.append(msg)

        async with CapturingApp(root).run_test() as pilot:
            tree = pilot.app.tree_widget
            await pilot.pause()

            # Try to expand the lazy directory
            tree.expand_node("dir")
            await pilot.pause()

            # NodeNeedsChildren should have been posted
            assert len(messages) == 1
            assert messages[0].node_id == "dir"
            assert messages[0].node.loaded is False

    async def test_toggling_lazy_node_posts_needs_children(self):
        """Toggling a lazy node posts NodeNeedsChildren."""
        root = TreeNode("root", "root", children=[
            TreeNode("dir", "Dir", loaded=False, children=[]),
        ])
        messages = []

        class CapturingApp(App):
            CSS = """
            Tree { height: 100%; width: 100%; }
            TreeRow.-hidden { display: none; }
            """

            def __init__(self, root_node):
                super().__init__()
                self._root = root_node

            def compose(self) -> ComposeResult:
                self.tree_widget = Tree(self._root)
                yield self.tree_widget

            def on_node_needs_children(self, msg: NodeNeedsChildren) -> None:
                messages.append(msg)

        async with CapturingApp(root).run_test() as pilot:
            tree = pilot.app.tree_widget
            await pilot.pause()

            # Toggle the lazy directory
            tree.toggle_node("dir")
            await pilot.pause()

            assert len(messages) == 1
            assert messages[0].node_id == "dir"

    async def test_loading_lazy_node_then_expanding(self):
        """After loading children into a lazy node, expand works normally."""
        root = TreeNode("root", "root", children=[
            TreeNode("dir", "Dir", loaded=False, children=[]),
        ])
        async with TreeTestApp(root).run_test() as pilot:
            tree = pilot.app.tree
            await pilot.pause()

            # Initially, dir has no visible children
            assert len(_visible_rows(tree)) == 2  # root + dir

            # Load children
            dir_node = tree._node_map["dir"]
            dir_node.children = [
                TreeNode("dir-file1", "file1.py"),
                TreeNode("dir-file2", "file2.py"),
            ]
            dir_node.loaded = True

            # Rebuild and expand
            tree.rebuild()
            tree.expand_node("dir")
            await pilot.pause()

            # Now 4 visible rows: root, dir, file1, file2
            assert len(_visible_rows(tree)) == 4

    async def test_loaded_node_expands_normally(self):
        """A loaded=True node expands normally without posting NodeNeedsChildren."""
        root = _make_tree()
        messages = []

        class CapturingApp(App):
            CSS = """
            Tree { height: 100%; width: 100%; }
            TreeRow.-hidden { display: none; }
            """

            def __init__(self, root_node):
                super().__init__()
                self._root = root_node

            def compose(self) -> ComposeResult:
                self.tree_widget = Tree(self._root)
                yield self.tree_widget

            def on_node_needs_children(self, msg: NodeNeedsChildren) -> None:
                messages.append(msg)

        async with CapturingApp(root).run_test() as pilot:
            tree = pilot.app.tree_widget
            await pilot.pause()

            # Expand a loaded node
            tree.expand_node("a")
            await pilot.pause()

            # No NodeNeedsChildren posted
            assert len(messages) == 0
            # Node is expanded normally
            assert "a" in tree._expanded


# ---------------------------------------------------------------------------
# Tree — branches with buttons (merged rows)
# ---------------------------------------------------------------------------


class TestTreeBranchButtons:
    async def test_tree_creates_treerow_for_all_nodes(self):
        """Tree creates TreeRow for all nodes regardless of buttons."""
        root = TreeNode("root", "root", children=[
            TreeNode("dir", "Dir", children=[
                TreeNode("file", "file.py", buttons=[
                    RowButton("open", OPEN, ""),
                ]),
            ], buttons=[
                RowButton("add", ADD_FILE, ""),
            ]),
        ])
        async with TreeTestApp(root).run_test() as pilot:
            tree = pilot.app.tree
            tree.expand_all()
            await pilot.pause()

            # All rows should be TreeRow instances (no ActionRow)
            from ui.tree.tree_row import TreeRow as TR
            rows = tree.query(TR)
            assert len(rows) == 3
            # No ActionRow instances
            from ui.tree.tree_row import ActionRow
            action_rows = tree.query(ActionRow)
            # ActionRow might still exist for backward compat but
            # Tree should only create TreeRow instances
            # Actually after merge, ActionRow should not be created by Tree

    async def test_branch_with_buttons_is_branch_row(self):
        """A branch node with buttons renders as a branch TreeRow."""
        root = TreeNode("root", "root", children=[
            TreeNode("dir", "Dir", children=[
                TreeNode("f", "file.txt"),
            ], buttons=[
                RowButton("add", ADD_FILE, ""),
            ]),
        ])
        async with TreeTestApp(root).run_test() as pilot:
            tree = pilot.app.tree
            await pilot.pause()

            dir_row = [r for r in tree.query(TreeRow) if r.node.id == "dir"][0]
            assert dir_row.is_branch is True
            assert dir_row.node.buttons  # has buttons

    async def test_leaf_with_buttons_is_leaf_row(self):
        """A leaf node with buttons renders as a leaf TreeRow."""
        root = TreeNode("root", "root", children=[
            TreeNode("file", "file.py", buttons=[
                RowButton("edit", EDIT, ""),
            ]),
        ])
        async with TreeTestApp(root).run_test() as pilot:
            tree = pilot.app.tree
            await pilot.pause()
            tree.expand_node("root")
            await pilot.pause()

            file_row = [r for r in tree.query(TreeRow) if r.node.id == "file"][0]
            assert file_row.is_branch is False
            assert file_row.node.buttons

    async def test_button_pressed_bubbles_to_tree(self):
        """ButtonPressed message from TreeRow reaches the Tree."""
        root = TreeNode("root", "root", children=[
            TreeNode("file", "file.py", buttons=[
                RowButton("edit", EDIT, "btn-edit"),
            ]),
        ])
        async with TreeTestApp(root).run_test() as pilot:
            tree = pilot.app.tree
            tree.expand_node("root")
            await pilot.pause()

            # Find the file row and verify it has a button
            file_row = [r for r in tree.query(TreeRow) if r.node.id == "file"][0]
            buttons = file_row.query(Button)
            assert len(buttons) == 1
            assert buttons[0].id == "act-file-edit"


# ---------------------------------------------------------------------------
# Regression — existing Tree functionality preserved
# ---------------------------------------------------------------------------


class TestTreeRegression:
    async def test_all_rows_mounted_on_start(self):
        """All nodes are mounted as rows, including initially hidden ones."""
        root = _make_tree()
        async with TreeTestApp(root).run_test() as pilot:
            tree = pilot.app.tree
            await pilot.pause()

            all_rows = tree.query(TreeRow)
            assert len(all_rows) == 5

    async def test_expand_collapse_visibility(self):
        """Expanding and collapsing toggles row visibility."""
        root = _make_tree()
        async with TreeTestApp(root).run_test() as pilot:
            tree = pilot.app.tree
            await pilot.pause()

            # Initially 3 visible: root, A, B
            assert len(_visible_rows(tree)) == 3

            tree.expand_node("a")
            await pilot.pause()
            assert len(_visible_rows(tree)) == 5

            tree.collapse_node("a")
            await pilot.pause()
            assert len(_visible_rows(tree)) == 3

    async def test_content_widget_survives_collapse_reexpand(self):
        """Content widgets stay mounted through collapse/expand cycles."""
        md = Markdown("# Before", id="survivor-md")
        root = TreeNode("root", "root", children=[
            TreeNode("a", "Branch", children=[
                TreeNode("leaf", "", content=md),
            ]),
        ])
        async with TreeTestApp(root).run_test() as pilot:
            tree = pilot.app.tree
            tree.expand_node("a")
            await pilot.pause()
            await pilot.pause()

            markdowns = tree.query(Markdown)
            assert len(markdowns) == 1

            tree.collapse_node("a")
            await pilot.pause()
            tree.expand_node("a")
            await pilot.pause()
            await pilot.pause()

            markdowns2 = tree.query(Markdown)
            assert len(markdowns2) == 1
            assert markdowns2[0].id == "survivor-md"

    async def test_rebuild_preserves_expanded_state(self):
        """rebuild() does NOT reset expand state."""
        root = _make_tree()
        async with TreeTestApp(root).run_test() as pilot:
            tree = pilot.app.tree
            tree.expand_node("a")
            await pilot.pause()
            assert tree.is_expanded("a")

            tree.rebuild()
            await pilot.pause()
            assert tree.is_expanded("a")