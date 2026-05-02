"""Recursive pane tree — pure data model for the splitting workspace.

A :class:`Pane` is either a :class:`LeafPane` (holds a content widget) or
a :class:`SplitPane` (divides its space between two children).  All
operations return new trees — no mutation of inputs.

This module has **zero Textual dependency**.  It is pure data + algorithms.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Literal

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

Direction = Literal["h", "v"]
"""Split direction: ``"h"`` = children side-by-side, ``"v"`` = stacked."""

NavDirection = Literal["left", "right", "up", "down"]
"""Spatial navigation direction (vim hjkl semantics)."""


@dataclass
class LeafPane:
    """A pane that holds a single content widget.

    Attributes:
        id: Unique identifier for this pane within the tree.
        content: The widget mounted in this pane (or ``None``).
    """

    id: str
    content: Any = None


@dataclass
class SplitPane:
    """A pane that divides its space between two child panes.

    Attributes:
        id: Unique identifier.
        direction: ``"h"`` = left/right, ``"v"`` = top/bottom.
        ratio: Fraction (0.0-1.0) of space given to the **first** child.
        children: The two child panes (left/top and right/bottom).
    """

    id: str
    direction: Direction
    ratio: float
    children: tuple[Pane, Pane]


Pane = LeafPane | SplitPane
"""A node in the pane tree."""


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_leaf(id: str | None = None, content: Any = None) -> LeafPane:
    """Create a new leaf pane.

    Args:
        id: Unique identifier.  Auto-generated when ``None``.
        content: Initial widget to mount (default ``None``).
    """
    if id is None:
        id = uuid.uuid4().hex[:8]
    return LeafPane(id=id, content=content)


# ---------------------------------------------------------------------------
# split
# ---------------------------------------------------------------------------


def split(
    root: Pane,
    target_id: str,
    direction: Direction,
    ratio: float,
    new_id: str,
    content: Any = None,
) -> Pane:
    """Split *target_id* in *direction*, creating a new leaf with *new_id*.

    The target leaf is replaced by a :class:`SplitPane` whose first child
    is the original leaf and second child is the new leaf.  *ratio*
    controls how much space the first child gets.

    Args:
        root: Root of the pane tree.
        target_id: ID of the leaf to split.
        direction: ``"h"`` or ``"v"``.
        ratio: Float in ``[0.0, 1.0]`` — portion for the first child.
        new_id: ID for the newly created leaf.
        content: Initial content for the new leaf.

    Returns:
        A new tree (original *root* is not mutated).

    Raises:
        ValueError: If *target_id* is not found, *new_id* already exists,
            *direction* is invalid, or *ratio* is out of range.
    """
    if direction not in ("h", "v"):
        raise ValueError(f"Invalid direction: {direction!r}. Must be 'h' or 'v'.")
    if not (0.0 <= ratio <= 1.0):
        raise ValueError(f"ratio must be between 0.0 and 1.0, got {ratio}")

    _require_exists(root, target_id)
    _require_not_exists(root, new_id)

    return _split_impl(root, target_id, direction, ratio, new_id, content)


def _split_impl(
    node: Pane,
    target_id: str,
    direction: Direction,
    ratio: float,
    new_id: str,
    content: Any,
) -> Pane:
    if isinstance(node, LeafPane):
        if node.id == target_id:
            new_leaf = LeafPane(id=new_id, content=content)
            return SplitPane(
                id=uuid.uuid4().hex[:8],
                direction=direction,
                ratio=ratio,
                children=(node, new_leaf),
            )
        return node

    # SplitPane — recurse into children
    left, right = node.children
    new_left = _split_impl(left, target_id, direction, ratio, new_id, content)
    new_right = _split_impl(right, target_id, direction, ratio, new_id, content)
    if new_left is not left or new_right is not right:
        return SplitPane(
            id=node.id,
            direction=node.direction,
            ratio=node.ratio,
            children=(new_left, new_right),
        )
    return node


# ---------------------------------------------------------------------------
# close
# ---------------------------------------------------------------------------


def close(root: Pane, target_id: str) -> Pane:
    """Remove *target_id* from the tree.  Its sibling inherits the space.

    If *target_id* is the only pane in the tree, an empty leaf is returned
    (the workspace will render as a bordered empty area).

    Args:
        root: Root of the pane tree.
        target_id: ID of the pane to close.

    Returns:
        A new tree (original *root* is not mutated).

    Raises:
        ValueError: If *target_id* is not found.
    """
    _require_exists(root, target_id)

    # Special case: closing the only pane
    if isinstance(root, LeafPane):
        return LeafPane(id=uuid.uuid4().hex[:8], content=None)

    result = _close_impl(root, target_id)
    assert result is not None, "close_impl returned None for non-root target"
    return result


def _close_impl(node: Pane, target_id: str) -> Pane | None:
    """Recurse into the tree to find and remove *target_id*.

    Returns:
        * ``None`` — this node **is** the target (parent replaces with sibling).
        * A :class:`Pane` — replacement for this node in the parent.
    """
    if isinstance(node, LeafPane):
        return None if node.id == target_id else node

    left, right = node.children
    new_left = _close_impl(left, target_id)
    new_right = _close_impl(right, target_id)

    if new_left is None:
        return right
    if new_right is None:
        return left

    if new_left is not left or new_right is not right:
        return SplitPane(
            id=node.id,
            direction=node.direction,
            ratio=node.ratio,
            children=(new_left, new_right),
        )
    return node


# ---------------------------------------------------------------------------
# find_neighbor (coordinate-based)
# ---------------------------------------------------------------------------


@dataclass
class LeafRect:
    """Bounding box of a leaf pane in normalized workspace coordinates."""

    leaf_id: str
    x: float
    y: float
    w: float
    h: float


def get_layout(root: Pane) -> list[LeafRect]:
    """Compute normalized bounding boxes for all leaves.

    Returns rectangles in visual order (top-left → bottom-right).
    Each coordinate is in ``[0.0, 1.0]`` relative to the workspace.
    """
    result: list[LeafRect] = []
    _layout_impl(root, 0.0, 0.0, 1.0, 1.0, result)
    return result


def _layout_impl(
    node: Pane, x: float, y: float, w: float, h: float, acc: list[LeafRect]
) -> None:
    if isinstance(node, LeafPane):
        acc.append(LeafRect(leaf_id=node.id, x=x, y=y, w=w, h=h))
        return

    left, right = node.children
    if node.direction == "h":
        left_w = w * node.ratio
        _layout_impl(left, x, y, left_w, h, acc)
        _layout_impl(right, x + left_w, y, w - left_w, h, acc)
    else:
        top_h = h * node.ratio
        _layout_impl(left, x, y, w, top_h, acc)
        _layout_impl(right, x, y + top_h, w, h - top_h, acc)


def find_neighbor(root: Pane, target_id: str, direction: NavDirection) -> str | None:
    """Find the ID of the leaf adjacent to *target_id* in *direction*.

    Directions use vim semantics: ``"left"`` (h), ``"right"`` (l),
    ``"up"`` (k), ``"down"`` (j).

    Uses coordinate-based adjacency — works correctly for all tree
    configurations, not just perfect grids.

    Args:
        root: Root of the pane tree.
        target_id: ID of the starting leaf.
        direction: Which direction to search.

    Returns:
        The neighbor's ID, or ``None`` if there is no pane in that direction.

    Raises:
        ValueError: If *target_id* is not found or *direction* is invalid.
    """
    if direction not in ("left", "right", "up", "down"):
        raise ValueError(
            f"Invalid direction: {direction!r}. "
            "Must be 'left', 'right', 'up', or 'down'."
        )

    _require_exists(root, target_id)

    layout = get_layout(root)
    target = next(r for r in layout if r.leaf_id == target_id)

    best_id: str | None = None
    best_score: float = float("inf")

    for rect in layout:
        if rect.leaf_id == target_id:
            continue
        score = _adjacency_score(target, rect, direction)
        if score is not None and score < best_score:
            best_score = score
            best_id = rect.leaf_id

    return best_id


def _adjacency_score(
    target: LeafRect, candidate: LeafRect, direction: NavDirection
) -> float | None:
    """Return a score for how well *candidate* is adjacent to *target*
    in *direction*.  Lower is better.  Returns ``None`` if *candidate*
    is not in the correct direction at all.
    """
    if direction == "left":
        # Candidate must be strictly to the left
        if candidate.x + candidate.w > target.x + 0.001:
            return None
        # Score: horizontal gap + vertical misalignment
        gap = target.x - (candidate.x + candidate.w)
        overlap = _overlap_ratio(target.y, target.y + target.h,
                                 candidate.y, candidate.y + candidate.h)
        if overlap <= 0.0:
            return None
        return gap - overlap  # prefer closer + more overlap

    elif direction == "right":
        if candidate.x < target.x + target.w - 0.001:
            return None
        gap = candidate.x - (target.x + target.w)
        overlap = _overlap_ratio(target.y, target.y + target.h,
                                 candidate.y, candidate.y + candidate.h)
        if overlap <= 0.0:
            return None
        return gap - overlap

    elif direction == "up":
        if candidate.y + candidate.h > target.y + 0.001:
            return None
        gap = target.y - (candidate.y + candidate.h)
        overlap = _overlap_ratio(target.x, target.x + target.w,
                                 candidate.x, candidate.x + candidate.w)
        if overlap <= 0.0:
            return None
        return gap - overlap

    else:  # down
        if candidate.y < target.y + target.h - 0.001:
            return None
        gap = candidate.y - (target.y + target.h)
        overlap = _overlap_ratio(target.x, target.x + target.w,
                                 candidate.x, candidate.x + candidate.w)
        if overlap <= 0.0:
            return None
        return gap - overlap


def _overlap_ratio(a1: float, a2: float, b1: float, b2: float) -> float:
    """Ratio of overlap between two 1D intervals."""
    overlap = min(a2, b2) - max(a1, b1)
    if overlap <= 0.0:
        return 0.0
    target_len = a2 - a1
    return overlap / target_len if target_len > 0 else 0.0


# ---------------------------------------------------------------------------
# set_content
# ---------------------------------------------------------------------------


def set_content(root: Pane, target_id: str, content: Any) -> Pane:
    """Replace the content of leaf *target_id* with *content*.

    Args:
        root: Root of the pane tree.
        target_id: ID of the leaf to update.
        content: New widget (or ``None`` to clear).

    Returns:
        A new tree (original *root* is not mutated if target is nested).

    Raises:
        ValueError: If *target_id* is not found.
    """
    _require_exists(root, target_id)
    return _set_content_impl(root, target_id, content)


def _set_content_impl(node: Pane, target_id: str, content: Any) -> Pane:
    if isinstance(node, LeafPane):
        if node.id == target_id:
            node.content = content
            return node
        return node

    left, right = node.children
    new_left = _set_content_impl(left, target_id, content)
    new_right = _set_content_impl(right, target_id, content)
    if new_left is not left or new_right is not right:
        return SplitPane(
            id=node.id,
            direction=node.direction,
            ratio=node.ratio,
            children=(new_left, new_right),
        )
    return node


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------


def get_leaves(root: Pane) -> list[LeafPane]:
    """Return all leaves in visual order (top-left → bottom-right)."""
    result: list[LeafPane] = []
    _collect_leaves(root, result)
    return result


def _collect_leaves(node: Pane, acc: list[LeafPane]) -> None:
    if isinstance(node, LeafPane):
        acc.append(node)
    else:
        _collect_leaves(node.children[0], acc)
        _collect_leaves(node.children[1], acc)


def find_pane(root: Pane, target_id: str) -> Pane | None:
    """Find the pane with *target_id*, or ``None`` if not found."""
    if root.id == target_id:
        return root
    if isinstance(root, SplitPane):
        for child in root.children:
            found = find_pane(child, target_id)
            if found is not None:
                return found
    return None


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _require_exists(root: Pane, target_id: str) -> None:
    if find_pane(root, target_id) is None:
        raise ValueError(f"Pane {target_id!r} not found in tree.")


def _require_not_exists(root: Pane, new_id: str) -> None:
    if find_pane(root, new_id) is not None:
        raise ValueError(f"Pane {new_id!r} already exists in tree.")
