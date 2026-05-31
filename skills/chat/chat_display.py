"""Chat display — a Tree-backed conversation view with streaming Markdown sections.

Each assistant turn is a **branch** node with dynamically-created section
branches.  Sections are added on demand via :meth:`add_section` as their
content arrives during streaming, producing a natural sequential layout
(e.g. Thinking → Tools → Thinking → Response).

Thinking sections use plain :class:`~textual.widgets.Static` text instead
of :class:`~textual.widgets.Markdown` to reduce re-rendering overhead during
streaming.  This eliminates expensive markdown parsing on every chunk when
a reasoning model emits rapid thinking tokens.

The display auto-scrolls to the bottom when new content is added or
updated, so the view follows along with streaming output.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Markdown, Static

from ui.tree.tree import Tree
from ui.tree.tree_row import TreeNode


# ---------------------------------------------------------------------------
# ChatDisplay
# ---------------------------------------------------------------------------

_VALID_SECTIONS = frozenset({"thinking", "tools", "response", "system"})
_SECTION_ICONS: dict[str, str] = {
    "thinking": "  \U000f0df6 Thinking",
    "tools": "  \U000f1074 Tools",
    "response": "  \U000f0b79 Response",
    "system": "  \U000f0e38 System",
}

# Section types rendered as plain Static text instead of Markdown.
# Thinking output can be very long and is updated rapidly during streaming;
# using Static (no markdown parsing) reduces rendering overhead significantly.
_PLAIN_TEXT_SECTIONS = frozenset({"thinking"})


class ChatDisplay(Widget):
    """Streaming conversation display backed by a collapsible Tree.

    Provides a high-level API for building and updating a conversation:

    * ``add_user_message(text)`` → branch node for user text (with Markdown leaf).
    * ``begin_assistant_turn()`` → empty assistant branch node.
    * ``add_section(section_type)`` → new section branch, returns ID.
    * ``update_section(section_id, text)`` → streaming update.
    * ``finalize_turn()`` → removes any empty sections, clears state.

    Thinking sections are rendered as plain ``Static`` text (no markdown)
    to reduce re-rendering cost during fast streaming.  All other sections
    use ``Markdown`` for rich formatting.
    """

    def __init__(self):
        super().__init__()
        self._root = TreeNode("chat-display-root", "Conversation")
        self._turn_count = 0
        self._section_count = 0
        self._active_asst_id: str | None = None

        # Populated by add_section, cleared by finalize_turn.
        # Maps section_id → content widget (Markdown or Static).
        self._section_widgets: dict[str, Widget] = {}
        # Maps section_id → accumulated text (for emptiness checks).
        self._section_texts: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Composition
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Tree(self._root)

    # ------------------------------------------------------------------
    # Scrolling
    # ------------------------------------------------------------------

    def _scroll_to_bottom(self) -> None:
        """Scroll the chat tree to show the latest content.

        Best-effort — does not raise if the tree is not yet mounted.
        Called after adding content or updating sections so that the
        view follows the streaming output.
        """
        try:
            tree = self.query_one(Tree)
            tree.scroll_end(animate=False)
        except Exception:
            pass

    def _schedule_scroll(self) -> None:
        """Schedule a deferred scroll-to-bottom after layout recalculates.

        Content updates (adding nodes, updating sections) change the
        tree's virtual size, but the layout pass happens asynchronously.
        Calling ``scroll_end()`` immediately would use the old virtual
        size, so we defer by ~1 frame to let the layout catch up.
        """
        self.set_timer(1 / 60, self._scroll_to_bottom)

    # ------------------------------------------------------------------
    # User messages
    # ------------------------------------------------------------------

    def add_user_message(self, text: str) -> str:
        """Add a user message as a branch node with a Markdown leaf.

        Creates an expandable **User** branch whose child is a Markdown
        widget rendering the full message.  The branch auto-expands so
        the user can see what they just typed.

        When expanded the label shows ``\uf007  User``; when collapsed
        it shows a truncated preview like ``\uf007  User: Hello there...``.

        Returns the branch node ID.
        """
        self._turn_count += 1
        node_id = f"msg-{self._turn_count}"

        # Markdown leaf for the full user text.
        md = Markdown(text, id=f"md-{node_id}")
        leaf = TreeNode(f"{node_id}-leaf", "", content=md)

        # Branch — dual labels so collapsed state shows a preview.
        preview = _truncate(text, 60)
        branch = TreeNode(
            node_id,
            f"\uf007  [cyan]User:[/cyan] {preview}",
            label_expanded="\uf007  [cyan]User[/cyan]",
            data={"role": "user"},
            children=[leaf],
        )
        self._root.children.append(branch)
        self._rebuild()

        # Expand the new user branch by default.
        tree = self.query_one(Tree)
        tree.expand_node(node_id)

        self._schedule_scroll()

        return node_id

    # ------------------------------------------------------------------
    # Assistant turn lifecycle
    # ------------------------------------------------------------------

    def begin_assistant_turn(self) -> str:
        """Create an assistant branch node with **no** section children.

        Sections are added on demand via :meth:`add_section` as their
        content arrives during streaming.  Returns the assistant branch
        node ID.
        """
        self._turn_count += 1
        asst_id = f"msg-{self._turn_count}"

        asst_node = TreeNode(
            asst_id, "\uf4ad  [green]Assistant[/green]",
            data={"role": "assistant", "type": "branch"},
        )
        self._root.children.append(asst_node)

        self._active_asst_id = asst_id
        self._section_widgets = {}
        self._section_texts = {}

        self._rebuild()

        # Expand the assistant branch.
        tree = self.query_one(Tree)
        tree.expand_node(asst_id)

        self._schedule_scroll()

        return asst_id

    def add_section(self, section_type: str) -> str:
        """Add a new section branch to the current assistant turn.

        *section_type* must be one of ``'thinking'``, ``'tools'``, or
        ``'response'``.  Returns the section ID for use with
        :meth:`update_section`.

        Thinking sections use a plain :class:`~textual.widgets.Static`
        widget instead of :class:`~textual.widgets.Markdown` to reduce
        re-rendering overhead during streaming.
        """
        if section_type not in _VALID_SECTIONS:
            raise ValueError(
                f"Unknown section type {section_type!r}; "
                f"must be one of {sorted(_VALID_SECTIONS)}"
            )
        if self._active_asst_id is None:
            raise RuntimeError(
                "No active assistant turn — call begin_assistant_turn first"
            )

        self._section_count += 1
        section_id = f"{section_type}-sec{self._section_count}"

        # Use Static (plain text) for thinking, Markdown for everything else.
        if section_type in _PLAIN_TEXT_SECTIONS:
            widget: Widget = Static(
                "", markup=False,
                id=f"md-{section_id}", classes="thinking-content",
            )
        else:
            widget = Markdown("", id=f"md-{section_id}")

        self._section_widgets[section_id] = widget
        self._section_texts[section_id] = ""

        leaf = TreeNode(
            f"{section_id}-leaf", "",
            content=widget,
        )
        branch = TreeNode(
            section_id,
            _SECTION_ICONS.get(section_type, section_type),
            data={"section": section_type},
            children=[leaf],
        )

        # Append to the current assistant node.
        asst_node = self._find_node(self._active_asst_id)
        if asst_node is not None:
            asst_node.children.append(branch)

        self._rebuild()

        # Expand the new section and its parent.
        tree = self.query_one(Tree)
        tree.expand_node(section_id)
        tree.expand_node(self._active_asst_id)

        self._schedule_scroll()

        return section_id

    async def update_section(self, section_id: str, text: str) -> None:
        """Update the content widget for the section identified by *section_id*.

        For thinking sections (Static), this is a lightweight synchronous
        update — no markdown parsing.  For other sections (Markdown),
        this is an async re-render.  In both cases, the display scrolls
        to show the latest content.

        The section must have been created by a prior :meth:`add_section`
        call during the current assistant turn.
        """
        widget = self._section_widgets.get(section_id)
        if widget is None:
            return  # Unknown section — no-op.

        self._section_texts[section_id] = text

        if isinstance(widget, Static):
            # Plain text update — fast, no markdown parsing.
            widget.update(text)
        elif isinstance(widget, Markdown):
            # Markdown update — async re-render.
            await widget.update(text)
            # Guard: if Markdown._markdown wasn't set (race with mount),
            # store the text directly so it can be recovered.
            if not widget._markdown:
                widget._markdown = text

        self._schedule_scroll()

    def finalize_turn(self) -> None:
        """Remove empty section children, rebuild tree, clear internal state."""
        asst_id = self._active_asst_id
        if asst_id is None:
            return

        node = self._find_node(asst_id)
        if node is not None:
            keep = [
                c for c in node.children
                if not self._is_empty_section(c)
            ]
            if len(keep) != len(node.children):
                node.children = keep
                self._rebuild()

        self._active_asst_id = None
        self._section_widgets = {}
        self._section_texts = {}

    # ------------------------------------------------------------------
    # System messages (command feedback)
    # ------------------------------------------------------------------

    def add_system_message(self, text: str) -> str:
        """Add a system message as a standalone branch with a Markdown leaf.

        System messages are used for command feedback (e.g. "Chat cleared.").
        They appear as a single branch with a Markdown child, similar to
        user messages but styled differently.

        Returns the branch node ID.
        """
        self._turn_count += 1
        node_id = f"msg-{self._turn_count}"

        md = Markdown(text, id=f"md-{node_id}")
        leaf = TreeNode(f"{node_id}-leaf", "", content=md)

        branch = TreeNode(
            node_id,
            "  \U000f0e38 [dim]System[/dim]",
            data={"role": "system"},
            children=[leaf],
        )
        self._root.children.append(branch)
        self._rebuild()

        tree = self.query_one(Tree)
        tree.expand_node(node_id)

        self._schedule_scroll()

        return node_id

    # ------------------------------------------------------------------
    # Reset
    # ------------------------------------------------------------------

    def clear(self) -> None:
        """Remove all messages from the display and reset internal state.

        Does not affect the database — only clears the visual tree.
        """
        self._root.children.clear()
        self._turn_count = 0
        self._section_count = 0
        self._active_asst_id = None
        self._section_widgets = {}
        self._section_texts = {}
        self._rebuild()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _is_empty_section(self, branch: TreeNode) -> bool:
        """Return True if the section branch's content widget has no text."""
        return not self._section_texts.get(branch.id)

    def _find_node(self, node_id: str) -> TreeNode | None:
        for child in self._root.children:
            if child.id == node_id:
                return child
        return None

    def _rebuild(self) -> None:
        """Rebuild the tree and restore expand/collapse state.

        Uses :meth:`Tree.restore_expand_state` so that branches the
        user has manually collapsed stay collapsed across rebuilds.
        New nodes are expanded by default.
        """
        tree = self.query_one(Tree)
        tree.rebuild()
        tree.restore_expand_state()


def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."