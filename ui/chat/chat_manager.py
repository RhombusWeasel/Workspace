"""Chat manager — orchestrates streaming chat between input, display, agent, and database.

Composes a :class:`~ui.chat.chat_input.ChatInput` and
:class:`~ui.chat.chat_display.ChatDisplay`, catching ``ChatSubmitted``
messages and driving the full streaming cycle through an LLM agent.
"""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widget import Widget

from ui.chat.chat_input import ChatInput
from ui.chat.chat_display import ChatDisplay


class ChatManager(Widget):
    """Orchestrates a streaming conversation.

    Composes a ``ChatInput`` and ``ChatDisplay``.  Listens for
    ``ChatInput.ChatSubmitted``, runs the agent streaming loop, updates
    the display, tracks history, and optionally persists turns to a
    database.
    """

    def __init__(self):
        super().__init__()
        self._agent: Any = None
        self._tools: list[dict[str, Any]] | None = None
        self._history: list[dict[str, Any]] = []
        self._db: Any = None
        self._chat_id: str | None = None

    # ------------------------------------------------------------------
    # Composition
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        with Vertical():
            self._chat_display = ChatDisplay()
            self._chat_input = ChatInput()
            yield self._chat_display
            yield self._chat_input

    def on_mount(self) -> None:
        self._chat_input.focus()

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def set_agent(self, agent: Any) -> None:
        """Set the LLM agent used for streaming responses."""
        self._agent = agent

    def set_tools(self, tools: list[dict[str, Any]]) -> None:
        """Set the list of available tools passed to the agent."""
        self._tools = tools

    def wire_from_context(self, ctx: Any) -> None:
        """Wire agent, tools, and database from an ``AppContext``.

        If no agent was explicitly set, this creates a default agent
        using ``OllamaProvider`` and the current skill catalog.
        """
        if ctx.database is not None:
            self._db = ctx.database
            self._chat_id = self._db.create_chat()
        if self._agent is None:
            self._wire_agent(ctx)

    def _wire_agent(self, ctx: Any) -> None:
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

    # ------------------------------------------------------------------
    # Message handling → streaming cycle
    # ------------------------------------------------------------------

    def on_chat_input_chat_submitted(self, event: ChatInput.ChatSubmitted) -> None:
        """Handle a user submission — kick off the streaming turn."""
        self._chat_input.clear()
        self.run_worker(self._handle_submit(event.text))

    async def _handle_submit(self, user_text: str) -> None:
        """Full streaming turn: display user msg, stream assistant, save."""
        # User message in display and history.
        self._chat_display.add_user_message(user_text)
        self._history.append({"role": "user", "content": user_text})

        # Assistant branch.
        asst_id = self._chat_display.begin_assistant_turn()

        if self._agent is None:
            await self._chat_display.update_section("response", "No agent configured.")
            self._chat_display.finalize_turn()
            self._chat_input.focus()
            return

        accumulated = ""
        thinking_accumulated = ""
        all_tool_calls: list[dict[str, Any]] = []
        tools_text = ""

        try:
            async for chunk in self._agent.stream_chat(
                self._history,
                user_text,
                tools=self._tools,
            ):
                # --- Thinking ---
                if chunk.thinking:
                    thinking_accumulated += chunk.thinking
                    await self._chat_display.update_section(
                        "thinking", thinking_accumulated
                    )

                # --- Tool calls ---
                if chunk.tool_calls:
                    # Tool calls replace thinking display (agent stops thinking).
                    if thinking_accumulated:
                        await self._chat_display.update_section("thinking", "")
                        thinking_accumulated = ""
                    accumulated = ""

                    for tc in chunk.tool_calls:
                        all_tool_calls.append({
                            "name": tc.name,
                            "arguments": tc.arguments,
                        })
                        tools_text += (
                            f"🔧 `{tc.name}("
                            f"{_format_args(tc.arguments)})`\n"
                        )
                    await self._chat_display.update_section("tools", tools_text)

                # --- Response text ---
                if chunk.content:
                    accumulated += chunk.content
                    await self._chat_display.update_section(
                        "response", accumulated
                    )

        except Exception as exc:
            await self._chat_display.update_section(
                "response", f"Error: {exc}"
            )

        # --- Post-turn ---
        if accumulated:
            self._history.append({
                "role": "assistant",
                "content": accumulated,
                "thinking": thinking_accumulated,
                "tool_calls": all_tool_calls if all_tool_calls else None,
            })

        self._save_turn(
            user_text, accumulated,
            thinking=thinking_accumulated,
            tool_calls=all_tool_calls if all_tool_calls else None,
        )

        self._chat_display.finalize_turn()
        self._chat_input.focus()

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
            pass


def _format_args(args: dict[str, Any]) -> str:
    items = [f"{k}={v!r}" for k, v in args.items()]
    return ", ".join(items)[:60]
