"""Chat manager — orchestrates streaming chat between input, display, agent, and database.

Composes a :class:`~ui.chat.chat_input.ChatInput` and
:class:`~ui.chat.chat_display.ChatDisplay`, catching ``ChatSubmitted``
messages and driving the full streaming cycle through an LLM agent.
"""

from __future__ import annotations

import asyncio
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

        # Assistant branch (no sections yet — added on demand).
        self._chat_display.begin_assistant_turn()

        # New rows were mounted synchronously; yield to the event loop
        # so the assistant branch finishes its mount lifecycle before we
        # add sections to it.
        self.refresh(layout=True)
        await asyncio.sleep(0)

        if self._agent is None:
            section_id = self._chat_display.add_section("response")
            await self._chat_display.update_section(section_id, "No agent configured.")
            self._chat_display.finalize_turn()
            self._chat_input.focus()
            return

        # Track the currently active display section.  When the
        # content type transitions we close out the current section
        # and open a new one — this produces the sequential layout
        # (Thinking → Tools → Thinking → … → Response).
        current_section_id: str | None = None
        current_section_type: str | None = None
        section_text: str = ""

        # Persistence accumulators (independent of display sections).
        all_thinking: str = ""
        all_tool_calls: list[dict[str, Any]] = []
        final_response: str = ""

        try:
            async for chunk in self._agent.stream_chat(
                self._history,
                user_text,
                tools=self._tools,
            ):
                # --- Thinking ---
                if chunk.thinking:
                    if current_section_type != "thinking":
                        current_section_id = self._chat_display.add_section("thinking")
                        current_section_type = "thinking"
                        section_text = ""
                    section_text += chunk.thinking
                    all_thinking += chunk.thinking
                    await self._chat_display.update_section(
                        current_section_id, section_text
                    )

                # --- Tool calls ---
                if chunk.tool_calls:
                    # Tool calls mark a transition — close the current section
                    # and open a new tools section.  Each round of tool calls
                    # gets its own section in the display.
                    current_section_id = None
                    current_section_type = None
                    section_text = ""

                    tools_section_id = self._chat_display.add_section("tools")
                    tools_text = ""
                    for tc in chunk.tool_calls:
                        all_tool_calls.append({
                            "name": tc.name,
                            "arguments": tc.arguments,
                        })
                        tools_text += (
                            f"\U0001f527 `{tc.name}("
                            f"{_format_args(tc.arguments)})`\n"
                        )
                    await self._chat_display.update_section(
                        tools_section_id, tools_text
                    )

                # --- Response text ---
                if chunk.content:
                    if current_section_type != "response":
                        current_section_id = self._chat_display.add_section("response")
                        current_section_type = "response"
                        section_text = ""
                    section_text += chunk.content
                    final_response = section_text
                    await self._chat_display.update_section(
                        current_section_id, section_text
                    )

        except Exception as exc:
            if current_section_type != "response":
                current_section_id = self._chat_display.add_section("response")
                current_section_type = "response"
                section_text = ""
            section_text = f"Error: {exc}"
            await self._chat_display.update_section(
                current_section_id, section_text
            )

        # --- Post-turn ---
        if final_response:
            self._history.append({
                "role": "assistant",
                "content": final_response,
                "thinking": all_thinking or None,
                "tool_calls": all_tool_calls if all_tool_calls else None,
            })

        self._save_turn(
            user_text, final_response,
            thinking=all_thinking,
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