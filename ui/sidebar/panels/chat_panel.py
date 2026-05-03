"""Chat panel — sidebar tab with streaming conversation in a Tree widget.

Each assistant **response** is a branch node whose children contain
thinking, tool results, and a :class:`~textual.widgets.Markdown` widget
for streaming content.  User messages are leaf nodes.

Tree structure::

    root (Conversation)
    ├── 👤 User: "Hello"           ← leaf
    ├── 💭 Response                ← branch
    │   ├── 💡 Thinking: "..."     ← leaf
    │   ├── 🔧 Tool: ...           ← leaf
    │   └── 📝 [Markdown widget]   ← leaf with streaming content
    ├── 👤 User: "What is 2+2?"    ← leaf
    ├── 💭 Response                ← branch
    │   └── 📝 [Markdown widget]
"""

from __future__ import annotations

import uuid
from typing import Any

from textual.app import ComposeResult
from textual.containers import Container, Vertical
from textual.widgets import Input, Markdown, Static

from ui.sidebar.registry import register_sidebar_tab
from ui.tree.tree import Tree
from ui.tree.tree_row import TreeNode


@register_sidebar_tab(name="chat", icon="\uf4ad", side="right", tooltip="Chat")
class ChatPanel(Container):
    """Streaming chat panel using a Tree for collapsible message display.

    Each assistant response is a **branch** node.  The response text is
    rendered in a :class:`~textual.widgets.Markdown` widget (leaf child)
    that supports streaming via :meth:`update_response_text`.

    Provides:
    * ``add_message()`` — user leaf or response branch
    * ``add_thought()`` — thinking leaf under the current response
    * ``add_tool_result()`` — tool-call leaf under current response
    * ``update_response_text()`` — stream text into the Markdown widget
    """

    def __init__(self):
        super().__init__()
        self._root = TreeNode("chat-root", "Conversation")
        self._turn_count = 0
        self.last_assistant_id: str | None = None
        self._last_markdown: Markdown | None = None
        self._agent = None
        self._history: list[dict[str, Any]] = []

    def set_agent(self, agent) -> None:
        """Bind an :class:`Agent` instance for LLM conversations."""
        self._agent = agent

    def set_tools(self, tools: list[dict[str, Any]]) -> None:
        """Set the tool definitions to pass to the agent."""
        self._tools = tools

    def compose(self) -> ComposeResult:
        with Vertical():
            self._tree = Tree(self._root)
            yield self._tree
            self._input = Input(placeholder="Type a message…")
            yield self._input

    def on_mount(self) -> None:
        self._input.focus()

    # ------------------------------------------------------------------
    # Input handling → streaming agent
    # ------------------------------------------------------------------

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if not event.value.strip():
            return
        user_text = event.value
        self._input.clear()

        # Add user message to tree and history
        self.add_message("user", user_text)
        self._history.append({"role": "user", "content": user_text})

        # Create assistant response branch (with placeholder markdown)
        self.add_message("assistant", "…")

        if self._agent is None:
            self.update_response_text("No agent configured.")
            return

        # Stream from agent
        accumulated = ""
        try:
            async for chunk in self._agent.stream_chat(
                self._history,
                user_text,
                tools=getattr(self, '_tools', None),
            ):
                # Handle thinking
                if chunk.thinking:
                    self.add_thought(chunk.thinking)

                # Handle tool calls — reset accumulated text since
                # this iteration's content was intermediate.
                if chunk.tool_calls:
                    accumulated = ""
                    for tc in chunk.tool_calls:
                        self.add_tool_result(
                            tc.name, tc.arguments, "executing…"
                        )

                # Accumulate content into the markdown widget
                if chunk.content:
                    accumulated += chunk.content
                    self.update_response_text(accumulated)

        except Exception as exc:
            self.update_response_text(f"Error: {exc}")

        # Add final response to history
        if accumulated:
            self._history.append({
                "role": "assistant",
                "content": accumulated,
                "tool_calls": None,
            })

        self.last_assistant_id = None
        self._last_markdown = None
        self._input.focus()

    # ------------------------------------------------------------------
    # Message building
    # ------------------------------------------------------------------

    def add_message(self, role: str, content: str) -> str:
        """Add a message node to the tree.

        * ``role == "user"`` → leaf node with plain label.
        * ``role == "assistant"`` → **branch** node whose children
          include a :class:`~textual.widgets.Markdown` widget for
          streaming content.

        Returns the new node id.  Sets ``last_assistant_id`` for
        assistant messages.
        """
        self._turn_count += 1
        node_id = f"msg-{self._turn_count}"

        if role == "user":
            label = f"\uf007  User: {_truncate(content, 60)}"
            node = TreeNode(
                node_id, label,
                data={"role": role},
            )
        else:
            # Assistant → branch node with markdown child
            label = f"\uf4ad  Response"
            # Create a streaming Markdown widget
            md = Markdown(content, id=f"md-{node_id}")
            self._last_markdown = md
            md_child = TreeNode(
                f"md-{node_id}",
                "",  # label unused — widget renders itself
                content=md,
                data={"kind": "response"},
            )
            node = TreeNode(
                node_id, label,
                children=[md_child],
                data={"role": role},
            )

        self._root.children.append(node)

        if role == "assistant":
            self.last_assistant_id = node_id

        self._tree.set_root(self._root)
        self._tree.expand_all()
        return node_id

    def add_thought(self, thought: str) -> str:
        """Add a thinking leaf under the **last response branch**.

        If the last child is already a thought with the same kind,
        update it in-place (for streaming accumulation).
        """
        parent = self._get_last_assistant()
        if parent is None:
            return ""

        # If the last child is already a thought, update it
        for child in reversed(parent.children):
            if child.data.get("kind") == "thought":
                child.label = f"\uf0eb  Thinking: {thought}"
                self._tree.update_node_label(child.id, child.label)
                return child.id

        thought_id = f"thought-{uuid.uuid4().hex[:6]}"
        thought_node = TreeNode(
            thought_id,
            f"\uf0eb  Thinking: {thought}",
            data={"kind": "thought"},
        )
        parent.children.append(thought_node)
        self._tree.set_root(self._root)
        self._tree.expand_all()
        return thought_id

    def add_tool_result(
        self, tool_name: str, args: dict[str, Any], result: str
    ) -> str:
        """Add a tool-call leaf under the **last response branch**."""
        parent = self._get_last_assistant()
        if parent is None:
            return ""

        tool_id = f"tool-{uuid.uuid4().hex[:6]}"
        label = f"\uf552  {tool_name}({_format_args(args)}) → {_truncate(result, 80)}"
        tool_node = TreeNode(
            tool_id, label,
            data={"kind": "tool", "tool_name": tool_name, "result": result},
        )
        parent.children.append(tool_node)
        self._tree.set_root(self._root)
        self._tree.expand_all()
        return tool_id

    def update_response_text(self, text: str) -> None:
        """Stream text into the Markdown widget of the current response.

        Updates the :class:`~textual.widgets.Markdown` content in-place
        without rebuilding the tree.
        """
        if self._last_markdown is not None:
            self._last_markdown.update(text)

    def get_input(self) -> Input:
        return self._input

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _get_last_assistant(self) -> TreeNode | None:
        """Return the last assistant response branch node."""
        if self.last_assistant_id is None:
            return None
        return self._tree._node_map.get(self.last_assistant_id)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _format_args(args: dict[str, Any]) -> str:
    items = [f"{k}={v!r}" for k, v in args.items()]
    return ", ".join(items)[:60]


def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len - 3] + "..."
