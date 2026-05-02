"""Chat panel — sidebar tab with streaming conversation in a Tree widget.

Messages are displayed in a collapsible tree:
- User messages as leaf nodes
- Assistant responses as branch nodes with children for thinking,
  tool calls, and final response text.

Streaming updates the last assistant node in-place via
:meth:`Tree.update_node_label`.
"""

from __future__ import annotations

import uuid
from typing import Any

from textual.app import ComposeResult
from textual.containers import Container, Vertical
from textual.widgets import Input, Static

from ui.sidebar.registry import register_sidebar_tab
from ui.tree.tree import Tree
from ui.tree.tree_row import TreeNode


@register_sidebar_tab(name="chat", icon="\uf4ad", side="right", tooltip="Chat")
class ChatPanel(Container):
    """Streaming chat panel using a Tree for collapsible message display.

    Provides ``add_message()``, ``add_thought()``, and
    ``add_tool_result()`` for building conversation nodes.
    ``last_assistant_id`` tracks the current response for
    streaming updates.
    """

    DEFAULT_CSS = """
    ChatPanel {
        height: 1fr;
    }

    ChatPanel > Vertical {
        height: 1fr;
    }

    ChatPanel Tree {
        height: 1fr;
    }

    ChatPanel Input {
        dock: bottom;
    }
    """

    def __init__(self):
        super().__init__()
        self._root = TreeNode("chat-root", "Conversation")
        self._turn_count = 0
        self.last_assistant_id: str | None = None
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

        # Create assistant placeholder
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

                # Handle tool calls (on the final chunk)
                if chunk.tool_calls:
                    for tc in chunk.tool_calls:
                        # We don't have the result yet — the agent handles
                        # execution internally.  Just log the call.
                        self.add_tool_result(
                            tc.name, tc.arguments, "executing…"
                        )

                # Accumulate content
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
        self._input.focus()

    # ------------------------------------------------------------------
    # Message building
    # ------------------------------------------------------------------

    def add_message(self, role: str, content: str) -> str:
        """Add a top-level message node and return its id.

        ``role`` should be ``"user"`` or ``"assistant"``.
        Sets ``last_assistant_id`` for assistant messages.
        """
        self._turn_count += 1
        node_id = f"msg-{self._turn_count}"

        prefix = "\uf007" if role == "user" else "\uf4ad"
        label = f"{prefix} {role.title()}: {content}"

        node = TreeNode(node_id, label, children=[],
                        data={"role": role})
        self._root.children.append(node)

        if role == "assistant":
            self.last_assistant_id = node_id

        self._tree.set_root(self._root)
        self._tree.expand_all()
        return node_id

    def add_thought(self, thought: str) -> str:
        """Add a thinking child under the last assistant message.

        If the last child is already a thought, update it instead
        (streaming accumulation).
        """
        parent = self._get_last_assistant()
        if parent is None:
            return ""

        # Check if the last child is already a thought
        if parent.children and parent.children[-1].data.get("kind") == "thought":
            # Update existing thought node
            thought_node = parent.children[-1]
            thought_node.label = f"\uf0eb  Thinking: {thought}"
            self._tree.update_node_label(thought_node.id, thought_node.label)
            return thought_node.id

        thought_id = f"thought-{uuid.uuid4().hex[:6]}"
        thought_node = TreeNode(
            thought_id,
            f"\uf0eb  Thinking: {thought}",
            data={"kind": "thought"}
        )
        parent.children.append(thought_node)
        self._tree.set_root(self._root)
        self._tree.expand_all()
        return thought_id

    def add_tool_result(
        self, tool_name: str, args: dict[str, Any], result: str
    ) -> str:
        """Add a tool-call result child under the last assistant message."""
        parent = self._get_last_assistant()
        if parent is None:
            return ""

        tool_id = f"tool-{uuid.uuid4().hex[:6]}"
        label = f"\uf552  {tool_name}({_format_args(args)}) → {_truncate(result, 80)}"
        tool_node = TreeNode(
            tool_id, label,
            data={"kind": "tool", "tool_name": tool_name, "result": result}
        )
        parent.children.append(tool_node)
        self._tree.set_root(self._root)
        self._tree.expand_all()
        return tool_id

    def update_response_text(self, text: str) -> None:
        """Update the last assistant message's label with accumulated text."""
        if self.last_assistant_id is None:
            return
        node = self._tree._node_map.get(self.last_assistant_id)
        if node is None:
            return
        node.label = f"\uf4ad  Assistant: {text}"
        self._tree.update_node_label(self.last_assistant_id, node.label)

    def get_input(self) -> Input:
        return self._input

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _get_last_assistant(self) -> TreeNode | None:
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
