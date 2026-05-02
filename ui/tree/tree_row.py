"""Tree row — a single row in a :class:`~ui.tree.tree.Tree`."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------


@dataclass
class TreeNode:
    """A single node in the tree data model.

    Parameters
    ----------
    id:
        Unique identifier for this node.
    label:
        Display text.
    children:
        Child nodes.
    data:
        Arbitrary attached payload.
    """

    id: str
    label: str
    children: list[TreeNode] = field(default_factory=list)
    data: Any = None


# ---------------------------------------------------------------------------
# TreeRow
# ---------------------------------------------------------------------------


class TreeRow(Widget):
    """A single visible row in the tree.

    Renders an indent prefix, optional expand/collapse indicator, and
    the node label.  Posts ``Selected`` on click and ``Toggled`` on
    expand-indicator click.
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
        self._was_expanded: bool = False  # track state for indicator text

    def render(self):
        from rich.text import Text

        indent = "  " * self.depth
        toggle = "▶ " if self.is_branch else "  "
        text = Text(f"{indent}{toggle}{self.node.label}")
        if self.is_selected:
            text.stylize("reverse")
        return text

    def on_click(self, event) -> None:
        """Mouse click — if branch, toggle; always select."""
        if self.is_branch:
            self.post_message(self.Toggled(self.node))
        else:
            self.post_message(self.Selected(self.node))
        event.stop()
