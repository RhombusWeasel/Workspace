"""Chat input — wraps a Textual ``TextArea`` with send/abort button and command/file palette.

When idle, shows a **send** button.  When the agent is streaming,
the send button transforms into an **abort** button.  Pressing
``Escape`` while streaming also aborts.

Typing ``/`` shows a command palette above the input that lists
available slash commands.  Typing ``@`` shows a file palette that
lists project files.  Arrow keys navigate the active palette, Enter
or Tab selects an item, and Escape dismisses it.

**Enter** submits the message.  **Shift+Enter** inserts a newline so
the user can write multi-line messages.

Both palette widgets are composed inside the
:class:`ChatInput` above the text bar so that they naturally appear above
the input when visible, without overlapping the TextArea viewport.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.events import Key
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Button, TextArea

from skills.chat.command_palette import CommandPalette
from skills.chat.context_usage_bar import ContextUsageBar
from skills.chat.file_palette import FilePalette, scan_files
from utils.icons import SEND, ABORT

import os


class ChatTextArea(TextArea):
    """A :class:`~textual.widgets.TextArea` subclass that intercepts key events
    before the base class can consume them and provides inline completion
    suggestions for ``/`` commands and ``@`` file mentions.

    When the user presses **Enter** (without Shift) this widget stops the
    key event and posts a :class:`SubmitRequested` message so the parent
    :class:`ChatInput` can handle submission.  **Shift+Enter** falls through
    to the base ``TextArea`` handler and inserts a newline as usual.

    **Arrow up/down** are intercepted when a palette (command or file) is
    visible, so that the parent :class:`ChatInput` can use them to navigate
    the palette.  Without this, the inherited ``TextArea`` bindings would
    consume up/down and move the text cursor instead.

    **Right arrow** at the end of the text accepts the current inline
    suggestion (if any), completing the ``/`` command or ``@`` file mention.

    Inline suggestions are computed in :meth:`update_suggestion` which is
    called automatically by the base ``TextArea`` after every content change.
    When the input starts with ``/`` a slash-command completion is shown;
    when it contains ``@`` a file-path completion is shown.
    """

    class SubmitRequested(Message):
        """Posted when the user presses Enter (without Shift) in the chat input."""

        pass

    class PaletteKey(Message):
        """Posted when an arrow key should be forwarded to a palette."""

        def __init__(self, key: str) -> None:
            super().__init__()
            self.key = key

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._working_directory: str = ""
        self._all_files: list[str] | None = None

    def set_working_directory(self, wd: str) -> None:
        """Set the working directory for file suggestions."""
        if wd != self._working_directory:
            self._working_directory = wd
            self._all_files = None  # invalidate cache

    def _ensure_files_scanned(self) -> None:
        """Scan the working directory for files if the cache is cold."""
        if self._all_files is not None:
            return
        wd = self._working_directory or os.getcwd()
        self._all_files = scan_files(wd)

    def update_suggestion(self) -> None:
        """Compute and set an inline suggestion based on the current text.

        Called automatically by the base ``TextArea`` after every content
        change.  Sets :attr:`suggestion` to a completion string when the
        input starts with ``/`` (command) or contains ``@`` (file), and
        clears it otherwise.

        For commands, the suggestion shows the rest of the command name
        (e.g. typing ``/cl`` suggests ``ear`` to complete ``/clear``).

        For files, the suggestion shows the rest of the file path when the
        text after ``@`` is a prefix of a file path (e.g. typing ``@main``
        suggests ``.py `` to complete ``@main.py ``).  Substring matches
        (e.g. ``@chat_input`` matching ``skills/chat/chat_input.py``) are
        not shown as inline suggestions because ``TextArea.suggestion``
        can only append text, not replace it — those matches are still
        available in the file palette dropdown.
        """
        text = self.text
        suggestion = ""

        if text.startswith("/"):
            # Slash-command completion
            partial = text[1:].casefold()
            from core.commands import list_commands
            commands = list_commands()
            for cmd_name in commands:
                if cmd_name.casefold().startswith(partial) and len(cmd_name) > len(partial):
                    # Show only the part the user hasn't typed yet
                    suggestion = cmd_name[len(partial):]
                    break

        elif "@" in text:
            # File-path completion — only suggest when the text after @
            # is a prefix of a file path, since TextArea.suggestion can
            # only append text (not replace what the user already typed).
            at_idx = text.rfind("@")
            after_at = text[at_idx + 1 :]
            space_idx = after_at.find(" ")
            if space_idx == -1 and after_at:
                partial = after_at.casefold()
                self._ensure_files_scanned()
                if self._all_files is not None:
                    for relpath in self._all_files:
                        # Prefix match: the file path must start with
                        # what the user typed after @
                        if relpath.casefold().startswith(partial) and len(relpath) > len(partial):
                            suggestion = relpath[len(partial):] + " "
                            break

        self.suggestion = suggestion

    async def _on_key(self, event: Key) -> None:
        """Intercept key events before the base class can consume them.

        * **Enter** (no Shift): stop the event, prevent default, and post
          :class:`SubmitRequested`.
        * **Shift+Enter**: insert a newline (the base ``TextArea`` only
          handles ``"enter"``, not ``"shift+enter"``, so we do it here).
        * **Up/Down**: stop the event and post :class:`PaletteKey` so the
          parent can navigate the palette or move the cursor.
        * **Right arrow** at end of text: accept the current inline suggestion.
        * Everything else: fall through to the base ``TextArea`` handler
          (which is async, so we must ``await`` it).
        """
        if event.key == "enter":
            event.prevent_default()
            event.stop()
            self.post_message(self.SubmitRequested())
            return
        if event.key == "shift+enter":
            event.prevent_default()
            event.stop()
            start, end = self.selection
            self._replace_via_keyboard("\n", start, end)
            return
        if event.key in ("up", "down"):
            event.prevent_default()
            event.stop()
            self.post_message(self.PaletteKey(event.key))
            return
        # Right arrow at end of text accepts the inline suggestion.
        if event.key == "right" and self.suggestion:
            row, col = self.cursor_location
            lines = self.document.lines
            if row < len(lines) and col >= len(lines[row]):
                # Cursor is at end of line — accept the suggestion
                event.prevent_default()
                event.stop()
                self.insert(self.suggestion)
                return
        # Everything else goes to the base class — must be awaited.
        await super()._on_key(event)


class ChatInput(Widget):
    """A chat input widget with an integrated send/abort button and command palette.

    Posts:
    * ``ChatSubmitted(text)`` when the user submits non-empty text.
    * ``ChatAbortRequested`` when the user requests abort (button or Esc).

    The button starts as a send icon and switches to an abort icon when
    :meth:`set_streaming` is called with ``True``.  Call
    ``set_streaming(False)`` to switch back.

    **Enter** submits the message.  **Shift+Enter** inserts a newline
    so the user can compose multi-line messages.

    Provides ``focus()``, ``clear()``, and ``set_streaming()`` methods.
    The command and file palettes are composed directly inside this widget
    above the text bar.
    """

    BINDINGS = [
        Binding("escape", "handle_escape", "Abort or close palette", show=False),
        Binding("tab", "palette_select_or_complete", "Select command", show=False),
    ]

    class ChatSubmitted(Message):
        """Posted when the user submits non-empty text."""

        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text

    class ChatAbortRequested(Message):
        """Posted when the user requests abort of the current stream."""

        pass

    def __init__(self):
        super().__init__()
        self._streaming: bool = False
        self._suppress_palette_update: bool = False
        self._multiline: bool = False
        """Whether the input is in multi-line mode (user pressed Shift+Enter
        or text contains newlines).  When False, the TextArea is constrained
        to a single visible line to minimise vertical space."""
        self._context_progress: int = 0
        """Current progress value (tokens used) for the context bar."""
        self._context_total: int = 0
        """Total context window size for the context bar."""

    # ------------------------------------------------------------------
    # Composition
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        with Vertical(classes="chat-input-container"):
            yield CommandPalette()
            yield FilePalette()
            with Horizontal(classes="chat-input-bar-horizontal"):
                ta = ChatTextArea(
                    "",
                    placeholder="Type a message…",
                    classes="chat-input single-line",
                    soft_wrap=True,
                    show_line_numbers=False,
                    tab_behavior="focus",
                    compact=True,
                )
                yield ta
                yield Button(SEND, classes="chat-action-btn -send", id="chat-action-btn")
            yield ContextUsageBar()

    # ------------------------------------------------------------------
    # Palette access
    # ------------------------------------------------------------------

    @property
    def palette(self) -> CommandPalette:
        """The command palette widget."""
        return self.query_one(CommandPalette)

    @property
    def file_palette(self) -> FilePalette:
        """The file palette widget."""
        return self.query_one(FilePalette)

    def _active_palette(self) -> CommandPalette | FilePalette | None:
        """Return whichever palette is currently visible, or ``None``."""
        if self.palette.is_visible:
            return self.palette
        if self.file_palette.is_visible:
            return self.file_palette
        return None

    def set_working_directory(self, wd: str) -> None:
        """Set the working directory for file suggestions and the file palette.

        Propagates the working directory to both the :class:`ChatTextArea`
        (for inline file-path suggestions) and the :class:`FilePalette`
        (for the dropdown file picker).
        """
        ta = self.query_one(ChatTextArea)
        ta.set_working_directory(wd)
        self.file_palette.set_working_directory(wd)

    # ------------------------------------------------------------------
    # Command palette integration
    # ------------------------------------------------------------------

    def _update_multiline(self) -> None:
        """Update the multiline state based on the current text content.

        If the text contains newlines, switches to multi-line mode (expands
        the TextArea).  If the text has no newlines, switches back to
        single-line mode (collapses the TextArea).
        """
        ta = self.query_one(ChatTextArea)
        has_newlines = "\n" in ta.text
        if has_newlines and not self._multiline:
            self._multiline = True
            ta.add_class("multiline")
            ta.remove_class("single-line")
        elif not has_newlines and self._multiline:
            self._multiline = False
            ta.remove_class("multiline")
            ta.add_class("single-line")

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        """Show/filter the command palette when input starts with /, or the
        file palette when the input contains @.

        Programmatic changes (e.g. filling in a value from a palette
        selection) set ``_suppress_palette_update`` so palettes aren't
        re-shown immediately after being hidden.

        Only one palette is visible at a time.  Typing ``/`` at the
        start of the input opens the command palette.  Typing ``@``
        anywhere in the input opens the file palette, filtering by
        the text after the last ``@``.
        """
        # Update multiline mode based on text content (e.g. paste).
        self._update_multiline()

        if self._suppress_palette_update:
            return
        text = event.text_area.text

        # Command palette — only when input starts with /
        if text.startswith("/"):
            # Hide file palette if visible
            if self.file_palette.is_visible:
                self.file_palette.hide()
            self.palette.update_filter(text)
            return

        # Hide command palette if visible (input no longer starts with /)
        if self.palette.is_visible:
            self.palette.hide()

        # File palette — detect last @ in the input
        at_idx = text.rfind("@")
        if at_idx != -1:
            after_at = text[at_idx + 1 :]
            # If there's a space after the @ token, the mention is
            # complete (e.g. "@file_editor.py continues").  Hide the
            # palette so the user can keep typing their message.
            space_idx = after_at.find(" ")
            if space_idx != -1:
                if self.file_palette.is_visible:
                    self.file_palette.hide()
            else:
                # Still typing the @ query — filter the palette
                query = after_at
                self.file_palette.update_filter(query)
        else:
            if self.file_palette.is_visible:
                self.file_palette.hide()

    def action_palette_up(self) -> None:
        """Navigate up in whichever palette is currently visible."""
        active = self._active_palette()
        if active is not None:
            active.move_highlight(-1)

    def action_palette_down(self) -> None:
        """Navigate down in whichever palette is currently visible."""
        active = self._active_palette()
        if active is not None:
            active.move_highlight(1)

    def action_palette_select_or_complete(self) -> None:
        """Tab key: fill the input with the selected item.

        If the command palette is visible, fills with ``/{name} ``.
        If the file palette is visible, replaces the ``@query`` portion
        with ``@filepath `` while preserving surrounding text.
        """
        # Command palette
        if self.palette.is_visible:
            name = self.palette.select_highlighted()
            if name:
                self.palette.hide()
                self._suppress_palette_update = True
                try:
                    ta = self.query_one(ChatTextArea)
                    ta.text = f"/{name} "
                    ta.cursor_location = (0, len(ta.text))
                    ta.focus()
                finally:
                    self._suppress_palette_update = False
            return

        # File palette
        if self.file_palette.is_visible:
            filepath = self.file_palette.select_highlighted()
            if filepath:
                self.file_palette.hide()
                ta = self.query_one(ChatTextArea)
                text = ta.text
                at_idx = text.rfind("@")
                if at_idx != -1:
                    # Replace from @ to cursor with @filepath
                    prefix = text[:at_idx]
                    after_at = text[at_idx + 1 :]
                    token_end = len(after_at)
                    for i, ch in enumerate(after_at):
                        if ch == " ":
                            token_end = i
                            break
                    new_text = prefix + f"@{filepath} " + text[at_idx + 1 + token_end :]
                    self._suppress_palette_update = True
                    try:
                        ta.text = new_text
                        ta.cursor_location = (0, len(ta.text))
                        ta.focus()
                    finally:
                        self._suppress_palette_update = False
            return

    # ------------------------------------------------------------------
    # Streaming state
    # ------------------------------------------------------------------

    @property
    def is_streaming(self) -> bool:
        """Whether the agent is currently streaming a response."""
        return self._streaming

    def set_streaming(self, streaming: bool) -> None:
        """Toggle between streaming and idle mode.

        When streaming, the send button becomes an abort button and
        the input field is disabled.  When idle, the send button is
        shown and the input is enabled.
        """
        self._streaming = streaming
        try:
            btn = self.query_one("#chat-action-btn", Button)
            ta = self.query_one(ChatTextArea)
            if streaming:
                btn.label = ABORT
                btn.remove_class("-send")
                btn.add_class("-abort")
                ta.disabled = True
                # Hide palettes when streaming starts
                if self.palette.is_visible:
                    self.palette.hide()
                if self.file_palette.is_visible:
                    self.file_palette.hide()
            else:
                btn.label = SEND
                btn.remove_class("-abort")
                btn.add_class("-send")
                ta.disabled = False
                ta.focus()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Key handling — Enter submits, Shift+Enter inserts newline
    # ------------------------------------------------------------------

    def on_chat_text_area_palette_key(
        self, event: ChatTextArea.PaletteKey
    ) -> None:
        """Handle up/down arrow keys from the text area.

        The :class:`ChatTextArea` intercepts up/down and stops them before
        the ``TextArea`` base class can consume them.  If a palette is
        visible, we navigate it; otherwise we move the text cursor.
        """
        event.stop()
        active = self._active_palette()
        if active is not None:
            if event.key == "up":
                active.move_highlight(-1)
            elif event.key == "down":
                active.move_highlight(1)
        else:
            # No palette visible — move the text cursor as normal.
            ta = self.query_one(ChatTextArea)
            if event.key == "up":
                ta.action_cursor_up()
            elif event.key == "down":
                ta.action_cursor_down()

    def on_chat_text_area_submit_requested(
        self, event: ChatTextArea.SubmitRequested
    ) -> None:
        """Handle Enter pressed in the :class:`ChatTextArea`.

        The :class:`ChatTextArea` has already stopped the key event; we
        just need to decide what *Enter* means:

        * If a palette is visible, select from it.
        * Otherwise, submit the message.
        """
        event.stop()

        # If a palette is visible, Enter selects from it.
        if self.palette.is_visible:
            name = self.palette.select_highlighted()
            self.palette.hide()
            if name:
                self.post_message(self.ChatSubmitted(f"/{name}"))
            return

        if self.file_palette.is_visible:
            filepath = self.file_palette.select_highlighted()
            self.file_palette.hide()
            if filepath:
                ta = self.query_one(ChatTextArea)
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
                    new_text = prefix + f"@{filepath} " + text[at_idx + 1 + token_end :]
                    self._suppress_palette_update = True
                    try:
                        ta.text = new_text
                        ta.cursor_location = (0, len(ta.text))
                        ta.focus()
                    finally:
                        self._suppress_palette_update = False
            return

        # No palette — submit the message.
        ta = self.query_one(ChatTextArea)
        text = ta.text.strip()
        if text and not self._streaming:
            self.post_message(self.ChatSubmitted(text))

    def _on_key(self, event: Key) -> None:
        """Handle Shift+Enter for multi-line expansion.

        Bare Enter is handled by :class:`ChatTextArea` which posts
        :class:`ChatTextArea.SubmitRequested`.  This handler only
        deals with **Shift+Enter** — letting the ``TextArea`` base
        class insert a newline, then expanding the input.
        """
        if event.key == "shift+enter":
            # Let TextArea handle the newline insertion, then expand.
            self.call_later(self._update_multiline)
            return

    # ------------------------------------------------------------------
    # Button press
    # ------------------------------------------------------------------

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle send/abort button presses."""
        event.stop()
        if event.button.id != "chat-action-btn":
            return

        if self._streaming:
            self.post_message(self.ChatAbortRequested())
        else:
            # Send: read the text area value and submit
            ta = self.query_one(ChatTextArea)
            text = ta.text.strip()
            if text:
                self.post_message(self.ChatSubmitted(text))

    # ------------------------------------------------------------------
    # Key bindings
    # ------------------------------------------------------------------

    def action_handle_escape(self) -> None:
        """Escape key: close whichever palette is visible, otherwise abort streaming."""
        if self.palette.is_visible:
            self.palette.hide()
            return
        if self.file_palette.is_visible:
            self.file_palette.hide()
            return
        if self._streaming:
            self.post_message(self.ChatAbortRequested())

    # ------------------------------------------------------------------
    # Context progress bar
    # ------------------------------------------------------------------

    def update_context_progress(self, model_name: str, used: int, total: int | None) -> None:
        """Update the context window progress bar.

        Parameters
        ----------
        model_name:
            Display name of the model (e.g. ``"qwen3.5:0.8b"``).
        used:
            Number of tokens used so far (prompt + completion).
        total:
            Maximum context window size, or ``None`` if unknown.
        """
        self._context_progress = used
        self._context_total = total or 0
        try:
            bar = self.query_one(ContextUsageBar)
            bar.update(model_name, used, total)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    def focus(self) -> None:
        """Focus the underlying ``TextArea`` widget."""
        self.query_one(ChatTextArea).focus()

    def clear(self) -> None:
        """Clear the underlying ``TextArea`` value, reset to single-line mode, and hide all palettes."""
        ta = self.query_one(ChatTextArea)
        ta.text = ""
        ta.cursor_location = (0, 0)
        ta.suggestion = ""  # Clear any inline suggestion
        # Reset to single-line mode after sending
        self._multiline = False
        ta.remove_class("multiline")
        ta.add_class("single-line")
        if self.palette.is_visible:
            self.palette.hide()
        if self.file_palette.is_visible:
            self.file_palette.hide()