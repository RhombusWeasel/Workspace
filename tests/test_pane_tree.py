"""Tests for core/pane_tree.py — the pure data model for recursive pane splitting."""

import pytest
from core.pane_tree import (
    LeafPane,
    LeafRect,
    SplitPane,
    Pane,
    create_leaf,
    split,
    close,
    find_neighbor,
    set_content,
    get_leaves,
    get_layout,
    find_pane,
)


# ---------------------------------------------------------------------------
# create_leaf
# ---------------------------------------------------------------------------


class TestCreateLeaf:
    def test_creates_leaf_with_given_id(self):
        leaf = create_leaf("leaf-1")
        assert isinstance(leaf, LeafPane)
        assert leaf.id == "leaf-1"

    def test_content_defaults_to_none(self):
        leaf = create_leaf("leaf-1")
        assert leaf.content is None

    def test_accepts_initial_content(self):
        leaf = create_leaf("leaf-1", content="hello")
        assert leaf.content == "hello"


# ---------------------------------------------------------------------------
# split
# ---------------------------------------------------------------------------


class TestSplit:
    def test_splits_leaf_vertically(self):
        root = create_leaf("root")
        result = split(root, "root", "v", 0.5, "new-leaf")

        assert isinstance(result, SplitPane)
        assert result.direction == "v"
        assert result.ratio == 0.5
        assert len(result.children) == 2
        assert result.children[0].id == "root"
        assert result.children[1].id == "new-leaf"

    def test_splits_leaf_horizontally(self):
        root = create_leaf("root")
        result = split(root, "root", "h", 0.3, "new-leaf")

        assert isinstance(result, SplitPane)
        assert result.direction == "h"
        assert result.ratio == 0.3

    def test_split_is_recursive(self):
        """Split a pane that is already inside a split."""
        root = create_leaf("root")
        root = split(root, "root", "v", 0.5, "child-1")
        root = split(root, "child-1", "h", 0.7, "grandchild")

        # root is SplitPane(v) with children [Leaf(root), SplitPane(h)]
        assert isinstance(root, SplitPane)
        assert root.direction == "v"
        right_child = root.children[1]
        assert isinstance(right_child, SplitPane)
        assert right_child.direction == "h"
        assert right_child.children[0].id == "child-1"
        assert right_child.children[1].id == "grandchild"

    def test_split_preserves_existing_content(self):
        root = create_leaf("root", content="original")
        result = split(root, "root", "v", 0.5, "new-leaf")

        assert result.children[0].content == "original"
        assert result.children[1].content is None

    def test_split_accepts_content_for_new_pane(self):
        root = create_leaf("root")
        result = split(root, "root", "v", 0.5, "new-leaf", content="fresh")

        assert result.children[1].content == "fresh"

    def test_ratio_of_zero(self):
        root = create_leaf("root")
        result = split(root, "root", "v", 0.0, "new-leaf")
        assert result.ratio == 0.0

    def test_ratio_of_one(self):
        root = create_leaf("root")
        result = split(root, "root", "v", 1.0, "new-leaf")
        assert result.ratio == 1.0

    def test_raises_on_invalid_direction(self):
        root = create_leaf("root")
        with pytest.raises(ValueError, match="direction"):
            split(root, "root", "diagonal", 0.5, "new-leaf")

    def test_raises_on_ratio_below_zero(self):
        root = create_leaf("root")
        with pytest.raises(ValueError, match="ratio"):
            split(root, "root", "v", -0.1, "new-leaf")

    def test_raises_on_ratio_above_one(self):
        root = create_leaf("root")
        with pytest.raises(ValueError, match="ratio"):
            split(root, "root", "v", 1.5, "new-leaf")

    def test_raises_on_target_not_found(self):
        root = create_leaf("root")
        with pytest.raises(ValueError, match="not found"):
            split(root, "nonexistent", "v", 0.5, "new-leaf")

    def test_raises_on_duplicate_id(self):
        root = create_leaf("root")
        with pytest.raises(ValueError, match="already exists"):
            split(root, "root", "v", 0.5, "root")


# ---------------------------------------------------------------------------
# close
# ---------------------------------------------------------------------------


