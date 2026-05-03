"""Tree row — a single row in a :class:`~ui.tree.tree.Tree`."""

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
        Machine-readable identifier posted in ``ActionRow.ButtonPressed``.
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
        Action buttons to show on this row (only used for leaf nodes).
    """

    id: str
    label: str
    children: list[TreeNode] = field(default_factory=list)
    data: Any = None
    content: Widget | None = None
    buttons: list[RowButton] = field(default_factory=list)


# ---------------------------------------------------------------------------
# TreeRow
# ---------------------------------------------------------------------------


class TreeRow(Widget):
    """A single visible row in the tree.

    Composes an indent prefix, optional expand/collapse indicator, and
    either the node label (plain text) or the node's ``content`` widget.

    Posts ``Selected`` on click and ``Toggled`` on expand-indicator click.
    """

    is_selected: reactive[bool] = reactive(False)

    class Selected(Message):
        """Posted when the row is clicked."""

        def __init__(self, node: TreeNode) -> None:
            super().__init__()
            self.node = node

    class Toggled(Message):
        """Posted when the expand/collapse indicator is clicked."""

        def __init__(self, node: TreeNode) -> None:
            super().__init__()
            self.node = node

    def __init__(self, node: TreeNode, *, depth: int = 0, is_branch: bool = False):
        super().__init__()
        self.node = node
        self.depth = depth
        self.is_branch = is_branch

    def compose(self) -> ComposeResult:
        indent = "  " * self.depth
        toggle = "▶ " if self.is_branch else "  "
        yield Static(f"{indent}{toggle}{self.node.label}")
        if self.node.content is not None:
            yield self.node.content

    def on_click(self, event) -> None:
        """Mouse click — if branch, toggle; always select."""
        if self.is_branch:
            self.post_message(self.Toggled(self.node))
        else:
            self.post_message(self.Selected(self.node))
        event.stop()


# ---------------------------------------------------------------------------
# ActionRow — a tree row with inline action buttons
# ---------------------------------------------------------------------------


class ActionRow(Widget):
    """A tree row that composes action buttons alongside the node label.

    Used by :class:`~ui.tree.tree.Tree` when a :class:`TreeNode` has a
    non-empty ``buttons`` list.  Posts ``ButtonPressed`` when any of the
    action buttons is clicked.
    """

    class ButtonPressed(Message):
        """Posted when an action button is clicked."""

        def __init__(self, action_id: str, node: TreeNode) -> None:
            super().__init__()
            self.action_id = action_id
            self.node = node

    def __init__(self, node: TreeNode, *, depth: int = 0):
        super().__init__()
        self.node = node
        self.depth = depth

    def compose(self) -> ComposeResult:
        indent = "  " * self.depth
        label_text = f"{indent}  {self.node.label}"
        with Horizontal():
            yield Static(label_text)
            for btn in self.node.buttons:
                yield Button(
                    btn.label,
                    id=f"act-{self.node.id}-{btn.action_id}",
                    classes=btn.style or "",
                )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        # Parse action_id back from the DOM id
        prefix = f"act-{self.node.id}-"
        action_id = event.button.id[len(prefix):]
        self.post_message(self.ButtonPressed(action_id, self.node))
