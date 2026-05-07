"""Tree row — a single row in a :class:`~ui.tree.tree.Tree`.

Each row can optionally display inline action buttons alongside the label.
Branch nodes show ▼/▶ toggle indicators regardless of whether they have buttons.
Clicking the label area posts ``Selected`` (leaf) or ``Toggled`` (branch).
Clicking an action button posts ``ButtonPressed``.

The label area is a separate :class:`_RowLabel` widget so that clicks on
buttons do not also trigger selection or toggle events.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Button, Static


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------


@dataclass
class RowButton:
    """Describes an action button to render inside a tree row.

    Parameters
    ----------
    action_id:
        Machine-readable identifier posted in ``ButtonPressed``.
    label:
        Display text on the button.
    style:
        Optional CSS class(es) for styling the button.
    """

    action_id: str
    label: str
    style: str = ""


@dataclass
class TreeNode:
    """A single node in the tree data model.

    Parameters
    ----------
    id:
        Unique identifier for this node.
    label:
        Display text shown in the indent / toggle prefix area.
    children:
        Child nodes (makes this a branch when non-empty).
    data:
        Arbitrary attached payload.
    content:
        Optional Textual :class:`Widget` mounted as the node's
        content area.  When set, the widget is composed inside the
        row instead of a plain text label.  Useful for
        :class:`~textual.widgets.Markdown` (streaming) or any
        custom rendering.
    buttons:
        Action buttons to show on this row.
    loaded:
        Whether children have been loaded.  ``False`` means this
        is a lazy node that has not been scanned yet — the tree
        will treat it as a branch and post :class:`NodeNeedsChildren`
        when the user tries to expand it.
    """

    id: str
    label: str
    children: list[TreeNode] = field(default_factory=list)
    data: Any = None
    content: Widget | None = None
    buttons: list[RowButton] = field(default_factory=list)
    loaded: bool = True


# ---------------------------------------------------------------------------
# Constants — box-drawing characters for tree lines
# ---------------------------------------------------------------------------

_LINE_VERTICAL = "│   "
_BRANCH = "├── "
_LAST_BRANCH = "└── "
_INDENT = "    "


# ---------------------------------------------------------------------------
# _RowLabel — clickable label area within a TreeRow
# ---------------------------------------------------------------------------


class _RowLabel(Widget):
    """Label area within a :class:`TreeRow` that handles clicks for
    selection and toggle, independently of action buttons.

    Clicks here post :class:`TreeRow.Selected` (leaf) or
    :class:`TreeRow.Toggled` (branch) messages.
    """

    DEFAULT_CSS = """
    _RowLabel {
        width: 1fr;
        height: auto;
        min-height: 1;
    }
    """

    def __init__(self, text: str, node: TreeNode, is_branch: bool):
        super().__init__()
        self._text = text
        self._node = node
        self._is_branch = is_branch

    def compose(self) -> ComposeResult:
        yield Static(self._text)

    def on_click(self, event) -> None:
        event.stop()
        parent = self.ancestor(TreeRow)
        if parent is None:
            return
        if self._is_branch:
            parent.post_message(TreeRow.Toggled(self._node))
        else:
            parent.post_message(TreeRow.Selected(self._node))


# ---------------------------------------------------------------------------
# TreeRow
# ---------------------------------------------------------------------------


class TreeRow(Widget):
    """A single visible row in the tree.

    Composes a clickable label area (with tree-line prefix and
    optional ▼/▶ toggle), an optional content widget, and optional
    inline action buttons.

    - Clicking the **label area** posts ``Selected`` (leaf) or
      ``Toggled`` (branch).
    - Clicking an **action button** posts ``ButtonPressed``.
    - The two click targets are separate widgets so that clicking
      a button does not also trigger selection or toggle.
    """

    is_selected: reactive[bool] = reactive(False)

    class Selected(Message):
        """Posted when the label area is clicked on a leaf node."""

        def __init__(self, node: TreeNode) -> None:
            super().__init__()
            self.node = node

    class Toggled(Message):
        """Posted when the label area is clicked on a branch node."""

        def __init__(self, node: TreeNode) -> None:
            super().__init__()
            self.node = node

    class ButtonPressed(Message):
        """Posted when an action button is clicked."""

        def __init__(self, action_id: str, node: TreeNode) -> None:
            super().__init__()
            self.action_id = action_id
            self.node = node

    def __init__(
        self,
        node: TreeNode,
        *,
        depth: int = 0,
        is_branch: bool = False,
        prefix: str = "",
        expanded: bool = False,
    ):
        super().__init__()
        self.node = node
        self.depth = depth
        self.is_branch = is_branch
        self.prefix = prefix
        self.expanded = expanded

    def _render_label(self) -> str:
        """Build the full display string for this row."""
        if self.is_branch:
            toggle = "\u25bc " if self.expanded else "\u25b6 "  # ▼ / ▶
        else:
            toggle = ""
        return f"{self.prefix}{toggle}{self.node.label}"

    def compose(self) -> ComposeResult:
        # Label area — handles clicks for select/toggle
        self._label = _RowLabel(
            self._render_label(), self.node, self.is_branch
        )
        with Horizontal(classes="tree-row-inner"):
            yield self._label
            if self.node.content is not None:
                yield self.node.content

        # Buttons — handle their own clicks independently
        if self.node.buttons:
            with Horizontal(classes="tree-row-buttons"):
                for btn in self.node.buttons:
                    yield Button(
                        btn.label,
                        id=f"act-{self.node.id}-{btn.action_id}",
                        classes=btn.style or "",
                    )

    @property
    def label_text(self) -> str:
        """The current rendered label string."""
        return self._render_label()

    def set_expanded(self, expanded: bool) -> None:
        """Update the expand/collapse indicator and re-render the label."""
        self.expanded = expanded
        if hasattr(self, "_label"):
            self._label._text = self._render_label()
            # Update the Static inside _RowLabel
            statics = self._label.query(Static)
            if statics:
                statics[0].update(self._render_label())

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Route button clicks to ``ButtonPressed`` message."""
        event.stop()
        prefix = f"act-{self.node.id}-"
        action_id = event.button.id[len(prefix):]
        self.post_message(self.ButtonPressed(action_id, self.node))


# ---------------------------------------------------------------------------
# ActionRow — legacy compatibility alias
# ---------------------------------------------------------------------------


class ActionRow(TreeRow):
    """Legacy alias for :class:`TreeRow` when buttons are present.

    .. deprecated::
        Use :class:`TreeRow` directly — all rows now support buttons.
    """

    def __init__(self, node: TreeNode, *, depth: int = 0, prefix: str = ""):
        is_branch = bool(node.children) or not node.loaded
        super().__init__(
            node, depth=depth, is_branch=is_branch, prefix=prefix
        )