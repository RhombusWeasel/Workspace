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

from core.commands import execute_command, list_commands
from skills.chat.chat_input import ChatInput, ChatTextArea
from skills.chat.chat_display import ChatDisplay
from skills.chat.command_palette import CommandPalette
from skills.chat.file_palette import FilePalette
from skills.chat.stream_section import StreamSection
from skills.chat.tool_format import format_tool_call_json


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

    can_focus = True
    """Mark as focusable so that :meth:`WorkspaceTabs._focus_active_content`
    calls our :meth:`focus` method (which delegates to the chat input)
    instead of walking descendants and landing on an unrelated focusable
    widget (e.g. a Tree or Markdown inside ChatDisplay)."""

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
        # Read config-driven defaults for thinking/tool-call expand state
        # and system prompt display.
        open_thinking = False
        open_tools = False
        show_system_prompt = False
        if hasattr(self.app, "context") and self.app.context is not None:
            cfg = self.app.context.config
            if cfg is not None:
                open_thinking = cfg.get("session.open_thinking", False)
                open_tools = cfg.get("session.open_tools", False)
                show_system_prompt = cfg.get("session.show_system_prompt", False)
        with Vertical():
            self._chat_display = ChatDisplay(
                open_thinking=open_thinking,
                open_tools=open_tools,
                show_system_prompt=show_system_prompt,
            )
            self._chat_input = ChatInput()
            yield self._chat_display
            yield self._chat_input

    def on_mount(self) -> None:
        self.focus()
        # Set working directory on ChatInput (propagates to ChatTextArea
        # for inline suggestions and to FilePalette for the dropdown picker)
        if hasattr(self.app, "context") and self.app.context is not None:
            self._chat_input.set_working_directory(
                self.app.context.working_directory
            )

        # If state was restored, rebuild the visual display asynchronously.
        # The rebuild needs to await Markdown.update() calls, so it runs
        # as a background worker.
        if self._state is not None and self._sections:
            self.run_worker(self._rebuild_display_from_sections())
        elif self._state is None or not self._sections:
            # Fresh chat tab — show system prompt if configured.
            self._maybe_show_system_prompt()

    def focus(self) -> None:
        """Focus the chat input.

        Overrides :meth:`Widget.focus` so that :meth:`WorkspaceTabs._focus_active_content`
        lands on the input field instead of walking descendants and picking
        the first focusable widget (e.g. a Tree inside ChatDisplay).
        """
        self._chat_input.focus()

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

        # Group sections by turn_id, preserving order of first appearance.
        turn_order: list[str] = []
        turns: dict[str, list[dict]] = {}
        for sec in self._sections:
            tid = sec["turn_id"]
            if tid not in turns:
                turn_order.append(tid)
                turns[tid] = []
            turns[tid].append(sec)

        # Yield to the event loop so that the display tree finishes
        # mounting before we start adding sections.
        await asyncio.sleep(0)

        for tid in turn_order:
            sections = turns[tid]
            assistant_started = False
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
                    # Add tool calls one at a time, in their original
                    # order, so that branches appear in the same
                    # sequence as they were created during streaming.
                    try:
                        tc_data = _json.loads(content)
                        self._chat_display.add_tool_call(
                            tc_data["name"],
                            tc_data["arguments"],
                        )
                    except (_json.JSONDecodeError, KeyError):
                        self._chat_display.add_tool_call(
                            "unknown",
                            {"raw": content},
                        )

            # Finalise each assistant turn as we go so that sections
            # are swapped from Static to Markdown and empty sections are
            # removed.  This is important for multi-turn conversations
            # where finalize_turn() only processes the active turn.
            if assistant_started:
                await self._chat_display.finalize_turn()

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
        using the provider and agent registries.

        The database chat row is **not** created here — it is created
        lazily on first persist so that opening a tab without sending
        a message does not leave an empty conversation in the DB.
        """
        if ctx.database is not None:
            self._db = ctx.database
        if self._agent is None:
            self._wire_agent(ctx)

    def wire_agent_from_id(self, ctx: Any, agent_id: str) -> None:
        """Wire a specific agent definition by ID.

        Like :meth:`wire_from_context`, but forces the use of the named
        agent instead of the session default.

        The database chat row is **not** created here — it is created
        lazily on first persist so that opening a tab without sending
        a message does not leave an empty conversation in the DB.
        """
        if ctx.database is not None:
            self._db = ctx.database
        self._wire_agent(ctx, agent_id=agent_id)

    def _wire_agent(self, ctx: Any, agent_id: str | None = None) -> None:
        from core.agent import Agent
        from core.tools import get_tools

        # Resolve the agent definition from the agent registry.
        if agent_id is None:
            agent_id = ctx.config.get("agent.default_id", "default")
        agent_def = None
        if ctx.agents is not None:
            agent_def = ctx.agents.get_agent(agent_id)

        # Resolve the provider — agent may specify a named provider instance.
        if ctx.providers is not None:
            if agent_def and agent_def.get("provider"):
                try:
                    provider = ctx.providers.get(agent_def["provider"])
                except (ValueError, KeyError):
                    provider = ctx.providers.get_default()
            else:
                provider = ctx.providers.get_default()
        else:
            provider = ctx.provider  # backward compat property

        # Resolve the system prompt from the agent registry.
        if ctx.agents is not None and agent_def is not None:
            try:
                system_prompt = ctx.agents.render(agent_id, ctx)
            except ValueError:
                system_prompt = "You are a helpful AI coding assistant."
        else:
            system_prompt = "You are a helpful AI coding assistant."

        # Determine the model — agent definition may specify an override.
        model = ""
        if agent_def and ctx.agents is not None:
            model = ctx.agents.resolve_model(agent_def, ctx)
        elif ctx.config is not None:
            provider_name = ctx.config.get("session.provider", "ollama")
            model = ctx.config.get(f"providers.{provider_name}.model", "")

        # Resolve tools — agent may specify a subset.
        tool_filter = None
        if agent_def and ctx.agents is not None:
            tool_filter = ctx.agents.resolve_tools(agent_def)

        if tool_filter is not None:
            tools = get_tools(filtered=tool_filter)
        else:
            tools = get_tools()

        # Resolve max_tool_iterations — agent may override the session default.
        max_tool_iterations = ctx.config.get("session.max_tool_calls", 10)
        if agent_def and ctx.agents is not None:
            mt = ctx.agents.resolve_max_tool_iterations(agent_def)
            if mt is not None:
                max_tool_iterations = mt

        # Resolve per-agent skills XML if agent specifies a skill subset.
        skills_xml = ""
        if agent_def and ctx.agents is not None:
            skill_names = ctx.agents.resolve_skills(agent_def)
            if skill_names is not None and ctx.skills is not None:
                # Agent wants specific skills — build XML for just those.
                skills_xml = ctx.skills.render_selected(skill_names)

        agent = Agent(
            provider=provider,
            template=system_prompt,
            model=model,
            skills_xml=skills_xml,
            max_tool_iterations=max_tool_iterations,
            ctx=ctx,
        )
        self._agent = agent
        self._tools = tools

    # ------------------------------------------------------------------
    # Command palette selection
    # ------------------------------------------------------------------

    def on_command_palette_command_selected(
        self, event: CommandPalette.CommandSelected
    ) -> None:
        """Handle selection from the command palette — fill the input."""
        event.stop()
        self._chat_input.palette.hide()
        # Suppress the on_text_area_changed that setting text triggers,
        # otherwise the palette re-shows because the text starts with /.
        self._chat_input._suppress_palette_update = True
        try:
            ta = self._chat_input.query_one(ChatTextArea)
            ta.text = f"/{event.command_name} "
            ta.cursor_location = (0, len(ta.text))
            ta.focus()
        finally:
            self._chat_input._suppress_palette_update = False

    def on_file_palette_file_selected(
        self, event: FilePalette.FileSelected
    ) -> None:
        """Handle selection from the file palette — insert the file path."""
        event.stop()
        self._chat_input.file_palette.hide()
        ta = self._chat_input.query_one(ChatTextArea)
        text = ta.text
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
                ta.text = new_text
                ta.cursor_location = (0, len(ta.text))
                ta.focus()
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
            await self._chat_display.finalize_turn()
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
                            await watcher.flush()
                            self._persist_section(
                                turn_id, watcher.section_type, watcher.text
                            )
                        watcher = StreamSection(self._chat_display, "thinking")
                    await watcher.append(chunk.thinking)

                # --- Tool calls ---
                if chunk.tool_calls:
                    # Close previous section and persist its text.
                    if watcher is not None:
                        await watcher.flush()
                        self._persist_section(
                            turn_id, watcher.section_type, watcher.text
                        )
                        watcher = None

                    # Create individual tool call branches directly under the assistant turn.
                    for tc in chunk.tool_calls:
                        self._chat_display.add_tool_call(
                            tc.name, tc.arguments,
                        )
                        # Persist each tool call as a separate row (structured JSON).
                        self._persist_section(
                            turn_id,
                            "tool_call",
                            format_tool_call_json(tc.name, tc.arguments),
                        )
                    # No StreamSection for tool calls — they are
                    # discrete display events, not streamed content.
                    watcher = None

                # --- Response text ---
                if chunk.content:
                    if watcher is None or watcher.section_type != "response":
                        # Close previous section and persist its text.
                        if watcher is not None:
                            await watcher.flush()
                            self._persist_section(
                                turn_id, watcher.section_type, watcher.text
                            )
                        watcher = StreamSection(self._chat_display, "response")
                    await watcher.append(chunk.content)

                # --- Token usage (on done chunk) ---
                if chunk.done and chunk.usage:
                    model_name = getattr(self._agent, "_model", "")
                    self._chat_input.update_context_progress(
                        model_name,
                        chunk.usage.total_tokens,
                        chunk.usage.context_length,
                    )

        except asyncio.CancelledError:
            # Aborted — persist whatever we have so far.
            if watcher is not None:
                replacement = await watcher.mark_aborted()
                self._persist_section(
                    turn_id, watcher.section_type, watcher.text
                )
                if replacement is not None:
                    await replacement.flush()
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
                    await watcher.flush()
                    self._persist_section(
                        turn_id, watcher.section_type, watcher.text
                    )
                watcher = StreamSection(self._chat_display, "response")
            await watcher.replace(f"Error: {exc}")
            self._persist_section(turn_id, watcher.section_type, watcher.text)

        else:
            # Normal completion — persist the final section.
            if watcher is not None:
                await watcher.flush()
                self._persist_section(
                    turn_id, watcher.section_type, watcher.text
                )

        # Rebuild in-memory history from the database so it's always
        # consistent with what was persisted.
        self._rebuild_history()

        # Exit streaming mode.
        self._chat_input.set_streaming(False)
        await self._chat_display.finalize_turn()
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
        """Write a single section row to the database and in-memory list.

        The database chat row is created lazily on the first persist
        call, so that tabs which are opened but never used do not leave
        empty conversations in the database.
        """
        # Always track in memory so history works without a database.
        self._sections.append({
            "turn_id": turn_id,
            "content_type": content_type,
            "content": content,
        })

        if self._db is None:
            return

        # Lazy chat creation — only write to the DB when there's
        # actual content to persist.
        if self._chat_id is None:
            self._chat_id = self._db.create_chat()

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
        """Start a fresh conversation: clear display, reset history.

        The database chat row is **not** created eagerly — it will be
        created lazily on the first ``_persist_section()`` call, so that
        starting a new conversation without sending a message does not
        leave an empty row in the database.

        If the ``session.show_system_prompt`` config is True and an agent
        is wired, the system prompt is displayed as a collapsible branch.
        """
        self._chat_display.clear()
        self._history.clear()
        self._sections.clear()
        self._chat_id = None
        self._chat_display.add_system_message("New conversation started.")
        self._maybe_show_system_prompt()
        self._chat_input.focus()
        # Sync cleared state back to ChatTabState so it stays consistent
        # if a workspace recomposition happens before the next flush.
        self.flush_state()

    # ------------------------------------------------------------------
    # System prompt display
    # ------------------------------------------------------------------

    def _maybe_show_system_prompt(self) -> None:
        """Display the LLM system prompt if the config option is enabled.

        Checks the ``session.show_system_prompt`` config.  When True and
        an agent is wired, the rendered system prompt is added as a
        collapsible branch in the chat display.
        """
        if not self._chat_display._show_system_prompt:
            return
        if self._agent is None:
            return
        prompt = self._agent.system_prompt
        if prompt:
            self._chat_display.add_system_prompt(prompt)


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