class TestClose:
    def test_close_single_leaf_returns_empty_pane(self):
        root = create_leaf("only")
        result = close(root, "only")

        assert isinstance(result, LeafPane)
        assert result.content is None
        # The id should be regenerated — we don't want to reuse the closed id
        assert result.id != "only"

    def test_close_left_child_promotes_right(self):
        root = create_leaf("root")
        root = split(root, "root", "v", 0.5, "right-child")
        result = close(root, "root")

        assert isinstance(result, LeafPane)
        assert result.id == "right-child"

    def test_close_right_child_promotes_left(self):
        root = create_leaf("root")
        root = split(root, "root", "v", 0.5, "right-child")
        result = close(root, "right-child")

        assert isinstance(result, LeafPane)
        assert result.id == "root"

    def test_close_deeply_nested_pane(self):
        """Close a pane three levels deep — its sibling takes the space
        and the tree collapses appropriately."""
        # Build: root -> V-split -> [left, H-split -> [middle, right]]
        root = create_leaf("root")
        root = split(root, "root", "v", 0.5, "right")
        root = split(root, "right", "h", 0.5, "far-right")

        # Close "right" (which is now a SplitPane containing right+far-right)
        result = close(root, "right")

        # The SplitPane that was "right" is removed, far-right promoted.
        # root is now V-split [root, far-right]
        assert isinstance(result, SplitPane)
        assert result.direction == "v"
        assert result.children[0].id == "root"
        assert result.children[1].id == "far-right"

    def test_close_middle_pane_in_three_way(self):
        """Build V(root, H(middle-left, middle-right)), close middle-left."""
        root = create_leaf("root")
        root = split(root, "root", "v", 0.5, "middle")
        root = split(root, "middle", "h", 0.5, "middle-right")

        # Close the first child of the H-split
        result = close(root, "middle")

        assert isinstance(result, SplitPane)
        assert result.direction == "v"
        right = result.children[1]
        assert isinstance(right, LeafPane)
        assert right.id == "middle-right"

    def test_raises_on_target_not_found(self):
        root = create_leaf("root")
        with pytest.raises(ValueError, match="not found"):
            close(root, "ghost")


# ---------------------------------------------------------------------------
# find_neighbor
# ---------------------------------------------------------------------------


