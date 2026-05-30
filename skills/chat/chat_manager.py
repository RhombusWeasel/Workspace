"""Chat manager — orchestrates streaming chat between input, display, agent, and database.

Composes a :class:`~ui.chat.chat_input.ChatInput` and
:class:`~ui.chat.chat_display.ChatDisplay`, catching ``ChatSubmitted``
messages and driving the full streaming cycle through an LLM agent.

Supports aborting an in-progress stream via the abort button or
``Escape`` key.  When aborted, the partial response is preserved
in the display and database.

Section management is delegated to :class:`~ui.chat.stream_section.StreamSection`
instances — one per display section (thinking, tool_call, response).
The manager creates a new section each time the stream transitions
to a different chunk type.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widget import Widget
from textual.widgets import Input

from core.commands import execute_command, list_commands
from skills.chat.chat_input import ChatInput
from skills.chat.chat_display import ChatDisplay
from skills.chat.command_palette import CommandPalette
from skills.chat.file_palette import FilePalette
from skills.chat.stream_section import StreamSection
from skills.chat.tool_format import format_tool_call_display, format_tool_call_json


class ChatManager(Widget):
    """Orchestrates a streaming conversation.

    Composes a ``ChatInput`` and ``ChatDisplay``.  Listens for
    ``ChatInput.ChatSubmitted``, runs the agent streaming loop, updates
    the display via :class:`StreamSection` watchers, and persists each
    section to the database as it completes.

    State persistence: The ``_state`` attribute holds a reference to the
    tab's :class:`~skills.chat.chat_tab.ChatTabState`.  When the
    workspace is recomposed (split / close), ``flush_state()`` copies
    the widget's internal state back to ``ChatTabState`` so it survives
    DOM destruction.  The content factory then creates a fresh
    ChatManager that calls ``set_state()`` to adopt the saved data.

    Aborting:  When the user presses the abort button or Escape during
    a stream, ``ChatInput.ChatAbortRequested`` is caught here.  The
    agent's ``abort()`` method is called, the ``CancelledError``
    exception from the streaming loop is handled gracefully, and the
    partial response is saved.
    """

    def __init__(self):
        super().__init__()
        self._agent: Any = None
        self._tools: list[dict[str, Any]] | None = None
        self._history: list[dict[str, Any]] = []
        self._sections: list[dict[str, str]] = []
        """In-memory mirror of flat sections — used to build history when
        there is no database, and kept in sync for consistency."""
        self._db: Any = None
        self._chat_id: str | None = None
        self._streaming_task: asyncio.Task | None = None
        self._state: Any = None
        """Reference to the owning ChatTabState, set via ``set_state()``.

        When the workspace is recomposed, ``flush_state()`` copies the
        widget's conversation data into this state object.  After
        recomposition, the content factory calls ``set_state()`` on the
        fresh ChatManager so it can adopt the persisted data."""

    # ------------------------------------------------------------------
    # Composition
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        with Vertical():
            self._chat_display = ChatDisplay()
            self._chat_palette = CommandPalette()
            self._file_palette = FilePalette()
            self._chat_input = ChatInput()
            yield self._chat_display
            yield self._chat_palette
            yield self._file_palette
            yield self._chat_input

    def on_mount(self) -> None:
        self._chat_input.focus()
        # Wire up palette references so ChatInput can control them
        self._chat_input.set_palette(self._chat_palette)
        self._chat_input.set_file_palette(self._file_palette)
        # Set working directory on file palette for scanning
        if hasattr(self.app, "context") and self.app.context is not None:
            self._file_palette.set_working_directory(
                self.app.context.working_directory
            )

        # If state was restored, rebuild the visual display asynchronously.
        # The rebuild needs to await Markdown.update() calls, so it runs
        # as a background worker.
        if self._state is not None and self._sections:
            self.run_worker(self._rebuild_display_from_sections())

    # ------------------------------------------------------------------
    # State persistence (survives workspace recomposition)
    # ------------------------------------------------------------------

    def set_state(self, state: Any) -> None:
        """Adopt conversation state from a ChatTabState.

        Called by the content factory when recreating the ChatManager
        after a workspace recomposition.  Restores the internal state
        from the persisted data so the conversation continues seamlessly.
        """
        self._state = state
        self._history = state._history
        self._sections = state._sections
        self._agent = state._agent
        self._tools = state._tools
        self._db = state._db
        self._chat_id = state._chat_id

    def flush_state(self) -> None:
        """Sync current widget state back to the ChatTabState.

        Called by :meth:`WorkspaceTabs.save_state` before a DOM
        recomposition.  Copies the widget's internal state into the
        persistent state object so the fresh widget can restore it
        after the rebuild.
        """
        if self._state is not None:
            self._state._history = self._history
            self._state._sections = self._sections
            self._state._agent = self._agent
            self._state._tools = self._tools
            self._state._db = self._db
            self._state._chat_id = self._chat_id

    async def _rebuild_display_from_sections(self) -> None:
        """Reconstruct the chat display from persisted sections.

        Groups sections by turn_id and replays them into the ChatDisplay
        so the user sees their conversation restored after a workspace
        recomposition (split / close).

        This method is async because it needs to await Markdown.update()
        calls to properly render section content.  It is scheduled as a
        background worker from on_mount().
        """
        if not self._sections:
            return

        import json as _json
        from skills.chat.tool_format import format_tool_call_display

        # Group sections by turn_id, preserving order of first appearance.
        turn_order: list[str] = []
        turns: dict[str, list[dict]] = {}
        for sec in self._sections:
            tid = sec["turn_id"]
            if tid not in turns:
                turn_order.append(tid)
                turns[tid] = []
            # Use a mutable copy so we can mark tool-calls as displayed.
            turns[tid].append(dict(sec))

        # Yield to the event loop so that the display tree finishes
        # mounting before we start adding sections.
        await asyncio.sleep(0)

        for tid in turn_order:
            sections = turns[tid]
            assistant_started = False
            tools_displayed = False
            for sec in sections:
                ct = sec["content_type"]
                content = sec["content"]

                if ct == "user":
                    self._chat_display.add_user_message(content)
                elif ct == "system":
                    self._chat_display.add_system_message(content)
                elif ct == "thinking":
                    if not assistant_started:
                        self._chat_display.begin_assistant_turn()
                        assistant_started = True
                        # Give the assistant branch time to mount.
                        await asyncio.sleep(0)
                    section_id = self._chat_display.add_section("thinking")
                    await asyncio.sleep(0)
                    await self._chat_display.update_section(section_id, content)
                elif ct == "response":
                    if not assistant_started:
                        self._chat_display.begin_assistant_turn()
                        assistant_started = True
                        await asyncio.sleep(0)
                    section_id = self._chat_display.add_section("response")
                    await asyncio.sleep(0)
                    await self._chat_display.update_section(section_id, content)
                elif ct == "tool_call":
                    if not assistant_started:
                        self._chat_display.begin_assistant_turn()
                        assistant_started = True
                        await asyncio.sleep(0)
                    # Display all tool_call entries for this turn as
                    # a single "tools" section (only once).
                    if not tools_displayed:
                        tool_calls_in_turn = [
                            s for s in sections
                            if s["content_type"] == "tool_call"
                        ]
                        tool_display = ""
                        for tc_sec in tool_calls_in_turn:
                            try:
                                tc_data = _json.loads(tc_sec["content"])
                                tool_display += format_tool_call_display(
                                    tc_data["name"], tc_data["arguments"]
                                )
                            except (_json.JSONDecodeError, KeyError):
                                tool_display += tc_sec["content"] + "\n"
                        section_id = self._chat_display.add_section("tools")
                        await asyncio.sleep(0)
                        await self._chat_display.update_section(
                            section_id, tool_display
                        )
                        tools_displayed = True

        self._chat_display.finalize_turn()

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
        from core.tools import get_tools

        provider = ctx.provider

        # Resolve the system prompt from the prompt registry.
        prompt_id = ctx.config.get("prompt.default_id", "default")
        if ctx.prompts is not None:
            try:
                system_prompt = ctx.prompts.render(prompt_id, ctx)
            except ValueError:
                # Prompt not found — fall back to a bare-bones default.
                system_prompt = "You are a helpful AI coding assistant."
        else:
            system_prompt = "You are a helpful AI coding assistant."

        # Determine the model — prompt template may specify an override.
        model = ""
        if ctx.prompts is not None:
            prompt_row = ctx.prompts.get_prompt(prompt_id)
            if prompt_row and prompt_row.get("model"):
                model = prompt_row["model"]
        if not model and ctx.config is not None:
            model = ctx.config.get("session.model", "")

        agent = Agent(
            provider=provider,
            template=system_prompt,
            model=model,
            ctx=ctx,
        )
        self._agent = agent
        self._tools = get_tools()

    # ------------------------------------------------------------------
    # Command palette selection
    # ------------------------------------------------------------------

    def on_command_palette_command_selected(
        self, event: CommandPalette.CommandSelected
    ) -> None:
        """Handle selection from the command palette — fill the input."""
        event.stop()
        self._chat_palette.hide()
        # Suppress the on_input_changed that setting value triggers,
        # otherwise the palette re-shows because the text starts with /.
        self._chat_input._suppress_palette_update = True
        try:
            inp = self._chat_input.query_one(Input)
            inp.value = f"/{event.command_name} "
            inp.cursor_end = True
            inp.focus()
        finally:
            self._chat_input._suppress_palette_update = False

    def on_file_palette_file_selected(
        self, event: FilePalette.FileSelected
    ) -> None:
        """Handle selection from the file palette — insert the file path."""
        event.stop()
        self._file_palette.hide()
        inp = self._chat_input.query_one(Input)
        text = inp.value
        at_idx = text.rfind("@")
        if at_idx != -1:
            prefix = text[:at_idx]
            after_at = text[at_idx + 1 :]
            token_end = len(after_at)
            for i, ch in enumerate(after_at):
                if ch == " ":
                    token_end = i
                    break
            new_text = prefix + f"@{event.filepath} " + text[at_idx + 1 + token_end :]
            self._chat_input._suppress_palette_update = True
            try:
                inp.value = new_text
                inp.cursor_end = True
                inp.focus()
            finally:
                self._chat_input._suppress_palette_update = False

    # ------------------------------------------------------------------
    # Message handling → streaming cycle
    # ------------------------------------------------------------------

    def on_chat_input_chat_submitted(self, event: ChatInput.ChatSubmitted) -> None:
        """Handle a user submission — detect slash commands or kick off streaming."""
        event.stop()
        text = event.text

        # Slash command dispatch
        if text.startswith("/"):
            self._chat_input.clear()
            self.run_worker(self._handle_command(text))
            return

        self._chat_input.clear()
        self._streaming_task = self.run_worker(self._handle_submit(text))

    def on_chat_input_chat_abort_requested(
        self, event: ChatInput.ChatAbortRequested
    ) -> None:
        """Handle abort request — cancel the streaming task."""
        event.stop()
        if self._streaming_task is not None and not self._streaming_task.is_finished:
            self._agent.abort()
            self._streaming_task.cancel()

    # ------------------------------------------------------------------
    # Streaming turn
    # ------------------------------------------------------------------

    async def _handle_submit(self, user_text: str) -> None:
        """Full streaming turn: display user msg, stream assistant, save."""
        turn_id = uuid.uuid4().hex

        # User message in display and database.
        self._chat_display.add_user_message(user_text)
        self._persist_section(turn_id, "user", user_text)

        # Assistant branch (no sections yet — added on demand).
        self._chat_display.begin_assistant_turn()

        # New rows were mounted synchronously; yield to the event loop
        # so the assistant branch finishes its mount lifecycle before we
        # add sections to it.
        self.refresh(layout=True)
        await asyncio.sleep(0)

        if self._agent is None:
            section = StreamSection(self._chat_display, "response")
            await section.replace("No agent configured.")
            self._chat_display.finalize_turn()
            self._chat_input.focus()
            return

        # Enter streaming mode.
        self._chat_input.set_streaming(True)

        watcher: StreamSection | None = None

        try:
            async for chunk in self._agent.stream_chat(
                self._history,
                user_text,
                tools=self._tools,
            ):
                # --- Thinking ---
                if chunk.thinking:
                    if watcher is None or watcher.section_type != "thinking":
                        # Close previous section and persist its text.
                        if watcher is not None:
                            self._persist_section(
                                turn_id, watcher.section_type, watcher.text
                            )
                        watcher = StreamSection(self._chat_display, "thinking")
                    await watcher.append(chunk.thinking)

                # --- Tool calls ---
                if chunk.tool_calls:
                    # Close previous section and persist its text.
                    if watcher is not None:
                        self._persist_section(
                            turn_id, watcher.section_type, watcher.text
                        )
                        watcher = None

                    # Tool calls always get a fresh section.
                    watcher = StreamSection(self._chat_display, "tools")
                    tool_display = ""
                    for tc in chunk.tool_calls:
                        # Display-friendly markdown
                        tool_display += format_tool_call_display(
                            tc.name, tc.arguments
                        )
                        # Persist each tool call as a separate row (structured JSON).
                        self._persist_section(
                            turn_id,
                            "tool_call",
                            format_tool_call_json(tc.name, tc.arguments),
                        )
                    await watcher.replace(tool_display)
                    # Tool section is a discrete display event — no additional
                    # persistence needed here.  Each tool call was already
                    # persisted as structured JSON above.
                    watcher = None

                # --- Response text ---
                if chunk.content:
                    if watcher is None or watcher.section_type != "response":
                        # Close previous section and persist its text.
                        if watcher is not None:
                            self._persist_section(
                                turn_id, watcher.section_type, watcher.text
                            )
                        watcher = StreamSection(self._chat_display, "response")
                    await watcher.append(chunk.content)

        except asyncio.CancelledError:
            # Aborted — persist whatever we have so far.
            if watcher is not None:
                replacement = await watcher.mark_aborted()
                self._persist_section(
                    turn_id, watcher.section_type, watcher.text
                )
                if replacement is not None:
                    watcher = replacement
                    self._persist_section(
                        turn_id, watcher.section_type, watcher.text
                    )
            else:
                watcher = StreamSection(self._chat_display, "response")
                await watcher.replace("*[aborted]*")
                self._persist_section(turn_id, "response", watcher.text)

        except Exception as exc:
            if watcher is None or watcher.section_type != "response":
                if watcher is not None:
                    self._persist_section(
                        turn_id, watcher.section_type, watcher.text
                    )
                watcher = StreamSection(self._chat_display, "response")
            await watcher.replace(f"Error: {exc}")
            self._persist_section(turn_id, watcher.section_type, watcher.text)

        else:
            # Normal completion — persist the final section.
            if watcher is not None:
                self._persist_section(
                    turn_id, watcher.section_type, watcher.text
                )

        # Rebuild in-memory history from the database so it's always
        # consistent with what was persisted.
        self._rebuild_history()

        # Exit streaming mode.
        self._chat_input.set_streaming(False)
        self._chat_display.finalize_turn()
        self._chat_input.focus()

    # ------------------------------------------------------------------
    # Slash command dispatch
    # ------------------------------------------------------------------

    async def _handle_command(self, text: str) -> None:
        """Parse a slash command from *text* and execute it.

        The format is ``/command_name [args]``.  If the command is not
        found, a system message is shown with the error.
        """
        # Strip the leading slash and split into name + args.
        without_slash = text[1:]
        parts = without_slash.split(None, 1)
        if not parts:
            # Bare / with no command name — ignore.
            self._chat_display.add_system_message(
                "Type / followed by a command name."
            )
            self._chat_input.focus()
            return
        command_name = parts[0].lower()
        command_args = parts[1] if len(parts) > 1 else ""

        # Show what the user typed in the display.
        self._chat_display.add_user_message(text)

        try:
            result = await execute_command(command_name, self.app, command_args)
            # Command succeeded — show the result as a system message.
            result_text = str(result) if result is not None else ""
            if result_text:
                self._chat_display.add_system_message(result_text)
        except KeyError:
            # Unknown command.
            available = ", ".join(f"/{n}" for n in list_commands())
            self._chat_display.add_system_message(
                f"Unknown command: /{command_name}"
                + (f"\nAvailable commands: {available}" if available else "")
            )
        except Exception as exc:
            # Command raised an error.
            self._chat_display.add_system_message(f"Error: {exc}")

        self._chat_input.focus()

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def _persist_section(
        self, turn_id: str, content_type: str, content: str
    ) -> None:
        """Write a single section row to the database and in-memory list."""
        # Always track in memory so history works without a database.
        self._sections.append({
            "turn_id": turn_id,
            "content_type": content_type,
            "content": content,
        })

        if self._db is None or self._chat_id is None:
            return
        try:
            self._db.save_section(
                self._chat_id, turn_id, content_type, content
            )
        except Exception:
            pass  # Best-effort — don't crash the stream for a DB error.

    def _rebuild_history(self) -> None:
        """Rebuild in-memory LLM history from persisted or in-memory sections.

        Prefers the database when available.  Falls back to the
        in-memory ``_sections`` list when there is no database.
        Called after every streaming turn so that ``self._history``
        always reflects what was persisted.
        """
        if self._db is not None and self._chat_id is not None:
            try:
                self._history = self._db.reconstruct_history(self._chat_id)
                return
            except Exception:
                pass

        # No database (or DB error) — reconstruct from in-memory sections.
        self._history = self._reconstruct_from_sections(self._sections)

    @staticmethod
    def _reconstruct_from_sections(
        sections: list[dict[str, str]],
    ) -> list[dict[str, Any]]:
        """Reconstruct LLM-consumable history from a flat section list.

        Mirrors :meth:`DatabaseManager.reconstruct_history` but works
        on in-memory dicts instead of DB rows.
        """
        import json as _json

        history: list[dict[str, Any]] = []
        turn_order: list[str] = []
        turns: dict[str, list[dict[str, str]]] = {}

        for sec in sections:
            tid = sec["turn_id"]
            if tid not in turns:
                turn_order.append(tid)
                turns[tid] = []
            turns[tid].append(sec)

        for tid in turn_order:
            for s in turns[tid]:
                ct = s["content_type"]

                if ct == "user":
                    history.append({"role": "user", "content": s["content"]})

                elif ct == "system":
                    history.append({"role": "system", "content": s["content"]})

                elif ct == "thinking":
                    asst = _ensure_assistant(history, tid)
                    asst["thinking"] = (asst.get("thinking") or "") + s["content"]

                elif ct == "tool_call":
                    asst = _ensure_assistant(history, tid)
                    tc_list = asst.setdefault("tool_calls", [])
                    try:
                        tc_list.append(_json.loads(s["content"]))
                    except (_json.JSONDecodeError, TypeError):
                        pass

                elif ct == "response":
                    asst = _ensure_assistant(history, tid)
                    asst["content"] = (asst.get("content") or "") + s["content"]

        return history

    # ------------------------------------------------------------------
    # New conversation
    # ------------------------------------------------------------------

    def new_conversation(self) -> None:
        """Start a fresh conversation: clear display, reset history, create
        a new database chat.
        """
        self._chat_display.clear()
        self._history.clear()
        self._sections.clear()
        if self._db is not None:
            self._chat_id = self._db.create_chat()
        self._chat_display.add_system_message("New conversation started.")
        self._chat_input.focus()
        # Sync cleared state back to ChatTabState so it stays consistent
        # if a workspace recomposition happens before the next flush.
        self.flush_state()


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _ensure_assistant(
    history: list[dict[str, Any]], turn_id: str
) -> dict[str, Any]:
    """Find or create the assistant message dict for *turn_id*.

    The assistant dict is always the last entry in *history* when
    it exists (because user always precedes assistant).
    """
    if history and history[-1].get("role") == "assistant" and history[-1].get("_turn_id") == turn_id:
        return history[-1]
    asst: dict[str, Any] = {"role": "assistant", "_turn_id": turn_id}
    history.append(asst)
    return asst