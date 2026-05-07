"""Tests for the Tree and TreeRow widgets (ui/tree/).

After Step 15c: expand/collapse toggles a ``-hidden`` CSS class instead
of removing/re-mounting rows.  All rows are mounted once and stay in the
DOM; only their visibility changes.
"""

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
    TreeRow.-hidden {
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


def _visible_action_rows(tree: Tree) -> list[TreeRow]:
    """Return TreeRow widgets with buttons that are NOT hidden."""
    return [r for r in tree.query(TreeRow)
            if r.node.buttons and not r.has_class("-hidden")]


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

    async def test_row_uses_prefix_for_indent(self):
        """Row renders its prefix string before the label."""
        node = TreeNode("x", "Deep")
        row = TreeRow(node, depth=3, is_branch=False, prefix="│       ")

        app = App()
        async with app.run_test() as pilot:
            await pilot.app.mount(row)
            await pilot.pause()
            statics = row.query(Static)
            plain = statics[0].render().plain
            assert plain.startswith("│")
            assert "Deep" in plain

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

    async def test_row_with_content_still_shows_prefix(self):
        """Even with content widget, prefix is rendered."""
        content_widget = Label("Content")
        node = TreeNode("x", "Label", content=content_widget)
        row = TreeRow(node, depth=2, is_branch=False, prefix="├── ")

        app = App()
        async with app.run_test() as pilot:
            await pilot.app.mount(row)
            await pilot.pause()
            statics = row.query(Static)
            # First static contains the prefix + label
            assert len(statics) >= 1
            plain = statics[0].render().plain
            assert plain.startswith("├──")
            assert "Label" in plain

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
        row = TreeRow(node, depth=0, is_branch=True, expanded=False)

        app = App()
        async with app.run_test() as pilot:
            await pilot.app.mount(row)
            await pilot.pause()
            statics = row.query(Static)
            assert "\u25b6" in statics[0].render().plain  # ▶ collapsed

    async def test_row_toggle_updates_on_expand(self):
        """set_expanded(True) changes the indicator to ▼."""
        node = TreeNode("x", "Branch", children=[TreeNode("c", "Child")])
        row = TreeRow(node, depth=0, is_branch=True, expanded=False)

        app = App()
        async with app.run_test() as pilot:
            await pilot.app.mount(row)
            await pilot.pause()
            statics = row.query(Static)
            assert "\u25b6" in statics[0].render().plain  # ▶ collapsed

            row.set_expanded(True)
            await pilot.pause()
            assert "\u25bc" in statics[0].render().plain  # ▼ expanded

            row.set_expanded(False)
            await pilot.pause()
            assert "\u25b6" in statics[0].render().plain  # ▶ collapsed again

    async def test_row_leaf_has_no_toggle(self):
        """Leaf nodes do not show a toggle indicator."""
        node = TreeNode("x", "Leaf")
        row = TreeRow(node, depth=0, is_branch=False, prefix="├── ")

        app = App()
        async with app.run_test() as pilot:
            await pilot.app.mount(row)
            await pilot.pause()
            statics = row.query(Static)
            plain = statics[0].render().plain
            # No toggle character, just prefix + label
            assert plain.startswith("├── Leaf")


# ---------------------------------------------------------------------------
# Tree — prefix computation (box-drawing lines)
# ---------------------------------------------------------------------------


class TestTreePrefixes:
    def test_root_has_no_prefix(self):
        """Root node has an empty prefix."""
        root = _make_tree()
        tree = Tree(root)
        prefixes = tree._compute_prefixes()
        assert prefixes["root"] == ""

    def test_first_child_gets_branch(self):
        """First child (not last) gets ├── prefix."""
        root = _make_tree()
        tree = Tree(root)
        prefixes = tree._compute_prefixes()
        # 'a' is the first of two children of root, so ├──
        assert prefixes["a"].startswith("├──")

    def test_last_child_gets_last_branch(self):
        """Last child gets └── prefix."""
        root = _make_tree()
        tree = Tree(root)
        prefixes = tree._compute_prefixes()
        # 'b' is the last child of root
        assert prefixes["b"].startswith("└──")

    def test_grandchild_of_first_sibling_has_vertical_line(self):
        """Children of a non-last sibling have │ continuation."""
        root = _make_tree()
        tree = Tree(root)
        prefixes = tree._compute_prefixes()
        # a1 and a2 are under 'a' (not last sibling of root)
        # Their prefix should start with │
        assert prefixes["a1"].startswith("│")
        assert prefixes["a2"].startswith("│")

    def test_grandchild_of_last_sibling_has_indent(self):
        """Children of a last sibling use blank indent (no vertical line)."""
        root = TreeNode("root", "root", children=[
            TreeNode("a", "A", children=[
                TreeNode("a1", "A1"),
            ]),
        ])
        tree = Tree(root)
        prefixes = tree._compute_prefixes()
        # 'a' is the last (only) child of root, so a1's prefix uses
        # blank indent for the root level + └── for a1 itself
        assert prefixes["a1"] == "    └── "
        # 'a' itself is the last child, so it gets └──
        assert prefixes["a"].startswith("└──")

    def test_deep_nesting_prefixes(self):
        """Deep nesting creates proper stacked prefixes."""
        root = TreeNode("r", "R", children=[
            TreeNode("a", "A", children=[
                TreeNode("a1", "A1", children=[
                    TreeNode("deep", "Deep"),
                ]),
                TreeNode("a2", "A2"),
            ]),
            TreeNode("b", "B"),
        ])
        tree = Tree(root)
        prefixes = tree._compute_prefixes()
        # deep is under a1 (which is not last child of a? actually a2 exists)
        # a1 is first child of a, so deep gets │ prefix then └──
        assert "└──" in prefixes["deep"] or "├──" in prefixes["deep"]
        # The prefix for 'deep' should have the │ line from 'a' level
        # because 'a' is not the last sibling (b follows)

    async def test_tree_rows_have_box_drawing_prefixes(self):
        """Full tree renders with box-drawing prefixes on rows."""
        root = _make_tree()
        async with TreeTestApp(root).run_test() as pilot:
            tree = pilot.app.tree
            await pilot.pause()

            # Root row — branch node, expanded (has ▼ toggle)
            root_row = [r for r in tree.query(TreeRow) if r.node.id == "root"][0]
            label = root_row.label_text
            assert "root" in label
            assert "\u25bc" in label  # ▼ expanded
            # Root has no prefix (empty string)
            assert root_row.prefix == ""

    async def test_toggle_indicator_updates_on_expand_collapse(self):
        """Branch rows show ▼ when expanded and ▶ when collapsed."""
        root = _make_tree()
        async with TreeTestApp(root).run_test() as pilot:
            tree = pilot.app.tree
            await pilot.pause()

            a_row = [r for r in tree.query(TreeRow) if r.node.id == "a"][0]

            # Initially collapsed
            assert a_row.expanded is False
            label = a_row.label_text
            assert "\u25b6" in label  # ▶ collapsed

            # Expand
            tree.expand_node("a")
            await pilot.pause()
            assert a_row.expanded is True
            label = a_row.label_text
            assert "\u25bc" in label  # ▼ expanded

            # Collapse
            tree.collapse_node("a")
            await pilot.pause()
            assert a_row.expanded is False
            label = a_row.label_text
            assert "\u25b6" in label  # ▶ collapsed again


# ---------------------------------------------------------------------------
# Tree — rendering (CSS hide/show)
# ---------------------------------------------------------------------------


class TestTreeRendering:
    async def test_all_rows_mounted_on_start(self):
        """All nodes are mounted as rows, including initially hidden ones."""
        root = _make_tree()
        async with TreeTestApp(root).run_test() as pilot:
            tree = pilot.app.tree
            await pilot.pause()

            # All 5 nodes should have rows (root, A, A1, A2, B).
            all_rows = tree.query(TreeRow)
            assert len(all_rows) == 5

    async def test_initially_only_root_and_direct_children_visible(self):
        """Hidden rows have the -hidden class."""
        root = _make_tree()
        async with TreeTestApp(root).run_test() as pilot:
            tree = pilot.app.tree
            await pilot.pause()

            # root + A + B = 3 visible; A1, A2 are hidden
            assert len(_visible_rows(tree)) == 3

            hidden = [r for r in tree.query(TreeRow) if r.has_class("-hidden")]
            assert len(hidden) == 2
            hidden_ids = {r.node.id for r in hidden}
            assert hidden_ids == {"a1", "a2"}

    async def test_expand_reveals_children(self):
        """Expanding removes -hidden from children."""
        root = _make_tree()
        async with TreeTestApp(root).run_test() as pilot:
            tree = pilot.app.tree
            await pilot.pause()

            tree.expand_node("a")
            await pilot.pause()

            assert len(_visible_rows(tree)) == 5
            # No rows should be hidden.
            hidden = [r for r in tree.query(TreeRow) if r.has_class("-hidden")]
            assert len(hidden) == 0

    async def test_collapse_hides_children(self):
        """Collapsing adds -hidden to children."""
        root = _make_tree()
        async with TreeTestApp(root).run_test() as pilot:
            tree = pilot.app.tree
            await pilot.pause()

            tree.expand_node("a")
            await pilot.pause()
            tree.collapse_node("a")
            await pilot.pause()

            assert len(_visible_rows(tree)) == 3
            hidden = [r for r in tree.query(TreeRow) if r.has_class("-hidden")]
            hidden_ids = {r.node.id for r in hidden}
            assert hidden_ids == {"a1", "a2"}

    async def test_expand_all_shows_everything(self):
        """expand_all reveals every node."""
        root = _make_tree()
        async with TreeTestApp(root).run_test() as pilot:
            tree = pilot.app.tree
            tree.expand_all()
            await pilot.pause()

            assert len(_visible_rows(tree)) == 5
            hidden = [r for r in tree.query(TreeRow) if r.has_class("-hidden")]
            assert len(hidden) == 0

    async def test_nested_expand_and_collapse(self):
        """Deep nesting: collapsing a parent hides all descendants."""
        root = TreeNode("root", "root", children=[
            TreeNode("a", "A", children=[
                TreeNode("a1", "A1", children=[
                    TreeNode("a1a", "A1a"),
                ]),
            ]),
        ])
        async with TreeTestApp(root).run_test() as pilot:
            tree = pilot.app.tree
            await pilot.pause()

            # Expand all
            tree.expand_node("a")
            await pilot.pause()
            tree.expand_node("a1")
            await pilot.pause()

            assert len(_visible_rows(tree)) == 4  # root, A, A1, A1a

            # Collapse A — hides A1 and A1a, but A itself stays visible.
            tree.collapse_node("a")
            await pilot.pause()

            # root and A are visible (branch node stays visible when collapsed)
            assert len(_visible_rows(tree)) == 2

            hidden = [r for r in tree.query(TreeRow) if r.has_class("-hidden")]
            hidden_ids = {r.node.id for r in hidden}
            assert hidden_ids == {"a1", "a1a"}

    async def test_content_visible_after_expand(self):
        """Content widgets on descendant rows become visible on expand."""
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
            await pilot.pause()

            labels = tree.query(Label)
            label_texts = [l.render().plain for l in labels]
            assert any("A1 content" in t for t in label_texts)
            assert any("B content" in t for t in label_texts)

    async def test_content_widget_survives_collapse_and_reexpand(self):
        """Content widgets stay mounted through collapse/expand cycles.

        No PersistentMarkdown hack needed — the widget is never unmounted.
        """
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

            # Verify the Markdown exists and has our content.
            markdowns = tree.query(Markdown)
            assert len(markdowns) == 1
            assert markdowns[0].id == "survivor-md"

            # Collapse then re-expand — same widget instance should survive.
            tree.collapse_node("a")
            await pilot.pause()
            tree.expand_node("a")
            await pilot.pause()
            await pilot.pause()

            markdowns2 = tree.query(Markdown)
            assert len(markdowns2) == 1
            assert markdowns2[0].id == "survivor-md"
            # Same instance — never was destroyed.
            assert markdowns2[0] is md


# ---------------------------------------------------------------------------
# Tree — navigation
# ---------------------------------------------------------------------------


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
            assert len(_visible_rows(tree)) == 5

            tree.toggle_node("a")
            await pilot.pause()
            assert tree.is_expanded("a") is False
            assert len(_visible_rows(tree)) == 3

    async def test_select_hidden_node_still_works(self):
        """A hidden node can still be selected (row exists, just not displayed)."""
        root = _make_tree()
        async with TreeTestApp(root).run_test() as pilot:
            tree = pilot.app.tree
            await pilot.pause()

            # a1 is hidden but its row exists.
            tree.select_node("a1")
            assert tree.selected_id == "a1"


# ---------------------------------------------------------------------------
# Tree — events
# ---------------------------------------------------------------------------


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
            assert len(_visible_rows(tree)) == 5


# ---------------------------------------------------------------------------
# Tree — rebuild (structural changes)
# ---------------------------------------------------------------------------


class TestTreeRebuild:
    async def test_rebuild_preserves_expanded_state(self):
        """rebuild() does NOT reset the expand state — set_root() does."""
        root = _make_tree()
        async with TreeTestApp(root).run_test() as pilot:
            tree = pilot.app.tree
            tree.expand_node("a")
            await pilot.pause()
            assert tree.is_expanded("a")

            # rebuild should keep "a" expanded
            tree.rebuild()
            await pilot.pause()
            assert tree.is_expanded("a")

            # set_root should reset — only root expanded
            tree.set_root(tree.root)
            await pilot.pause()
            assert not tree.is_expanded("a")
            assert tree.is_expanded("root")

    async def test_rebuild_preserves_existing_rows(self):
        """rebuild() preserves existing rows and adds new ones."""
        root = _make_tree()
        async with TreeTestApp(root).run_test() as pilot:
            tree = pilot.app.tree
            tree.expand_node("a")
            await pilot.pause()

            # Capture existing row instances.
            original_rows = list(tree.query(TreeRow))
            assert len(original_rows) == 5

            # rebuild with same tree — all rows preserved.
            tree.rebuild()
            await pilot.pause()

            new_rows = list(tree.query(TreeRow))
            assert len(new_rows) == 5

            # Same instances survive (hybrid rebuild preserves existing rows).
            for orig in original_rows:
                assert orig in new_rows

            # Visibility is preserved.
            assert len(_visible_rows(tree)) == 5

    async def test_rebuild_after_adding_child(self):
        """Adding a child then rebuild() shows the new node."""
        md = Markdown("# Test", id="test-md")
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

            # Content widget is present.
            assert len(tree.query(Markdown)) == 1

            # Add a new child in the data model.
            tree._node_map["a"].children.append(TreeNode("new", "New child"))
            tree.rebuild()
            await pilot.pause()
            await pilot.pause()

            assert "new" in {r.node.id for r in tree.query(TreeRow)}
            # Content widget survives rebuild (hybrid approach preserves existing rows).
            assert len(tree.query(Markdown)) == 1

    async def test_set_root_remounts_all_rows(self):
        """set_root() re-mounts all rows and resets expand state."""
        root = _make_tree()
        async with TreeTestApp(root).run_test() as pilot:
            tree = pilot.app.tree
            tree.expand_node("a")
            await pilot.pause()

            tree.set_root(tree.root)
            await pilot.pause()

            # All rows re-mounted.
            all_rows = tree.query(TreeRow)
            assert len(all_rows) == 5
            # Expand state reset.
            assert not tree.is_expanded("a")
            assert tree.is_expanded("root")