class TestFindNeighbor:
    # --- Simple two-pane splits ---

    def test_left_from_right_in_h_split(self):
        root = create_leaf("left")
        root = split(root, "left", "h", 0.5, "right")
        assert find_neighbor(root, "right", "left") == "left"

    def test_right_from_left_in_h_split(self):
        root = create_leaf("left")
        root = split(root, "left", "h", 0.5, "right")
        assert find_neighbor(root, "left", "right") == "right"

    def test_up_from_bottom_in_v_split(self):
        root = create_leaf("top")
        root = split(root, "top", "v", 0.5, "bottom")
        assert find_neighbor(root, "bottom", "up") == "top"

    def test_down_from_top_in_v_split(self):
        root = create_leaf("top")
        root = split(root, "top", "v", 0.5, "bottom")
        assert find_neighbor(root, "top", "down") == "bottom"

    # --- No neighbor cases ---

    def test_no_left_from_leftmost(self):
        root = create_leaf("left")
        root = split(root, "left", "h", 0.5, "right")
        assert find_neighbor(root, "left", "left") is None

    def test_no_right_from_rightmost(self):
        root = create_leaf("left")
        root = split(root, "left", "h", 0.5, "right")
        assert find_neighbor(root, "right", "right") is None

    def test_no_up_from_topmost(self):
        root = create_leaf("top")
        root = split(root, "top", "v", 0.5, "bottom")
        assert find_neighbor(root, "top", "up") is None

    def test_no_down_from_bottommost(self):
        root = create_leaf("top")
        root = split(root, "top", "v", 0.5, "bottom")
        assert find_neighbor(root, "bottom", "down") is None

    # --- Cross-split navigation ---

    def test_left_across_v_split(self):
        """Layout: V-split(top, H-split(a, b)). From b, left = a."""
        root = create_leaf("top")
        root = split(root, "top", "v", 0.5, "bottom")
        root = split(root, "bottom", "h", 0.5, "b")

        # Now: V(top, H(bottom, b))
        assert find_neighbor(root, "b", "left") == "bottom"

    def test_right_across_v_split(self):
        """Layout: V-split(top, H-split(a, b)). From a, right = b."""
        root = create_leaf("top")
        root = split(root, "top", "v", 0.5, "bottom")
        root = split(root, "bottom", "h", 0.5, "b")

        assert find_neighbor(root, "bottom", "right") == "b"

    def test_up_across_h_split(self):
        """Layout: V-split(H-split(left, right), bottom).

        From bottom going up, both left and right are equally above —
        the algorithm picks the leftmost.
        """
        root = create_leaf("left")
        root = split(root, "left", "v", 0.5, "bottom")
        root = split(root, "left", "h", 0.5, "right")

        # V(H(left, right), bottom)
        # ┌─────┬─────┐
        # │ left│right│
        # ├─────┴─────┤
        # │  bottom   │
        # └───────────┘
        assert find_neighbor(root, "bottom", "up") == "left"

    def test_down_across_h_split(self):
        """Layout: H-split(V-split(a, b), right). From a, down = b."""
        root = create_leaf("left")
        root = split(root, "left", "v", 0.5, "bottom")
        root = split(root, "left", "h", 0.5, "right")

        assert find_neighbor(root, "left", "down") == "bottom"

    # --- Quadrant layout (2x2 grid) ---

    def test_two_by_two_grid_navigation(self):
        """Build a 2x2 grid and verify all four directional navigations."""
        # Step 1: V-split -> [top-left, bottom]
        root = create_leaf("tl")
        root = split(root, "tl", "v", 0.5, "bl")
        # Step 2: H-split top-left -> [top-left, top-right]
        root = split(root, "tl", "h", 0.5, "tr")
        # Step 3: H-split bottom-left -> [bottom-left, bottom-right]
        root = split(root, "bl", "h", 0.5, "br")

        # Layout:
        # ┌─────┬─────┐
        # │ tl  │ tr  │
        # ├─────┼─────┤
        # │ bl  │ br  │
        # └─────┴─────┘

        # From tl
        assert find_neighbor(root, "tl", "right") == "tr"
        assert find_neighbor(root, "tl", "down") == "bl"
        assert find_neighbor(root, "tl", "left") is None
        assert find_neighbor(root, "tl", "up") is None

        # From tr
        assert find_neighbor(root, "tr", "left") == "tl"
        assert find_neighbor(root, "tr", "down") == "br"
        assert find_neighbor(root, "tr", "right") is None
        assert find_neighbor(root, "tr", "up") is None

        # From bl
        assert find_neighbor(root, "bl", "right") == "br"
        assert find_neighbor(root, "bl", "up") == "tl"
        assert find_neighbor(root, "bl", "left") is None
        assert find_neighbor(root, "bl", "down") is None

        # From br
        assert find_neighbor(root, "br", "left") == "bl"
        assert find_neighbor(root, "br", "up") == "tr"
        assert find_neighbor(root, "br", "right") is None
        assert find_neighbor(root, "br", "down") is None

    def test_from_leaf_finds_neighbor_across_multiple_levels(self):
        """Non-uniform layout: V(H(top, V(right-top, right-bot)), mid).

        Layout:
        ┌──────┬──────────┐
        │ top  │ right-top│
        │      ├──────────┤
        │      │ right-bot│
        ├──────┴──────────┤
        │      mid        │
        └─────────────────┘

        mid spans full width, so it has no left/right neighbor.
        """
        root = create_leaf("top")
        root = split(root, "top", "v", 0.5, "mid")
        root = split(root, "top", "h", 0.5, "right-top")
        root = split(root, "right-top", "v", 0.5, "right-bot")

        # top neighbors
        assert find_neighbor(root, "top", "right") == "right-top"
        assert find_neighbor(root, "top", "down") == "mid"

        # right-top neighbors
        assert find_neighbor(root, "right-top", "left") == "top"
        assert find_neighbor(root, "right-top", "down") == "right-bot"

        # right-bot neighbors
        assert find_neighbor(root, "right-bot", "up") == "right-top"
        assert find_neighbor(root, "right-bot", "left") == "top"

        # mid neighbors — spans full width, no left/right
        assert find_neighbor(root, "mid", "up") == "top"
        assert find_neighbor(root, "mid", "left") is None
        assert find_neighbor(root, "mid", "right") is None
        assert find_neighbor(root, "mid", "down") is None

    def test_invalid_direction_raises(self):
        root = create_leaf("only")
        with pytest.raises(ValueError, match="direction"):
            find_neighbor(root, "only", "northwest")

    def test_target_not_found_raises(self):
        root = create_leaf("only")
        with pytest.raises(ValueError, match="not found"):
            find_neighbor(root, "ghost", "left")


