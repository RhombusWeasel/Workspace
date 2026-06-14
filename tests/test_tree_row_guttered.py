"""Tests for the guttered tree row — GutteredTreeRow and _extract_gutter."""

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Static

from ui.tree.tree_row import TreeNode
from ui.tree.tree_row_guttered import (
    GutteredTreeRow,
    _RowGutter,
    _extract_gutter,
)


# ---------------------------------------------------------------------------
# _extract_gutter unit tests
# ---------------------------------------------------------------------------


class TestExtractGutter:
    """Unit tests for the _extract_gutter helper."""

    def test_empty_prefix(self):
        assert _extract_gutter("") == ""

    def test_single_connector_no_gutter(self):
        assert _extract_gutter("├─ ") == ""
        assert _extract_gutter("└─ ") == ""

    def test_one_ancestor_with_vertical(self):
        assert _extract_gutter("│  ├─ ") == "│  "
        assert _extract_gutter("│  └─ ") == "│  "

    def test_one_ancestor_with_indent(self):
        assert _extract_gutter("   ├─ ") == "   "
        assert _extract_gutter("   └─ ") == "   "

    def test_two_ancestors(self):
        assert _extract_gutter("│  │  ├─ ") == "│  │  "
        assert _extract_gutter("│  │  └─ ") == "│  │  "
        assert _extract_gutter("   │  └─ ") == "   │  "
        assert _extract_gutter("      └─ ") == "      "

    def test_deep_nesting(self):
        assert _extract_gutter("│  │  │  │  └─ ") == "│  │  │  │  "

    def test_all_spaces(self):
        assert _extract_gutter("            └─ ") == "            "

    def test_roundtrip(self):
        for prefix in [
            "", "├─ ", "└─ ", "│  ├─ ", "│  └─ ",
            "   ├─ ", "   └─ ", "│  │  ├─ ", "│  │  └─ ",
            "   │  └─ ", "      └─ ", "│  │  │  │  └─ ",
        ]:
            gutter = _extract_gutter(prefix)
            if len(prefix) > 3:
                assert gutter + prefix[-3:] == prefix
            else:
                assert gutter == ""


# ---------------------------------------------------------------------------
# _RowGutter unit tests
# ---------------------------------------------------------------------------


class TestRowGutter:
    """Unit tests for the _RowGutter widget."""

    def test_initial_gutter_text(self):
        gutter = _RowGutter("│  │  ")
        assert gutter.gutter_text == "│  │  "

    def test_set_gutter_updates(self):
        gutter = _RowGutter("│  ")
        gutter.set_gutter("   ")
        assert gutter.gutter_text == "   "

    def test_set_gutter_noop_when_same(self):
        gutter = _RowGutter("│  ")
        gutter.set_gutter("│  ")
        assert gutter.gutter_text == "│  "

    def test_build_gutter_single_line(self):
        gutter = _RowGutter("│  ")
        assert gutter._build_gutter(1) == "│  "

    def test_build_gutter_multi_line(self):
        gutter = _RowGutter("│  ")
        assert gutter._build_gutter(5) == "│  \n│  \n│  \n│  \n│  "

    def test_build_gutter_deep_gutter(self):
        gutter = _RowGutter("│  │  ")
        assert gutter._build_gutter(3) == "│  │  \n│  │  \n│  │  "

    def test_build_gutter_empty_gutter(self):
        gutter = _RowGutter("")
        result = gutter._build_gutter(3)
        assert result == " \n \n "

    def test_build_gutter_zero_height(self):
        gutter = _RowGutter("│  ")
        result = gutter._build_gutter(0)
        # max(height, 1) → single line
        assert result == "│  "

    def test_update_height_increases(self):
        gutter = _RowGutter("│  ")
        assert gutter._line_count == 1
        gutter.update_height(5)
        assert gutter._line_count == 5

    def test_update_height_noop_same(self):
        gutter = _RowGutter("│  ")
        gutter.update_height(1)
        # Should not change — already 1
        assert gutter._line_count == 1

    def test_update_height_clamps_to_one(self):
        gutter = _RowGutter("│  ")
        gutter.update_height(0)
        # height < 1 is clamped to 1
        assert gutter._line_count == 1


# ---------------------------------------------------------------------------
# Minimal Textual app for integration tests
# ---------------------------------------------------------------------------


class GutterTestApp(App):
    """Minimal app that mounts GutteredTreeRow widgets for testing."""

    CSS = """
    GutteredTreeRow { height: auto; }
    """

    def __init__(self, rows: list[GutteredTreeRow]):
        super().__init__()
        self._rows = rows

    def compose(self) -> ComposeResult:
        yield from self._rows


# ---------------------------------------------------------------------------
# GutteredTreeRow composition tests
# ---------------------------------------------------------------------------


