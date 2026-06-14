"""Chat manager -- orchestrates streaming chat between input, display, agent, and database.

Composes a :class:`~ui.chat.chat_input.ChatInput` and
:class:`~ui.chat.chat_display.ChatDisplay`, catching ``ChatSubmitted``
messages and driving the streaming cycle through an LLM agent.

Supports aborting an in-progress stream via the abort button or
``Escape`` key.  When aborted, the partial response is preserved
in the display and database.
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
from skills.chat.tool_format import format_tool_call_json
# TODO: Re-implement revert buttons for Collapsible architecture


class ChatManager(Widget):
    """Orchestrates a streaming conversation.

    Composes a ``ChatInput`` and ``ChatDisplay``.  Listens for
    ``ChatInput.ChatSubmitted``, starts the LLM stream through
    :class:`~core.stream_manager.StreamManager`, polls the database for
    updates, and renders them in the display.

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
        """In-memory mirror of flat sections -- used to build history when
        there is no database, and kept in sync for consistency."""
        self._db: Any = None
        self._chat_id: str | None = None
        self._stream_id: str | None = None
        """UUID of the active stream in StreamManager.

        When streaming is active, this references a stream in the
        StreamManager.  On workspace recomposition, the stream continues
        running in StreamManager and the fresh ChatManager re-subscribes
        using this ID.  None when not streaming.
        """
        self._streaming_task: asyncio.Task | None = None
        """Background worker that polls the DB while a stream is active."""
        self._state: Any = None
        self._turn_checkpoint_tags: dict[str, str] = {}
        """Map of turn_id to checkpoint tag for revert support.

        When a user message is submitted, a git checkpoint is created
        and the tag is stored here.  When the user clicks the revert
        button on a user message branch, the tag is used to restore
        the working tree to that point."""
        self._streaming: bool = False
        """Whether the chat is currently streaming a response.

        Used to prevent revert actions during active streaming."""
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

        # If state was restored, rebuild the visual display and resume
        # polling any active stream.
        import logging
        _logger = logging.getLogger(__name__)
        if self._state is not None and self._sections:
            _logger.info(
                "on_mount: scheduling rebuild from %d sections (chat_id=%s)",
                len(self._sections), self._chat_id,
            )
            self.run_worker(self._rebuild_and_maybe_resume())
        elif self._state is not None and getattr(self._state, "_stream_id", None):
            _logger.info(
                "on_mount: resuming stream %s", self._state._stream_id,
            )
            self.run_worker(self._resume_stream(self._state._stream_id))
        else:
            _logger.info(
                "on_mount: new/empty chat (state=%s, sections=%d)",
                self._state is not None, len(self._sections),
            )
            self._maybe_show_system_prompt()

    def _resume_stream(self, stream_id: str) -> None:
        """Resume polling an active stream after workspace recomposition.

        The stream task continues writing to the DB.  The new widget just
        needs to start polling the same chat_id.
        """
        ctx = self._get_context()
        if ctx is None or ctx.stream_manager is None:
            return
        if not ctx.stream_manager.has_stream(stream_id):
            self._streaming = False
            self._stream_id = None
            if self._state is not None:
                self._state._stream_id = None
            self._chat_input.set_streaming(False)
            return

        self._chat_input.set_streaming(True)
        self._streaming = True
        self._streaming_task = self.run_worker(self._poll_stream(stream_id))

    def on_unmount(self) -> None:
        """Detach display when the widget is removed from the DOM.

        Called when the workspace is recomposed (split/close) or when
        the chat tab is closed.  Marks the display as detached so
        in-flight streaming updates bail out, but does NOT cancel the
        stream -- the stream continues running in StreamManager and
        the new ChatManager will re-subscribe after recomposition.

        The stream is only cancelled when the tab is permanently
        closed (via ChatTabState.dispose()).
        """
        self._detach_display()

    def on_remove(self) -> None:
        """Detach display when the widget is removed (belt-and-suspenders).

        Same as on_unmount -- detach display but don't cancel the stream.
        """
        self._detach_display()

    def _detach_display(self) -> None:
        """Mark the display as detached and stop the local polling worker.

        The stream itself continues in StreamManager.  Only the local
        polling worker and the display reference are cleaned up.
        """
        if hasattr(self, '_chat_display') and self._chat_display is not None:
            self._chat_display._detached = True
        if self._streaming_task is not None and not self._streaming_task.is_finished:
            self._streaming_task.cancel()

    def _cancel_streaming(self) -> None:
        """Cancel the stream entirely -- only used for user-initiated abort.

        Unlike _detach_display(), this cancels the stream in StreamManager
        so the LLM agent is aborted and the background task is cleaned up.
        Used when the user explicitly aborts a response.
        """
        if self._stream_id is not None:
            ctx = self._get_context()
            if ctx and ctx.stream_manager:
                ctx.stream_manager.cancel(self._stream_id)
            self._stream_id = None
        if self._streaming_task is not None and not self._streaming_task.is_finished:
            self._streaming_task.cancel()
        self._streaming = False
        if hasattr(self, '_chat_display') and self._chat_display is not None:
            self._chat_display._detached = True

    def focus(self) -> None:
        """Focus the chat input.

        Overrides :meth:`Widget.focus` so that :meth:`WorkspaceTabs._focus_active_content`
        lands on the input field instead of walking descendants and picking
        the first focusable widget (e.g. a Tree inside ChatDisplay).
        """
        self._chat_input.focus()

    def _get_context(self) -> Any:
        """Return the AppContext, or None if not available."""
        if hasattr(self.app, 'context') and self.app.context is not None:
            return self.app.context
        return None

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
        self._turn_checkpoint_tags = getattr(state, '_turn_checkpoint_tags', {})
        # Stream ID is adopted here so on_mount can re-subscribe.
        self._stream_id = getattr(state, '_stream_id', None)
        # If we have a stream ID, we're mid-stream -- set the flag.
        if self._stream_id is not None:
            self._streaming = True

    def flush_state(self) -> None:
        """Sync current widget state back to the ChatTabState.

        Called by :meth:`WorkspaceTabs.save_state` before a DOM
        recomposition.  Copies the widget's internal state into the
        persistent state object so the fresh widget can restore it
        after the rebuild.

        The stream ID is persisted so the new ChatManager can
        re-subscribe to the active stream in StreamManager.
        """
        if self._state is not None:
            self._state._history = self._history
            self._state._sections = self._sections
            self._state._agent = self._agent
            self._state._tools = self._tools
            self._state._db = self._db
            self._state._chat_id = self._chat_id
            self._state._turn_checkpoint_tags = self._turn_checkpoint_tags
            # Persist the stream ID so the new widget can re-subscribe.
            self._state._stream_id = self._stream_id

    async def _resume_stream(self, stream_id: str) -> None:
        """Resume polling an active stream after workspace recomposition."""
        ctx = self._get_context()
        if ctx is None or ctx.stream_manager is None:
            return
        if not ctx.stream_manager.has_stream(stream_id):
            self._streaming = False
            self._stream_id = None
            if self._state is not None:
                self._state._stream_id = None
            self._chat_input.set_streaming(False)
            return

        self._chat_input.set_streaming(True)
        self._streaming = True
        self._streaming_task = self.run_worker(self._poll_stream(stream_id))

    async def _rebuild_and_maybe_resume(self) -> None:
        """Rebuild the display from persisted sections and resume polling.

        Uses ``refresh_from_sections`` — the same method that drives the
        display during streaming — so history loading follows the exact
        same code path that is already proven to work.
        """
        import logging
        _logger = logging.getLogger(__name__)
        _logger.info(
            "_rebuild_and_maybe_resume: starting (chat_id=%s)",
            self._chat_id,
        )

        # Prefer DB sections (fresh, includes section_id) over in-memory
        # sections (may lack section_id from older conversations).
        sections = None
        if self._db is not None and self._chat_id is not None:
            try:
                sections = self._db.load_sections(self._chat_id)
            except Exception:
                _logger.warning("Failed to load sections from DB, falling back to in-memory")

        if sections is None:
            # Fallback to in-memory sections (from ChatTabState).
            sections = self._sections

        if not sections:
            _logger.info("_rebuild_and_maybe_resume: no sections to rebuild")
            return

        try:
            await self._chat_display.refresh_from_sections(sections, finalize=True)
            _logger.info(
                "_rebuild_and_maybe_resume: completed (%d sections)",
                len(sections),
            )
        except Exception:
            _logger.exception("Error rebuilding display from sections")
            # Show user-visible feedback so empty display isn't silently confusing.
            if self.is_mounted and not self._chat_display._detached:
                try:
                    self._chat_display.add_system_message(
                        "⚠ Failed to load conversation history. "
                        "Check the logs for details."
                    )
                except Exception:
                    pass  # Best-effort — don't crash for a display error.

        # Re-attach revert buttons to completed user message nodes that
        # have checkpoint tags from a previous session.
        self._attach_revert_buttons()

        if self._state is not None and getattr(self._state, '_stream_id', None):
            await self._resume_stream(self._state._stream_id)

    async def _resume_stream(self, stream_id: str) -> None:
        """Re-subscribe to an active stream after workspace recomposition.

        Called from ``on_mount()`` when the ChatTabState carries a
        ``_stream_id``, indicating that streaming was in progress when
        the workspace was recomposed.

        The display has already been rebuilt from persisted sections by
        ``_rebuild_and_maybe_resume()``.  This method re-subscribes
        to the StreamManager stream and processes only NEW chunks that
        arrive after the rebuild.

        All previously-persisted content is already on the display, so
        we skip the buffered chunks (they correspond to already-
        persisted sections) and only process chunks arriving after
        subscription.
        """
        ctx = self._get_context()
        if ctx is None or ctx.stream_manager is None:
            return

        sm = ctx.stream_manager
        if not sm.has_stream(stream_id):
            # Stream already finished or was cancelled during recomposition.
            self._streaming = False
            self._stream_id = None
            if self._state is not None:
                self._state._stream_id = None
            self._chat_input.set_streaming(False)
            return

        # Re-enter streaming mode on the display.
        self._chat_input.set_streaming(True)
        self._streaming = True

        # Process chunks from the StreamManager -- resume mode means
        # we skip all buffered chunks (already displayed via rebuild)
        # and only process new chunks arriving after subscription.
        self._streaming_task = self.run_worker(
            self._process_stream_chunks(stream_id, resume=True)
        )

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

        The database chat row is **not** created here -- it is created
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

        The database chat row is **not** created here -- it is created
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

        # Resolve the provider -- agent may specify a named provider instance.
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

        # Determine the model -- agent definition may specify an override.
        model = ""
        if agent_def and ctx.agents is not None:
            model = ctx.agents.resolve_model(agent_def, ctx)
        elif ctx.config is not None:
            provider_name = ctx.config.get("session.provider", "ollama")
            model = ctx.config.get(f"providers.{provider_name}.model", "")

        # Resolve tools -- agent may specify a subset.
        tool_filter = None
        if agent_def and ctx.agents is not None:
            tool_filter = ctx.agents.resolve_tools(agent_def)

        if tool_filter is not None:
            tools = get_tools(filtered=tool_filter)
        else:
            tools = get_tools()

        # Resolve max_tool_iterations -- agent may override the session default.
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
                # Agent wants specific skills -- build XML for just those.
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
        """Handle selection from the command palette -- fill the input."""
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
        """Handle selection from the file palette -- insert the file path."""
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
        """Handle a user submission -- detect slash commands or kick off streaming."""
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
        """Handle abort request -- cancel the stream via StreamManager."""
        event.stop()
        self._cancel_streaming()

    # ------------------------------------------------------------------
    # Streaming turn
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Streaming turn
    # ------------------------------------------------------------------

    async def _handle_submit(self, user_text: str) -> None:
        """Full streaming turn: display user msg, start LLM stream, poll DB."""
        turn_id = uuid.uuid4().hex

        # Create a git checkpoint before processing the user message.
        checkpoint_tag = self._create_turn_checkpoint(turn_id)

        # User message in display and database.
        self._chat_display.add_user_message(user_text)
        self._persist_section(turn_id, "user", user_text)

        # Assistant branch -- StreamManager will write sections here.
        self._chat_display.begin_assistant_turn(turn_id=turn_id)
        self.refresh(layout=True)
        await asyncio.sleep(0)

        if self._agent is None:
            error_section_id = self._chat_display.add_section("response")
            await self._chat_display.update_section(error_section_id, "No agent configured.")
            await self._chat_display.finalize_turn()
            self._chat_input.focus()
            return

        # Enter streaming mode.
        self._chat_input.set_streaming(True)
        self._streaming = True

        # Ensure a chat row exists so StreamManager has a chat_id to write to.
        if self._db is not None and self._chat_id is None:
            self._chat_id = self._db.create_chat()

        ctx = self._get_context()
        stream_manager = ctx.stream_manager if ctx and ctx.stream_manager else None

        if stream_manager is not None:
            self._stream_id = stream_manager.start(
                self._agent,
                self._history,
                user_text,
                tools=self._tools,
                db=self._db,
                chat_id=self._chat_id,
                turn_id=turn_id,
            )
            await self._poll_stream(self._stream_id)
        else:
            # Fallback when no StreamManager is available.
            await self._process_stream_direct(turn_id, user_text)

    async def _poll_stream(self, stream_id: str) -> None:
        """Poll the DB while a stream is running and refresh the display.

        The stream task writes chunks directly to the database.  This
        loop simply loads the latest sections and asks ChatDisplay to
        render them.  When the stream finishes, the final refresh finalises
        the assistant turn.
        """
        ctx = self._get_context()
        if ctx is None or ctx.stream_manager is None:
            return

        sm = ctx.stream_manager
        poll_interval = 0.25

        try:
            while sm.has_stream(stream_id):
                if not self.is_mounted or self._chat_display._detached:
                    break

                if self._db is not None and self._chat_id is not None:
                    try:
                        sections = self._db.load_sections(self._chat_id)
                        await self._chat_display.refresh_from_sections(sections)
                    except Exception:
                        pass

                await asyncio.sleep(poll_interval)

        except asyncio.CancelledError:
            pass

        # Final refresh after stream completes or is cancelled.
        if self.is_mounted and not self._chat_display._detached:
            if self._db is not None and self._chat_id is not None:
                try:
                    sections = self._db.load_sections(self._chat_id)
                    await self._chat_display.refresh_from_sections(
                        sections, finalize=True
                    )
                    # Refresh in-memory sections and history from DB.
                    self._sections = [
                        {
                            "turn_id": s["turn_id"],
                            "content_type": s["content_type"],
                            "content": s["content"],
                        }
                        for s in sections
                    ]
                    self._rebuild_history()
                except Exception:
                    pass

        # Update context usage bar with token counts from the completed stream.
        usage_chunk = sm.get_usage(stream_id)
        if usage_chunk is not None and usage_chunk.usage is not None:
            model_name = getattr(self._agent, "_model", "")
            self._chat_input.update_context_progress(
                model_name,
                usage_chunk.usage.total_tokens,
                usage_chunk.usage.context_length,
            )

        # Exit streaming mode.
        self._streaming = False
        self._stream_id = None
        if self._state is not None:
            self._state._stream_id = None
        if self.is_mounted and not self._chat_display._detached:
            self._chat_input.set_streaming(False)
            self._chat_input.focus()
            self._attach_revert_buttons()

    async def _process_stream_direct(self, turn_id: str, user_text: str) -> None:
        """Fallback when StreamManager is unavailable."""
        # StreamManager is created by bootstrap and should always be present.
        error_id = self._chat_display.add_section("response")
        await self._chat_display.update_section(error_id, "StreamManager not available.")
        await self._chat_display.finalize_turn()
        self._chat_input.set_streaming(False)
        self._streaming = False
        self._chat_input.focus()

    async def _handle_command(self, text: str) -> None:
        """Parse a slash command from *text* and execute it.

        The format is ``/command_name [args]``.  If the command is not
        found, a system message is shown with the error.
        """
        # Strip the leading slash and split into name + args.
        without_slash = text[1:]
        parts = without_slash.split(None, 1)
        if not parts:
            # Bare / with no command name -- ignore.
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
            # Command succeeded -- show the result as a system message.
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

        # Lazy chat creation -- only write to the DB when there's
        # actual content to persist.
        if self._chat_id is None:
            self._chat_id = self._db.create_chat()

        try:
            self._db.save_section(
                self._chat_id, turn_id, content_type, content
            )
        except Exception:
            pass  # Best-effort -- don't crash the stream for a DB error.

    def _update_tool_result(
        self,
        turn_id: str,
        name: str,
        arguments: dict[str, Any],
        result: str,
    ) -> None:
        """Update the persisted tool-call JSON to include the result.

        Finds the in-memory section for this tool call and replaces its
        content with an updated JSON that includes the ``result`` key.
        Also updates the database row.
        """
        import json as _json
        updated_json = format_tool_call_json(name, arguments, result=result)

        # Update the in-memory section list -- find the matching tool_call
        # row by turn_id and tool name.
        for sec in self._sections:
            if (
                sec["turn_id"] == turn_id
                and sec["content_type"] == "tool_call"
            ):
                try:
                    tc_data = _json.loads(sec["content"])
                    if tc_data.get("name") == name:
                        sec["content"] = updated_json
                        break
                except (_json.JSONDecodeError, KeyError):
                    continue

        # Update the database row if available.
        if self._db is not None and self._chat_id is not None:
            try:
                self._db.update_tool_result(
                    self._chat_id, turn_id, name, updated_json
                )
            except Exception:
                pass  # Best-effort -- don't crash the stream for a DB error.

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

        # No database (or DB error) -- reconstruct from in-memory sections.
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
                        tc_data = _json.loads(s["content"])
                        tc_list.append(tc_data)
                        # If the tool call JSON includes a result, emit a
                        # tool-role message so the LLM sees the output.
                        if "result" in tc_data and tc_data["result"] is not None:
                            history.append({
                                "role": "tool",
                                "content": tc_data["result"],
                                "name": tc_data.get("name", ""),
                            })
                    except (_json.JSONDecodeError, TypeError):
                        pass

                elif ct == "response":
                    asst = _ensure_assistant(history, tid)
                    asst["content"] = (asst.get("content") or "") + s["content"]

        return history

    # ------------------------------------------------------------------
    # Revert checkpoint support
    # ------------------------------------------------------------------

    def _create_turn_checkpoint(self, turn_id: str) -> str | None:
        """Create a git checkpoint before processing a user message.

        Imports and calls the git checkpoint script's create_checkpoint
        function directly.  Returns the tag name on success, or None on
        failure (e.g. no git repo, git not available).

        The tag is stored in ``_turn_checkpoint_tags`` so it can be
        looked up later when the user clicks a revert button.
        """
        try:
            from skills.git.scripts.checkpoint import create_checkpoint
            result = create_checkpoint(f"turn-{turn_id[:8]}")
            # create_checkpoint returns a multiline string;
            # the first line contains the tag name.
            if result and not result.startswith(("Error", "Not a git")):
                # Parse the tag from the first line:
                # "Checkpoint created: workspace-checkpoint/turn-xxxx"
                first_line = result.strip().split("\n")[0]
                if "Checkpoint created:" in first_line:
                    tag = first_line.split("Checkpoint created:")[1].strip()
                    if tag:
                        self._turn_checkpoint_tags[turn_id] = tag
                        return tag
        except Exception:
            pass  # Best-effort -- no checkpoint if git is unavailable.
        return None

    def _attach_revert_buttons(self) -> None:
        """Attach revert buttons to completed user message widgets.

        TODO: Re-implement for Collapsible-based architecture.
        The old Tree-based RowButton approach needs to be adapted
        to work with UserMessage Collapsible widgets.
        """
        pass  # TODO: Re-implement revert UI for Collapsible architecture

    async def _handle_revert(self, msg_id: str, checkpoint_tag: str) -> None:
        """Confirm and execute a revert to the given checkpoint.

        Shows a confirmation dialog, then restores the git working tree
        to the checkpoint, trims the conversation display and database.

        TODO: Re-implement trim_from_node for Collapsible architecture.
        """
        # Show confirmation dialog.
        from ui.widgets.confirm_modal import ConfirmModal
        confirmed = await self.app.push_screen_wait(
            ConfirmModal(
                f"Revert to checkpoint '{checkpoint_tag}'?\n"
                "This will reset the working tree and remove conversation "
                "history from this point onward."
            )
        )
        if not confirmed:
            return

        # Restore the git checkpoint.
        try:
            from skills.git.scripts.checkpoint import restore_checkpoint
            short_name = checkpoint_tag
            if short_name.startswith("workspace-checkpoint/"):
                short_name = short_name[len("workspace-checkpoint/"):]
            result = restore_checkpoint(short_name)
            if result:
                msg = result.strip()
                if msg.startswith(("Error", "Warning", "No checkpoint")):
                    self._chat_display.add_system_message(
                        f"Could not restore checkpoint: {msg}"
                    )
                    return
        except Exception as exc:
            self._chat_display.add_system_message(
                f"Error restoring checkpoint: {exc}"
            )
            return

        # TODO: Trim the conversation display from the reverted message onward.
        # This needs to be re-implemented for the Collapsible architecture
        # (remove UserMessage + all following widgets from the VerticalScroll).

        # Trim in-memory sections and history.
        turn_id_to_trim = None
        for tid, tag in self._turn_checkpoint_tags.items():
            if tag == checkpoint_tag:
                turn_id_to_trim = tid
                break

        if turn_id_to_trim is not None:
            trim_idx = None
            for i, sec in enumerate(self._sections):
                if sec["turn_id"] == turn_id_to_trim:
                    trim_idx = i
                    break
            if trim_idx is not None:
                self._sections = self._sections[:trim_idx]

            if self._db is not None and self._chat_id is not None:
                try:
                    self._db.delete_sections_from_turn(
                        self._chat_id, turn_id_to_trim
                    )
                except Exception:
                    pass

        self._rebuild_history()

        self._chat_display.add_system_message(
            f"Reverted to checkpoint: {checkpoint_tag}"
        )

        self._chat_input.focus()

    # ------------------------------------------------------------------
    # New conversation
    # ------------------------------------------------------------------

    def new_conversation(self) -> None:
        """Start a fresh conversation: clear display, reset history.

        The database chat row is **not** created eagerly -- it will be
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
        self._turn_checkpoint_tags.clear()
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