# ---------------------------------------------------------------------------
# set_content
# ---------------------------------------------------------------------------


class TestSetContent:
    def test_updates_content_of_leaf(self):
        root = create_leaf("a", content="old")
        result = set_content(root, "a", "new")
        assert result.content == "new"

    def test_updates_content_of_nested_leaf(self):
        root = create_leaf("a")
        root = split(root, "a", "v", 0.5, "b")
        result = set_content(root, "b", "nested-content")
        # Find b and check its content
        found = find_pane(result, "b")
        assert isinstance(found, LeafPane)
        assert found.content == "nested-content"

    def test_does_not_mutate_other_leaves(self):
        root = create_leaf("a", content="keep-me")
        root = split(root, "a", "v", 0.5, "b")
        result = set_content(root, "b", "changed")
        found = find_pane(result, "a")
        assert isinstance(found, LeafPane)
        assert found.content == "keep-me"

    def test_raises_on_target_not_found(self):
        root = create_leaf("a")
        with pytest.raises(ValueError, match="not found"):
            set_content(root, "ghost", "x")

    def test_returns_same_object_for_leaf_root(self):
        """When the target is the root leaf, the same object is returned
        (mutated in place)."""
        root = create_leaf("a", content="old")
        result = set_content(root, "a", "new")
        assert result is root


# ---------------------------------------------------------------------------
# get_leaves
# ---------------------------------------------------------------------------


class TestGetLeaves:
    def test_single_leaf(self):
        root = create_leaf("only")
        leaves = get_leaves(root)
        assert len(leaves) == 1
        assert leaves[0].id == "only"

    def test_multiple_leaves_in_flat_split(self):
        root = create_leaf("a")
        root = split(root, "a", "v", 0.5, "b")
        leaves = get_leaves(root)
        assert {leaf.id for leaf in leaves} == {"a", "b"}

    def test_deeply_nested(self):
        root = create_leaf("a")
        root = split(root, "a", "v", 0.5, "b")
        root = split(root, "b", "h", 0.5, "c")
        root = split(root, "a", "h", 0.3, "d")

        leaves = get_leaves(root)
        assert {leaf.id for leaf in leaves} == {"a", "b", "c", "d"}

    def test_returns_leaves_in_visual_order(self):
        """Leaves should be returned in top-left to bottom-right reading order."""
        root = create_leaf("tl")
        root = split(root, "tl", "h", 0.5, "tr")
        root = split(root, "tl", "v", 0.5, "bl")
        root = split(root, "tr", "v", 0.5, "br")

        # ┌─────┬─────┐
        # │ tl  │ tr  │
        # ├─────┼─────┤
        # │ bl  │ br  │
        # └─────┴─────┘

        leaves = get_leaves(root)
        ids = [leaf.id for leaf in leaves]
        assert ids == ["tl", "bl", "tr", "br"]


# ---------------------------------------------------------------------------
# get_layout
# ---------------------------------------------------------------------------