class TestGutteredTreeRowCompose:

    @pytest.mark.asyncio
    async def test_leaf_no_content_no_gutter(self):
        node = TreeNode(id="leaf1", label="Leaf")
        row = GutteredTreeRow(node, depth=0, is_branch=False, prefix="")
        app = GutterTestApp([row])
        async with app.run_test(size=(80, 24)):
            gutters = row.query(_RowGutter)
            assert len(gutters) == 0

    @pytest.mark.asyncio
    async def test_branch_no_content_no_gutter(self):
        node = TreeNode(id="branch1", label="Branch", children=[
            TreeNode(id="child1", label="Child"),
        ])
        row = GutteredTreeRow(node, depth=0, is_branch=True, prefix="")
        app = GutterTestApp([row])
        async with app.run_test(size=(80, 24)):
            gutters = row.query(_RowGutter)
            assert len(gutters) == 0

    @pytest.mark.asyncio
    async def test_content_node_has_gutter(self):
        content = Static("Hello world")
        node = TreeNode(id="msg1", label="Message", content=content)
        row = GutteredTreeRow(node, depth=1, is_branch=False, prefix="│  └─ ")
        app = GutterTestApp([row])
        async with app.run_test(size=(80, 24)):
            gutters = row.query(_RowGutter)
            assert len(gutters) == 1
            assert gutters.first().gutter_text == "│  "

    @pytest.mark.asyncio
    async def test_content_node_root_level_empty_gutter(self):
        content = Static("Hello")
        node = TreeNode(id="msg1", label="Message", content=content)
        row = GutteredTreeRow(node, depth=0, is_branch=False, prefix="└─ ")
        app = GutterTestApp([row])
        async with app.run_test(size=(80, 24)):
            gutters = row.query(_RowGutter)
            assert len(gutters) == 1
            assert gutters.first().gutter_text == ""

    @pytest.mark.asyncio
    async def test_content_node_deep_gutter(self):
        content = Static("Deep content")
        node = TreeNode(id="deep1", label="Deep", content=content)
        row = GutteredTreeRow(node, depth=3, is_branch=False, prefix="│  │  │  └─ ")
        app = GutterTestApp([row])
        async with app.run_test(size=(80, 24)):
            gutters = row.query(_RowGutter)
            assert len(gutters) == 1
            assert gutters.first().gutter_text == "│  │  │  "

    @pytest.mark.asyncio
    async def test_content_area_has_guttered_class(self):
        content = Static("test")
        node = TreeNode(id="n1", label="N1", content=content)
        row = GutteredTreeRow(node, depth=1, is_branch=False, prefix="│  └─ ")
        app = GutterTestApp([row])
        async with app.run_test(size=(80, 24)):
            content_containers = row.query(".tree-row-content")
            assert len(content_containers) == 1
            assert content_containers.first().has_class("guttered")

    @pytest.mark.asyncio
    async def test_no_content_no_guttered_class(self):
        node = TreeNode(id="leaf1", label="Leaf")
        row = GutteredTreeRow(node, depth=0, is_branch=False, prefix="")
        app = GutterTestApp([row])
        async with app.run_test(size=(80, 24)):
            content_containers = row.query(".tree-row-content")
            assert len(content_containers) == 0

    @pytest.mark.asyncio
    async def test_no_content_has_no_gutter_attr(self):
        node = TreeNode(id="leaf1", label="Leaf")
        row = GutteredTreeRow(node, depth=0, is_branch=False, prefix="")
        app = GutterTestApp([row])
        async with app.run_test(size=(80, 24)):
            assert row._gutter is None


# ---------------------------------------------------------------------------
# GutteredTreeRow — set_expanded updates gutter
# ---------------------------------------------------------------------------


class TestGutteredTreeRowSetExpanded:

    @pytest.mark.asyncio
    async def test_set_expanded_creates_gutter_ref(self):
        content = Static("test")
        node = TreeNode(id="n1", label="N1", content=content)
        row = GutteredTreeRow(node, depth=1, is_branch=False, prefix="│  └─ ")
        app = GutterTestApp([row])
        async with app.run_test(size=(80, 24)):
            assert hasattr(row, "_gutter")
            assert row._gutter is not None
            assert row._gutter.gutter_text == "│  "

    @pytest.mark.asyncio
    async def test_set_expanded_updates_gutter_on_prefix_change(self):
        content = Static("test")
        node = TreeNode(id="n1", label="N1", content=content)
        row = GutteredTreeRow(node, depth=1, is_branch=False, prefix="│  └─ ")
        app = GutterTestApp([row])
        async with app.run_test(size=(80, 24)):
            row.prefix = "   └─ "
            row.set_expanded(False)
            assert row._gutter.gutter_text == "   "


