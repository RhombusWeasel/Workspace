"""Guttered tree row — extends :class:`~ui.tree.tree_row.TreeRow` with a
left gutter that carries the ancestor tree-line characters (│) through
multi-line content widgets.

When a content widget (Markdown, Static, etc.) spans multiple lines, the
standard TreeRow only shows the tree-line prefix on the label row.  The
lines below lose the │ connectors, breaking the visual tree indentation.

This variant adds a :class:`_RowGutter` widget — a narrow vertical strip
that repeats the ancestor portion of the prefix alongside the content.
The gutter sits in the same Horizontal container as the content widget.
The parent :class:`GutteredTreeRow` watches the content widget's height
via :class:`~textual.events.Resize` and keeps the gutter in sync.

Usage
-----
Replace ``TreeRow`` with ``GutteredTreeRow`` in the tree's mount /
rebuild code.  Everything else (data model, events, CSS) is identical.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Static

from ui.tree.tree_row import (
    TreeNode,
    TreeRow,
)


# ---------------------------------------------------------------------------
# _RowGutter — vertical tree-line strip beside content widgets
# ---------------------------------------------------------------------------


class _RowGutter(Static):
    """A narrow strip that displays the ancestor portion of a tree-line
    prefix, repeating it vertically alongside the content widget.

    The gutter text is the part of the prefix *before* the final connector
    (├─ or └─).  For example, if the full prefix is ``"   │  └─ "``, the
    gutter shows ``"   │  "`` repeated for every line of the content.

    The gutter is ``height: auto`` — it does **not** stretch to fill
    available space.  Instead, the parent :class:`GutteredTreeRow`
    monitors the content widget's :class:`~textual.events.Resize` events
    and calls :meth:`update_height` to keep the gutter in sync.

    An empty gutter string (root-level nodes) is rendered as a single
    space per line so that the Horizontal layout keeps the gutter slot
    allocated.
    """

    DEFAULT_CSS = """
    _RowGutter {
        width: auto;
        height: auto;
        overflow: hidden;
        padding: 0;
        margin: 0;
        border: none;
    }
    """

    def __init__(self, gutter_text: str):
        self._gutter_text = gutter_text
        self._line_count: int = 1
        super().__init__(self._build_gutter(1))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_gutter(self, gutter_text: str) -> None:
        """Update the gutter string (e.g. when the prefix changes after
        a rebuild) and re-render."""
        if gutter_text != self._gutter_text:
            self._gutter_text = gutter_text
            self.update(self._build_gutter(self._line_count))

    @property
    def gutter_text(self) -> str:
        return self._gutter_text

    def update_height(self, height: int) -> None:
        """Update the gutter to show *height* lines of the pattern.

        Called by the parent :class:`GutteredTreeRow` when the content
        widget resizes.  The gutter's own height is set explicitly and
        its content is rebuilt to fill exactly that many visual lines.
        """
        if height < 1:
            height = 1
        if height != self._line_count:
            self._line_count = height
            self.update(self._build_gutter(height))

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _build_gutter(self, height: int) -> str:
        """Build the gutter text repeated for *height* lines.

        Each line shows the same gutter string so that │ characters
        stack vertically, creating a continuous tree-line guide.

        An empty gutter string (root-level content nodes) produces a
        single space per line so the Horizontal layout keeps the gutter
        slot allocated.
        """
        if not self._gutter_text:
            # Root-level: no ancestor lines, just a tiny spacer.
            # A single space per line prevents the widget from collapsing.
            return "\n".join(" " for _ in range(max(1, height)))
        return "\n".join(self._gutter_text for _ in range(max(height, 1)))


# ---------------------------------------------------------------------------
# Helper — extract the ancestor portion from a prefix
# ---------------------------------------------------------------------------


def _extract_gutter(prefix: str) -> str:
    """Extract the gutter string from a full tree-line prefix.

    The prefix is built from 3-character segments (│  or    for ancestor
    levels) plus a 3-character connector (├─  or └─ ) for the node itself.

    The gutter is everything *except* the last 3 characters (the
    connector).  It contains the │ characters for ancestor levels that
    have more siblings below.

    Examples::

        >>> _extract_gutter("")
        ''
        >>> _extract_gutter("├─ ")
        ''
        >>> _extract_gutter("└─ ")
        ''
        >>> _extract_gutter("│  ├─ ")
        '│  '
        >>> _extract_gutter("│  └─ ")
        '│  '
        >>> _extract_gutter("   └─ ")
        '   '
        >>> _extract_gutter("│  │  └─ ")
        '│  │  '
        >>> _extract_gutter("│  │  ├─ ")
        '│  │  '
    """
    if len(prefix) <= 3:
        return ""
    return prefix[:-3]


# ---------------------------------------------------------------------------
# GutteredTreeRow — TreeRow with a left gutter on content widgets
# ---------------------------------------------------------------------------


class GutteredTreeRow(TreeRow):
    """A :class:`TreeRow` that adds a :class:`_RowGutter` beside content
    widgets so that tree-line │ characters continue through multi-line
    content.

    The gutter width matches the ancestor portion of the tree-line prefix.
    When the content widget resizes, this row catches the
    :class:`~textual.events.Resize` event and updates the gutter height
    to match, keeping the │ characters aligned.
    """

    def compose(self) -> ComposeResult:
        self._label = self._render_label_widget()

        if self.node.inline_edit is not None:
            self.add_class("with-inline-editor")

        if self.node.content is not None:
            # --- Content branch: label + gutter + content ---
            with Horizontal(classes="tree-row-inner"):
                yield self._label
                if self.node.inline_edit is not None:
                    yield self.node.inline_edit
                else:
                    for btn in self.node.buttons:
                        from textual.widgets import Button
                        yield Button(
                            btn.label,
                            id=f"act-{self.node.id}-{btn.action_id}",
                            classes="tree-icon-btn " + (btn.style or ""),
                        )

            # Content area with a left gutter
            gutter_text = _extract_gutter(self.prefix)
            gutter = _RowGutter(gutter_text)
            self._gutter = gutter

            with Horizontal(classes="tree-row-content guttered"):
                yield gutter
                yield self.node.content
        else:
            # --- No content: identical to base TreeRow ---
            self._gutter = None
            with Horizontal(classes="tree-row-inner"):
                yield self._label
                if self.node.inline_edit is not None:
                    yield self.node.inline_edit
                else:
                    for btn in self.node.buttons:
                        from textual.widgets import Button
                        yield Button(
                            btn.label,
                            id=f"act-{self.node.id}-{btn.action_id}",
                            classes="tree-icon-btn " + (btn.style or ""),
                        )

    def _render_label_widget(self):
        """Create the _RowLabel widget (factored out for reuse)."""
        from ui.tree.tree_row import _RowLabel
        label = _RowLabel(
            self._render_label(), self.node, self.is_branch, self
        )
        label.tooltip = (
            self.node.label_expanded
            if (self.expanded and self.node.label_expanded is not None)
            else self.node.label
        )
        return label

    def on_resize(self, event) -> None:
        """When this row resizes, check if the content widget changed
        height and update the gutter to match."""
        if not hasattr(self, "_gutter") or self._gutter is None:
            return
        if self.node.content is None:
            return
        # The content widget's region height tells us how many lines
        # the gutter should span.
        try:
            content_height = self.node.content.region.size.height
        except Exception:
            return
        if content_height and content_height > 0:
            self._gutter.update_height(content_height)

    def set_expanded(self, expanded: bool) -> None:
        """Update the expand/collapse indicator and re-render the label.

        Also updates the gutter text if the prefix changed (e.g. after
        a rebuild that reordered siblings).
        """
        self.expanded = expanded
        if hasattr(self, "_label"):
            self._label.update(self._render_label())
        # Update gutter text if we have one — the prefix may have
        # changed after a rebuild (sibling reorder).
        if hasattr(self, "_gutter") and self._gutter is not None:
            self._gutter.set_gutter(_extract_gutter(self.prefix))