"""Chat display — a Tree-backed conversation view with streaming Markdown sections.

Each assistant turn is a **branch** node with up to three collapsible
section branches (Thinking, Tools, Response), each holding a ``Markdown``
widget that can be updated independently during streaming.
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
    "thinking": "  󰟶 Thinking",
    "tools": "  󱁤 Tools",
    "response": "  󰭹 Response",
}


class ChatDisplay(Widget):
    """Streaming conversation display backed by a collapsible Tree.

    Provides a high-level API for building and updating a conversation:

    * ``add_user_message(text)`` → leaf node for user text.
    * ``begin_assistant_turn()`` → branch node with empty section children.
    * ``update_section(section, text)`` → streaming update to a Markdown widget.
    * ``finalize_turn()`` → removes empty sections, clears internal state.
    """

    def __init__(self):
        super().__init__()
        self._root = TreeNode("chat-display-root", "Conversation")
        self._turn_count = 0
        self._active_asst_id: str | None = None

        # Populated by begin_assistant_turn, cleared by finalize_turn.
        self._section_md: dict[str, Markdown] = {}
        self._active_sections: set[str] = set()

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
        """Create an assistant branch with three empty section children.

        Returns the assistant branch node ID.  After calling this, use
        ``update_section()`` to stream content and ``finalize_turn()``
        to clean up.
        """
        self._turn_count += 1
        asst_id = f"msg-{self._turn_count}"

        # Build three section branches, each with a Markdown leaf.
        section_branches: list[TreeNode] = []
        md_map: dict[str, Markdown] = {}

        for section in ("thinking", "tools", "response"):
            md = Markdown("", id=f"md-{section}-{asst_id}")
            md_map[section] = md
            leaf = TreeNode(
                f"{section}-leaf-{asst_id}", "",
                content=md,
            )
            branch = TreeNode(
                f"{section}-{asst_id}", _SECTION_ICONS.get(section, section),
                data={"section": section},
                children=[leaf],
            )
            section_branches.append(branch)

        asst_node = TreeNode(
            asst_id, "\uf4ad  [green]Assistant[/green]",
            children=section_branches,
            data={"role": "assistant", "type": "branch"},
        )
        self._root.children.append(asst_node)

        self._active_asst_id = asst_id
        self._section_md = md_map
        self._active_sections = set()

        self._rebuild()

        # Auto-expand section branches so Markdown children are visible.
        tree = self.query_one(Tree)
        for section in ("thinking", "tools", "response"):
            tree.expand_node(f"{section}-{asst_id}")

        return asst_id

    async def update_section(self, section: str, text: str) -> None:
        """Update the Markdown for *section*.

        *section* must be one of ``'thinking'``, ``'tools'``, ``'response'``.
        The section is marked as active so ``finalize_turn()`` preserves it.
        """
        if section not in _VALID_SECTIONS:
            raise ValueError(
                f"Unknown section {section!r}; must be one of {sorted(_VALID_SECTIONS)}"
            )
        md = self._section_md.get(section)
        if md is None:
            return  # No active turn.
        self._active_sections.add(section)
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
                if c.data.get("section") in self._active_sections
            ]
            if len(keep) != len(node.children):
                node.children = keep
                self._rebuild()

        self._active_asst_id = None
        self._section_md = {}
        self._active_sections = set()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

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