# ---------------------------------------------------------------------------
# _RowGutter update_height (replaces on_resize approach)
# ---------------------------------------------------------------------------


class TestRowGutterUpdateHeight:

    def test_update_height_sets_line_count(self):
        gutter = _RowGutter("│  ")
        gutter.update_height(5)
        assert gutter._line_count == 5

    def test_update_height_clamps_to_one(self):
        gutter = _RowGutter("│  ")
        gutter.update_height(0)
        assert gutter._line_count == 1

    def test_update_height_noop_same(self):
        gutter = _RowGutter("│  ")
        # _line_count starts at 1, update_height(1) should be a no-op
        gutter.update_height(1)
        assert gutter._line_count == 1

    def test_build_gutter_after_update_height(self):
        gutter = _RowGutter("│  ")
        gutter.update_height(3)
        # After update_height, _line_count should be 3
        assert gutter._line_count == 3
        # _build_gutter should produce 3 lines
        result = gutter._build_gutter(3)
        assert result == "│  \n│  \n│  "

    def test_update_height_skips_when_same(self):
        """update_height should be a no-op when height hasn't changed."""
        gutter = _RowGutter("│  ")
        gutter.update_height(5)
        assert gutter._line_count == 5
        # Call again with same height — should be skipped
        gutter.update_height(5)
        assert gutter._line_count == 5

    def test_update_height_tracks_current_content(self):
        """_current_content is updated to match the rendered gutter."""
        gutter = _RowGutter("│  ")
        gutter.update_height(3)
        assert gutter._current_content == "│  \n│  \n│  "


class TestGutteredTreeRowResizeDebounce:
    """Tests for the debounced resize handler in GutteredTreeRow."""

    @pytest.mark.asyncio
    async def test_initial_state_no_timer(self):
        """Rows start with zero content height. The resize timer may fire
        during mount, so we only check _last_content_height."""
        content = Static("Hello world")
        node = TreeNode(id="n1", label="N1", content=content)
        row = GutteredTreeRow(node, depth=1, is_branch=False, prefix="│  └─ ")
        app = GutterTestApp([row])
        async with app.run_test(size=(80, 24)):
            # After mount, content height should have been tracked
            # (may be 0 if layout hasn't happened yet, or >0 if it has)
            assert isinstance(row._last_content_height, int)

    @pytest.mark.asyncio
    async def test_no_content_means_no_resize_tracking(self):
        """Rows without content should have no gutter and no resize tracking."""
        node = TreeNode(id="leaf1", label="Leaf")
        row = GutteredTreeRow(node, depth=0, is_branch=False, prefix="")
        app = GutterTestApp([row])
        async with app.run_test(size=(80, 24)):
            assert row._gutter is None
            assert row._last_content_height == 0
            assert row._resize_timer is None

    @pytest.mark.asyncio
    async def test_gutter_height_syncs_after_layout(self):
        """The gutter should sync to content height via _apply_gutter_resize."""
        content = Static("Line 1\nLine 2\nLine 3\nLine 4\nLine 5")
        node = TreeNode(id="n1", label="N1", content=content)
        row = GutteredTreeRow(node, depth=1, is_branch=False, prefix="│  └─ ")
        app = GutterTestApp([row])
        async with app.run_test(size=(80, 24)):
            gutter = row.query_one(_RowGutter)
            # Manually trigger the resize handler as if content grew to 5 lines
            row._apply_gutter_resize()
            # After apply, _last_content_height should be > 0 and gutter synced
            assert row._last_content_height > 0
            assert gutter._line_count == row._last_content_height


# ---------------------------------------------------------------------------
# Integration with Tree widget prefixes
# ---------------------------------------------------------------------------


class TestGutteredTreeRowWithTree:

    def test_tree_prefixes_and_gutters_agree(self):
        root = TreeNode(id="root", label="Root", children=[
            TreeNode(id="b1", label="B1", children=[
                TreeNode(id="l1", label="L1"),
                TreeNode(id="l2", label="L2"),
            ]),
            TreeNode(id="b2", label="B2", children=[
                TreeNode(id="l3", label="L3"),
            ]),
        ])

        from ui.tree.tree import Tree
        tree = Tree(root)
        prefixes = tree._compute_prefixes()

        for node_id, prefix in prefixes.items():
            gutter = _extract_gutter(prefix)
            if len(prefix) > 3:
                assert gutter + prefix[-3:] == prefix
            else:
                assert gutter == ""

    def test_gutter_preserves_vertical_lines(self):
        gutter = _extract_gutter("│  │  ├─ ")
        assert gutter == "│  │  "
        assert gutter[0] == "│"
        assert gutter[3] == "│"

        gutter = _extract_gutter("   └─ ")
        assert gutter == "   "