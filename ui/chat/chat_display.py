"""Chat display — a Tree-backed conversation view with streaming Markdown sections.

Each assistant turn is a **branch** node with dynamically-created section
branches.  Sections are added on demand via :meth:`add_section` as their
content arrives during streaming, producing a natural sequential layout
(e.g. Thinking → Tools → Thinking → Response).
"""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Markdown

from ui.tree.tree import Tree
from ui.tree.tree_row import TreeNode


# ---------------------------------------------------------------------------
# ChatDisplay
# ---------------------------------------------------------------------------

_VALID_SECTIONS = frozenset({"thinking", "tools", "response"})
_SECTION_ICONS: dict[str, str] = {
    "thinking": "  \U000f0df6 Thinking",
    "tools": "  \U000f1074 Tools",
    "response": "  \U000f0b79 Response",
}


class ChatDisplay(Widget):
    """Streaming conversation display backed by a collapsible Tree.

    Provides a high-level API for building and updating a conversation:

    * ``add_user_message(text)`` → leaf node for user text.
    * ``begin_assistant_turn()`` → empty assistant branch node.
    * ``add_section(section_type)`` → new section branch, returns ID.
    * ``update_section(section_id, text)`` → streaming update.
    * ``finalize_turn()`` → removes any empty sections, clears state.
    """

    def __init__(self):
        super().__init__()
        self._root = TreeNode("chat-display-root", "Conversation")
        self._turn_count = 0
        self._section_count = 0
        self._active_asst_id: str | None = None

        # Populated by add_section, cleared by finalize_turn.
        # Maps section_id → Markdown widget.
        self._section_md: dict[str, Markdown] = {}

    # ------------------------------------------------------------------
    # Composition
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Tree(self._root)

    # ------------------------------------------------------------------
    # User messages
    # ------------------------------------------------------------------

    def add_user_message(self, text: str) -> str:
        """Add a user message leaf node.  Returns the node ID."""
        self._turn_count += 1
        node_id = f"msg-{self._turn_count}"
        label = f"\uf007  [cyan]User:[/cyan] {_truncate(text, 60)}"
        node = TreeNode(node_id, label, data={"role": "user"})
        self._root.children.append(node)
        self._rebuild()
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
        self._section_md = {}

        self._rebuild()

        # Expand the assistant branch.
        tree = self.query_one(Tree)
        tree.expand_node(asst_id)

        return asst_id

    def add_section(self, section_type: str) -> str:
        """Add a new section branch to the current assistant turn.

        *section_type* must be one of ``'thinking'``, ``'tools'``, or
        ``'response'``.  Returns the section ID for use with
        :meth:`update_section`.
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

        md = Markdown("", id=f"md-{section_id}")
        self._section_md[section_id] = md

        leaf = TreeNode(
            f"{section_id}-leaf", "",
            content=md,
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

        return section_id

    async def update_section(self, section_id: str, text: str) -> None:
        """Update the Markdown for the section identified by *section_id*.

        The section must have been created by a prior :meth:`add_section`
        call during the current assistant turn.
        """
        md = self._section_md.get(section_id)
        if md is None:
            return  # Unknown section — no-op.
        await md.update(text)
        # Guard: if Markdown._markdown wasn't set (race with mount),
        # store the text directly so it can be recovered.
        if not md._markdown:
            md._markdown = text

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
        self._section_md = {}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _is_empty_section(self, branch: TreeNode) -> bool:
        """Return True if the section branch's Markdown widget has no content."""
        md = self._section_md.get(branch.id)
        if md is None:
            return True
        return not md._markdown

    def _find_node(self, node_id: str) -> TreeNode | None:
        for child in self._root.children:
            if child.id == node_id:
                return child
        return None

    def _rebuild(self) -> None:
        """Rebuild and expand the tree."""
        tree = self.query_one(Tree)
        tree.rebuild()
        tree.expand_all()


def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def _format_args(args: dict[str, Any]) -> str:
    items = [f"{k}={v!r}" for k, v in args.items()]
    return ", ".join(items)[:60]