"""Chat panel — sidebar tab with streaming conversation in a Tree widget.

Each message is a tree node.  User messages are plain leaf nodes.
Assistant responses are leaf nodes with a
:class:`~textual.widgets.Markdown` content widget that supports
streaming for all output: thinking, tool calls, and response text.

Tree structure::

    root (Conversation)
    ├── 👤 User: "Hello"           ← leaf (text label)
    ├── 💭 Response                ← leaf (Markdown widget)
    ├── 👤 User: "What is 2+2?"    ← leaf (text label)
    ├── 💭 Response                ← leaf (Markdown widget)
"""

from __future__ import annotations

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

    Each assistant response is a leaf node whose content is a
    :class:`~textual.widgets.Markdown` widget.  Thinking and tool-call
    output is folded into the markdown stream so everything appears
    inline with real-time updates.

    Provides:
    * ``add_message()`` — user leaf or response leaf with Markdown
    * ``add_thought()`` — append thinking text to the markdown widget
    * ``add_tool_result()`` — append tool result to the markdown widget
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
        self._db = None
        self._chat_id: str | None = None

    def set_agent(self, agent) -> None:
        """Bind an :class:`Agent` instance for LLM conversations."""
        self._agent = agent

    def set_tools(self, tools: list[dict[str, Any]]) -> None:
        """Set the tool definitions to pass to the agent."""
        self._tools = tools

    # ------------------------------------------------------------------
    # Mount — self-wire from app context
    # ------------------------------------------------------------------

    def on_mount(self) -> None:
        app = self.app
        if hasattr(app, 'context') and app.context is not None:
            ctx = app.context
            self._db = ctx.database if ctx.database is not None else None
            if self._agent is None:
                self._wire_agent(ctx)
            # Create a new chat session if we have a database.
            if self._db is not None:
                self._chat_id = self._db.create_chat()
        self._input.focus()

    def _wire_agent(self, ctx) -> None:
        """Build an :class:`Agent` and bind it from the app context."""
        from core.agent import Agent
        from core.providers.ollama import OllamaProvider
        from core.tools import get_tools
        from core.skills import skill_manager

        provider = OllamaProvider(ctx.config)
        agent = Agent(
            provider=provider,
            template="You are a helpful AI assistant. {{extra}}",
            variables={"extra": "Use tools when appropriate."},
            model=ctx.config.get("session.model", ""),
            skills_xml=skill_manager.get_catalog_xml(),
            ctx=ctx,
        )
        self._agent = agent
        self._tools = get_tools()

    def compose(self) -> ComposeResult:
        with Vertical():
            self._tree = Tree(self._root)
            yield self._tree
            self._input = Input(placeholder="Type a message…")
            yield self._input

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
            await self.update_response_text("No agent configured.")
            return

        # Stream from agent — thinking and content are accumulated
        # separately because thinking comes before content in the stream.
        # all_tool_calls captures every tool invocation for DB persistence.
        accumulated = ""
        thinking_accumulated = ""
        all_tool_calls: list[dict[str, Any]] = []
        try:
            async for chunk in self._agent.stream_chat(
                self._history,
                user_text,
                tools=getattr(self, '_tools', None),
            ):
                # Handle thinking — accumulate incrementally for streaming
                if chunk.thinking:
                    thinking_accumulated += chunk.thinking
                    display = f"\n💡 [gray]*{thinking_accumulated}*[/gray]\n"
                    await self.update_response_text(display)

                # Handle tool calls — fold into markdown as persistent text.
                # Previous accumulated content was intermediate (this iteration
                # led to tool calls), so replace it with tool call info.
                if chunk.tool_calls:
                    thinking_accumulated = ""
                    accumulated = ""
                    for tc in chunk.tool_calls:
                        all_tool_calls.append({
                            "name": tc.name,
                            "arguments": tc.arguments,
                        })
                        accumulated += (
                            f"\n🔧 `{tc.name}("
                            f"{_format_args(tc.arguments)})` → executing…\n"
                        )
                    await self.update_response_text(accumulated)

                # Accumulate content into the markdown widget.
                # On first content chunk, fold the thinking prefix into
                # the accumulated text so it appears before the response.
                if chunk.content:
                    if thinking_accumulated and not accumulated:
                        accumulated = f"\n💡 *{thinking_accumulated}*\n\n"
                    accumulated += chunk.content
                    await self.update_response_text(accumulated)

        except Exception as exc:
            await self.update_response_text(f"Error: {exc}")

        # Add final response to in-memory history.
        if accumulated:
            self._history.append({
                "role": "assistant",
                "content": accumulated,
                "tool_calls": all_tool_calls if all_tool_calls else None,
            })

        # Persist the full turn to the database — once, at the end.
        self._save_turn(
            user_text, accumulated,
            thinking=thinking_accumulated,
            tool_calls=all_tool_calls if all_tool_calls else None,
        )

        self.last_assistant_id = None
        self._last_markdown = None
        self._input.focus()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save_turn(
        self,
        user_text: str,
        assistant_text: str,
        thinking: str = "",
        tool_calls: list[dict[str, Any]] | None = None,
    ) -> None:
        """Save user + assistant messages to the database."""
        if self._db is None or self._chat_id is None:
            return
        try:
            self._db.save_message(self._chat_id, "user", user_text)
            self._db.save_message(
                self._chat_id,
                "assistant",
                assistant_text,
                tool_calls=tool_calls,
                thinking=thinking,
            )
        except Exception:
            pass  # Don't break the UI for a persistence failure.

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
            label = f"\uf007  [cyan]User:[/cyan] {_truncate(content, 60)}"
            node = TreeNode(
                node_id, label,
                data={"role": role},
            )
        else:
            # Assistant → leaf node with streaming Markdown widget as content
            label = f"\uf4ad  [green]Assistant:[/green]"
            md = Markdown(content, id=f"md-{node_id}")
            self._last_markdown = md
            node = TreeNode(
                node_id, label,
                content=md,
                data={"role": role},
            )

        self._root.children.append(node)

        if role == "assistant":
            self.last_assistant_id = node_id

        self._tree.rebuild()
        self._tree.expand_all()
        return node_id

    def add_thought(self, thought: str) -> str:
        """Display thinking text inline in the markdown widget."""
        if self._last_markdown is None:
            return ""
        current = self._last_markdown._markdown or ""
        new_text = f"{current}\n💡 *{thought}*\n"
        # Fire-and-forget — will render on next message pump
        self._last_markdown.update(new_text)
        return "thought"

    def add_tool_result(
        self, tool_name: str, args: dict[str, Any], result: str
    ) -> str:
        """Display tool call/result inline in the markdown widget."""
        if self._last_markdown is None:
            return ""
        current = self._last_markdown._markdown or ""
        new_text = (
            f"{current}\n🔧 `{tool_name}("
            f"{_format_args(args)})` → {_truncate(result, 80)}\n"
        )
        self._last_markdown.update(new_text)
        return "tool"

    async def update_response_text(self, text: str) -> None:
        """Stream text into the Markdown widget of the current response.

        Updates the :class:`~textual.widgets.Markdown` content in-place
        without rebuilding the tree.  Must be awaited because
        :meth:`Markdown.update` is asynchronous.
        """
        if self._last_markdown is not None:
            await self._last_markdown.update(text)

    def get_input(self) -> Input:
        return self._input

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------


def _format_args(args: dict[str, Any]) -> str:
    items = [f"{k}={v!r}" for k, v in args.items()]
    return ", ".join(items)[:60]


def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len - 3] + "..."