class TestGetLayout:
    def test_single_leaf_fills_workspace(self):
        root = create_leaf("only")
        layout = get_layout(root)
        assert len(layout) == 1
        r = layout[0]
        assert r.leaf_id == "only"
        assert r.x == 0.0
        assert r.y == 0.0
        assert r.w == 1.0
        assert r.h == 1.0

    def test_horizontal_split(self):
        root = create_leaf("left")
        root = split(root, "left", "h", 0.3, "right")
        layout = get_layout(root)
        assert len(layout) == 2

        left = next(r for r in layout if r.leaf_id == "left")
        assert left.x == 0.0
        assert left.y == 0.0
        assert left.w == pytest.approx(0.3)
        assert left.h == 1.0

        right = next(r for r in layout if r.leaf_id == "right")
        assert right.x == pytest.approx(0.3)
        assert right.y == 0.0
        assert right.w == pytest.approx(0.7)
        assert right.h == 1.0

    def test_vertical_split(self):
        root = create_leaf("top")
        root = split(root, "top", "v", 0.7, "bottom")
        layout = get_layout(root)
        assert len(layout) == 2

        top = next(r for r in layout if r.leaf_id == "top")
        assert top.x == 0.0
        assert top.y == 0.0
        assert top.w == 1.0
        assert top.h == pytest.approx(0.7)

        bottom = next(r for r in layout if r.leaf_id == "bottom")
        assert bottom.x == 0.0
        assert bottom.y == pytest.approx(0.7)
        assert bottom.w == 1.0
        assert bottom.h == pytest.approx(0.3)

    def test_two_by_two_grid(self):
        root = create_leaf("tl")
        root = split(root, "tl", "v", 0.5, "bl")
        root = split(root, "tl", "h", 0.5, "tr")
        root = split(root, "bl", "h", 0.5, "br")

        layout = get_layout(root)
        assert len(layout) == 4

        tl = next(r for r in layout if r.leaf_id == "tl")
        assert tl.x == 0.0 and tl.y == 0.0
        assert tl.w == pytest.approx(0.5) and tl.h == pytest.approx(0.5)

        tr = next(r for r in layout if r.leaf_id == "tr")
        assert tr.x == pytest.approx(0.5) and tr.y == 0.0
        assert tr.w == pytest.approx(0.5) and tr.h == pytest.approx(0.5)

        bl = next(r for r in layout if r.leaf_id == "bl")
        assert bl.x == 0.0 and bl.y == pytest.approx(0.5)
        assert bl.w == pytest.approx(0.5) and bl.h == pytest.approx(0.5)

        br = next(r for r in layout if r.leaf_id == "br")
        assert br.x == pytest.approx(0.5) and br.y == pytest.approx(0.5)
        assert br.w == pytest.approx(0.5) and br.h == pytest.approx(0.5)

    def test_visual_order_is_dfs_left_to_right(self):
        root = create_leaf("tl")
        root = split(root, "tl", "v", 0.5, "bl")
        root = split(root, "tl", "h", 0.5, "tr")
        root = split(root, "bl", "h", 0.5, "br")

        layout = get_layout(root)
        ids = [r.leaf_id for r in layout]
        # Tree is V(H(tl,tr), H(bl,br)). DFS yields: tl, tr, bl, br
        assert ids == ["tl", "tr", "bl", "br"]

    def test_layout_leaves_are_in_leafrect_form(self):
        root = create_leaf("a")
        layout = get_layout(root)
        assert isinstance(layout, list)
        assert all(isinstance(r, LeafRect) for r in layout)


# ---------------------------------------------------------------------------
# find_pane
# ---------------------------------------------------------------------------


class TestFindPane:
    def test_finds_root(self):
        root = create_leaf("root")
        found = find_pane(root, "root")
        assert found is root

    def test_finds_nested_leaf(self):
        root = create_leaf("a")
        root = split(root, "a", "v", 0.5, "b")
        found = find_pane(root, "b")
        assert isinstance(found, LeafPane)
        assert found.id == "b"

    def test_finds_split_pane(self):
        root = create_leaf("a")
        root = split(root, "a", "v", 0.5, "b")
        root = split(root, "b", "h", 0.5, "c")

        # "b" is still a LeafPane (new SplitPanes get auto-generated ids)
        found = find_pane(root, "b")
        assert isinstance(found, LeafPane)
        assert found.id == "b"

    def test_returns_none_for_missing(self):
        root = create_leaf("a")
        assert find_pane(root, "ghost") is None

    def test_returns_none_in_empty_tree(self):
        """Edge case — shouldn't happen in practice but handle gracefully."""
        # We can't really have an "empty" tree with our API, but testing
        # find_pane on a leaf with wrong id exercises the same path.
        root = create_leaf("a")
        assert find_pane(root, "b") is None


# ---------------------------------------------------------------------------
# Immutability / no unexpected mutation
# ---------------------------------------------------------------------------


class TestImmutability:
    def test_split_does_not_mutate_original(self):
        root = create_leaf("root")
        result = split(root, "root", "v", 0.5, "new")

        # The original root should still be a simple LeafPane
        assert isinstance(root, LeafPane)
        assert root.id == "root"
        # The result is a new SplitPane
        assert isinstance(result, SplitPane)

    def test_close_does_not_mutate_original(self):
        root = create_leaf("a")
        root = split(root, "a", "v", 0.5, "b")
        original = root
        result = close(root, "a")

        # Original should be unchanged
        assert isinstance(original, SplitPane)
        assert original.children[0].id == "a"
        assert result is not original
