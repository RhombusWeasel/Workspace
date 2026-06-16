"""Chat manager -- orchestrates streaming chat between input, display, agent, and database.

Composes a :class:`~ui.chat.chat_input.ChatInput` and
:class:`~ui.chat.chat_display.ChatDisplay`, catching ``ChatSubmitted``
messages and driving the streaming cycle through an LLM agent.

Supports aborting an in-progress stream via the abort button or
``Escape`` key.  When aborted, the partial response is preserved
in the display and database.

The database is always the source of truth.  All display updates go
through ``refresh_from_sections()`` which loads from the DB.  The
``_sync_conversation()`` method is the single entry point for both
initial loads and streaming polls.
"""

from __future__ import annotations

import asyncio
import logging
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
        if hasattr(self.app, "context") and self.app.context is not None:
            self._chat_input.set_working_directory(
                self.app.context.working_directory
            )

        if self._state is not None and self._chat_id is not None:
            # Rebuild the display from the database and resume any
            # active stream.  Use call_after_refresh so the rebuild
            # runs after the widget is fully laid out and the screen
            # has been refreshed.  This avoids the worker being
            # cancelled if the widget is briefly unmounted during
            # tab creation (Textual cancels all workers on unmount).
            logging.getLogger(__name__).warning(
                "on_mount: state=%s chat_id=%s",
                type(self._state).__name__, self._chat_id[:8] if self._chat_id else None,
            )
            self.call_after_refresh(self._start_rebuild)
        else:
            self._maybe_show_system_prompt()

    def _start_rebuild(self) -> None:
        """Launch _rebuild_and_resume as a worker (called via call_after_refresh)."""
        if self._chat_id is not None and self.is_mounted:
            self.run_worker(self._rebuild_and_resume())

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

        Note: we do NOT set ``_chat_display._detached = True`` here.  That
        flag means the widget has been removed from the DOM (workspace
        recomposition).  Setting it would block the post-stream cleanup in
        ``_sync_conversation``, leaving the input locked and the abort button
        stuck.
        """
        if self._stream_id is not None:
            ctx = self._get_context()
            if ctx and ctx.stream_manager:
                ctx.stream_manager.cancel(self._stream_id)
            self._stream_id = None
        if self._state is not None:
            self._state._stream_id = None
        if self._streaming_task is not None and not self._streaming_task.is_finished:
            self._streaming_task.cancel()
        self._streaming = False
        # Immediately unlock the input so the user can type again.
        # The async cleanup in _sync_conversation also calls these,
        # but only after the polling loop exits (up to 250ms delay).
        if hasattr(self, '_chat_input') and self._chat_input is not None:
            self._chat_input.set_streaming(False)
            self._chat_input.focus()

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
            self._state._agent = self._agent
            self._state._tools = self._tools
            self._state._db = self._db
            self._state._chat_id = self._chat_id
            self._state._turn_checkpoint_tags = self._turn_checkpoint_tags
            self._state._stream_id = self._stream_id

    async def _rebuild_and_resume(self) -> None:
        """Rebuild the display from the database and resume streaming if active.

        Called from ``_start_rebuild()`` (via ``call_after_refresh``) when
        the ChatManager is created with an existing chat_id — either from
        history panel or after workspace recomposition.  Loads sections
        from the database, refreshes the display, and re-enters the
        streaming loop if a stream was in progress.
        """
        logging.getLogger(__name__).warning(
            "_rebuild_and_resume: db=%s chat_id=%s mounted=%s display_mounted=%s detached=%s",
            self._db is not None,
            self._chat_id[:8] if self._chat_id else None,
            self.is_mounted,
            self._chat_display.is_mounted if hasattr(self, '_chat_display') else False,
            self._chat_display._detached if hasattr(self, '_chat_display') else 'N/A',
        )
        await self._sync_conversation(finalize=True)
        logging.getLogger(__name__).warning(
            "_rebuild_and_resume: sync done, display_children=%d",
            len(self._chat_display.children) if hasattr(self, '_chat_display') else 0,
        )

        # If a stream was active before recomposition, re-enter the
        # polling loop.
        if self._stream_id is not None:
            ctx = self._get_context()
            if ctx and ctx.stream_manager and ctx.stream_manager.has_stream(self._stream_id):
                self._chat_input.set_streaming(True)
                self._streaming = True
                self._streaming_task = self.run_worker(
                    self._sync_conversation(loop=True)
                )
            else:
                # Stream finished during recomposition -- already finalized.
                self._stream_id = None
                self._streaming = False
                if self._state is not None:
                    self._state._stream_id = None

    # ------------------------------------------------------------------
    # Conversation sync — single entry point for display updates
    # ------------------------------------------------------------------

    async def _sync_conversation(
        self, *, loop: bool = False, finalize: bool = False
    ) -> None:
        """Load sections from the database and refresh the display.

        Single entry point for all display updates: initial load,
        streaming poll loop, and post-recomposition rebuild.

        Parameters
        ----------
        loop:
            When True, poll the DB every 250ms until the stream
            completes.  Used for active streaming and stream resume
            after recomposition.
        finalize:
            When True, call ``finalize_turn()`` on the active
            assistant section after refreshing (swaps Static →
            Markdown, removes empty sections).
        """
        if self._db is None or self._chat_id is None:
            return

        ctx = self._get_context()
        sm = ctx.stream_manager if ctx else None

        if loop:
            # --- Streaming poll loop ---
            if sm is None:
                # No StreamManager available -- can't stream.
                return

            self._chat_input.set_streaming(True)
            self._streaming = True

            try:
                while sm.has_stream(self._stream_id):
                    if not self.is_mounted or self._chat_display._detached:
                        break
                    try:
                        sections = self._db.load_sections(self._chat_id)
                        await self._chat_display.refresh_from_sections(sections)
                    except Exception:
                        logging.getLogger(__name__).debug(
                            "Conversation sync refresh failed", exc_info=True
                        )
                    await asyncio.sleep(0.25)
            except asyncio.CancelledError:
                pass

            # Final refresh after stream completes or is cancelled.
            # This is the critical refresh that finalizes the display.
            finalize = True  # Always finalize after a streaming loop.

        # --- Single-shot refresh ---
        if self.is_mounted and not self._chat_display._detached:
            try:
                sections = self._db.load_sections(self._chat_id)
                logging.getLogger(__name__).warning(
                    "_sync_conversation: %d sections chat_id=%s finalize=%s",
                    len(sections), self._chat_id[:8] if self._chat_id else None, finalize,
                )
                await self._chat_display.refresh_from_sections(
                    sections, finalize=finalize
                )
                logging.getLogger(__name__).warning("_sync_conversation: refresh done")
                self._rebuild_history()
            except Exception:
                logging.getLogger(__name__).exception(
                    "Conversation sync (finalize=%s) failed",
                    finalize
                )
                # Retry without finalize so raw content is at least visible.
                if finalize:
                    try:
                        sections = self._db.load_sections(self._chat_id)
                        await self._chat_display.refresh_from_sections(sections)
                        self._rebuild_history()
                    except Exception:
                        logging.getLogger(__name__).error(
                            "Fallback sync also failed", exc_info=True
                        )
                # Show user-visible feedback on initial load failure.
                if finalize:
                    try:
                        self._chat_display.add_system_message(
                            "⚠ Failed to load conversation history. "
                            "Check the logs for details."
                        )
                    except Exception:
                        pass  # Best-effort — don't crash for a display error.

            self._attach_revert_buttons()

        # --- Post-stream cleanup ---
        if loop:
            # Update context usage bar with token counts.
            if sm is not None and self._stream_id:
                usage_chunk = sm.get_usage(self._stream_id)
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

    async def _handle_submit(self, user_text: str) -> None:
        """Full streaming turn: persist user msg to DB, start LLM stream, sync display."""
        turn_id = uuid.uuid4().hex

        # Create a git checkpoint before processing the user message.
        checkpoint_tag = self._create_turn_checkpoint(turn_id)

        # Persist user message to DB — the display will pick it up via
        # _sync_conversation polling refresh_from_sections().
        self._persist_section(turn_id, "user", user_text)

        if self._agent is None:
            # Persist error to DB and finalise — display reads from DB.
            self._persist_section(turn_id, "response", "No agent configured.")
            await self._sync_conversation(finalize=True)
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

        if stream_manager is None:
            # StreamManager is created by bootstrap and should always be present.
            self._persist_section(turn_id, "response", "StreamManager not available.")
            await self._sync_conversation(finalize=True)
            self._chat_input.set_streaming(False)
            self._streaming = False
            self._chat_input.focus()
            return

        self._stream_id = stream_manager.start(
            self._agent,
            self._history,
            user_text,
            tools=self._tools,
            db=self._db,
            chat_id=self._chat_id,
            turn_id=turn_id,
        )
        await self._sync_conversation(loop=True)

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
        """Write a single section row to the database.

        The database chat row is created lazily on the first persist
        call, so that tabs which are opened but never used do not leave
        empty conversations in the database.
        """
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

        Updates the database row.  The display is refreshed from the DB
        on the next sync cycle.
        """
        import json as _json
        updated_json = format_tool_call_json(name, arguments, result=result)

        # Update the database row.
        if self._db is not None and self._chat_id is not None:
            try:
                self._db.update_tool_result(
                    self._chat_id, turn_id, name, updated_json
                )
            except Exception:
                pass  # Best-effort -- don't crash the stream for a DB error.

    def _rebuild_history(self) -> None:
        """Rebuild in-memory LLM history from the database.

        Called after every streaming turn so that ``self._history``
        always reflects what was persisted.
        """
        if self._db is not None and self._chat_id is not None:
            try:
                self._history = self._db.reconstruct_history(self._chat_id)
            except Exception:
                self._history = []

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