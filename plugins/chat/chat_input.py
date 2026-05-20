"""Chat input — wraps a Textual ``Input`` with send/abort button and command/file palette.

When idle, shows a **send** button.  When the agent is streaming,
the send button transforms into an **abort** button.  Pressing
``Escape`` while streaming also aborts.

Typing ``/`` shows a command palette above the input that lists
available slash commands.  Typing ``@`` shows a file palette that
lists project files.  Arrow keys navigate the active palette, Enter
or Tab selects an item, and Escape dismisses it.

Both palette widgets are owned by :class:`~plugins.chat.chat_manager.ChatManager`
and wired into the input via :meth:`set_palette` and :meth:`set_file_palette`.
This keeps the palettes in the layout flow *between* the display and
the input so that the input bar stays anchored at the bottom even when
a palette is visible.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Button, Input

from plugins.chat.command_palette import CommandPalette
from plugins.chat.file_palette import FilePalette
from utils.icons import SEND, ABORT


class ChatInput(Widget):
    """A chat input widget with an integrated send/abort button and command palette.

    Posts:
    * ``ChatSubmitted(text)`` when the user submits non-empty text.
    * ``ChatAbortRequested`` when the user requests abort (button or Esc).

    The button starts as a send icon and switches to an abort icon when
    :meth:`set_streaming` is called with ``True``.  Call
    ``set_streaming(False)`` to switch back.

    Provides ``focus()``, ``clear()``, and ``set_streaming()`` methods.
    The :meth:`set_palette` method must be called during mount to inject
    the command palette managed by the parent :class:`~ui.chat.chat_manager.ChatManager`.
    """

    BINDINGS = [
        Binding("escape", "handle_escape", "Abort or close palette", show=False),
        Binding("up", "palette_up", "Navigate palette", show=False),
        Binding("down", "palette_down", "Navigate palette", show=False),
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
        self._palette: CommandPalette | None = None
        self._file_palette: FilePalette | None = None
        self._suppress_palette_update: bool = False

    # ------------------------------------------------------------------
    # Composition
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        with Horizontal(classes="chat-input-bar-horizontal"):
            yield Input(placeholder="Type a message…", classes="chat-input")
            yield Button(SEND, classes="chat-action-btn -send", id="chat-action-btn")

    # ------------------------------------------------------------------
    # Palette wiring
    # ------------------------------------------------------------------

    def set_palette(self, palette: CommandPalette) -> None:
        """Inject the command palette managed by :class:`~plugins.chat.chat_manager.ChatManager`.

        The palette lives in the layout between the display and the
        input so that it can appear above the input without pushing
        the input around.  This method stores a reference so that
        key bindings and input-change handlers can control it.
        """
        self._palette = palette

    def set_file_palette(self, file_palette: FilePalette) -> None:
        """Inject the file palette managed by :class:`~plugins.chat.chat_manager.ChatManager`.

        Same layout pattern as :meth:`set_palette` — the file palette
        sits between the display and the input.
        """
        self._file_palette = file_palette

    @property
    def palette(self) -> CommandPalette:
        """The command palette widget."""
        if self._palette is None:
            raise RuntimeError(
                "set_palette() must be called during mount — "
                "the palette is injected by ChatManager"
            )
        return self._palette

    @property
    def file_palette(self) -> FilePalette:
        """The file palette widget."""
        if self._file_palette is None:
            raise RuntimeError(
                "set_file_palette() must be called during mount — "
                "the file palette is injected by ChatManager"
            )
        return self._file_palette

    def _active_palette(self) -> CommandPalette | FilePalette | None:
        """Return whichever palette is currently visible, or ``None``."""
        if self._palette is not None and self._palette.is_visible:
            return self._palette
        if self._file_palette is not None and self._file_palette.is_visible:
            return self._file_palette
        return None

    # ------------------------------------------------------------------
    # Command palette integration
    # ------------------------------------------------------------------

    def on_input_changed(self, event: Input.Changed) -> None:
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
        if self._suppress_palette_update:
            return
        text = event.value

        # Command palette — only when input starts with /
        if text.startswith("/"):
            # Hide file palette if visible
            if self._file_palette is not None and self._file_palette.is_visible:
                self._file_palette.hide()
            self.palette.update_filter(text)
            return

        # Hide command palette if visible (input no longer starts with /)
        if self._palette is not None and self._palette.is_visible:
            self._palette.hide()

        # File palette — detect last @ in the input
        if self._file_palette is not None:
            at_idx = text.rfind("@")
            if at_idx != -1:
                after_at = text[at_idx + 1 :]
                # If there's a space after the @ token, the mention is
                # complete (e.g. "@file_editor.py continues").  Hide the
                # palette so the user can keep typing their message.
                space_idx = after_at.find(" ")
                if space_idx != -1:
                    if self._file_palette.is_visible:
                        self._file_palette.hide()
                else:
                    # Still typing the @ query — filter the palette
                    query = after_at
                    self._file_palette.update_filter(query)
            else:
                if self._file_palette.is_visible:
                    self._file_palette.hide()

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
        if self._palette is not None and self._palette.is_visible:
            name = self._palette.select_highlighted()
            if name:
                self._palette.hide()
                self._suppress_palette_update = True
                try:
                    inp = self.query_one(Input)
                    inp.value = f"/{name} "
                    inp.cursor_end = True
                    inp.focus()
                finally:
                    self._suppress_palette_update = False
            return

        # File palette
        if self._file_palette is not None and self._file_palette.is_visible:
            filepath = self._file_palette.select_highlighted()
            if filepath:
                self._file_palette.hide()
                inp = self.query_one(Input)
                text = inp.value
                at_idx = text.rfind("@")
                if at_idx != -1:
                    # Replace from @ to cursor with @filepath
                    prefix = text[:at_idx]
                    suffix_start = at_idx + 1 + len(text[at_idx + 1 :])
                    # Find end of current @query token (stop at space or end)
                    after_at = text[at_idx + 1 :]
                    token_end = len(after_at)
                    for i, ch in enumerate(after_at):
                        if ch == " ":
                            token_end = i
                            break
                    new_text = prefix + f"@{filepath} " + text[at_idx + 1 + token_end :]
                    self._suppress_palette_update = True
                    try:
                        inp.value = new_text
                        inp.cursor_end = True
                        inp.focus()
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
            inp = self.query_one(Input)
            if streaming:
                btn.label = ABORT
                btn.remove_class("-send")
                btn.add_class("-abort")
                inp.disabled = True
                # Hide palettes when streaming starts
                if self._palette is not None and self._palette.is_visible:
                    self._palette.hide()
                if self._file_palette is not None and self._file_palette.is_visible:
                    self._file_palette.hide()
            else:
                btn.label = SEND
                btn.remove_class("-abort")
                btn.add_class("-send")
                inp.disabled = False
                inp.focus()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Input submission
    # ------------------------------------------------------------------

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Intercept ``Input.Submitted`` and repost as ``ChatSubmitted``.

        If a palette is currently visible, Enter selects from it:
        - Command palette: submits the command immediately.
        - File palette: inserts the file path into the input (does not
          submit the message).
        If nothing is highlighted in the palette, it just closes
        without submitting.
        """
        # Command palette
        if self._palette is not None and self._palette.is_visible:
            name = self._palette.select_highlighted()
            self._palette.hide()
            if name:
                self.post_message(self.ChatSubmitted(f"/{name}"))
            return

        # File palette — insert the file path, don't submit
        if self._file_palette is not None and self._file_palette.is_visible:
            filepath = self._file_palette.select_highlighted()
            self._file_palette.hide()
            if filepath:
                inp = self.query_one(Input)
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
                    new_text = prefix + f"@{filepath} " + text[at_idx + 1 + token_end :]
                    self._suppress_palette_update = True
                    try:
                        inp.value = new_text
                        inp.cursor_end = True
                        inp.focus()
                    finally:
                        self._suppress_palette_update = False
            return

        text = event.value.strip()
        if text and not self._streaming:
            self.post_message(self.ChatSubmitted(text))

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
            # Send: read the input value and submit
            inp = self.query_one(Input)
            text = inp.value.strip()
            if text:
                self.post_message(self.ChatSubmitted(text))

    # ------------------------------------------------------------------
    # Key bindings
    # ------------------------------------------------------------------

    def action_handle_escape(self) -> None:
        """Escape key: close whichever palette is visible, otherwise abort streaming."""
        if self._palette is not None and self._palette.is_visible:
            self._palette.hide()
            return
        if self._file_palette is not None and self._file_palette.is_visible:
            self._file_palette.hide()
            return
        if self._streaming:
            self.post_message(self.ChatAbortRequested())

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    def focus(self) -> None:
        """Focus the underlying ``Input`` widget."""
        self.query_one(Input).focus()

    def clear(self) -> None:
        """Clear the underlying ``Input`` value and hide all palettes."""
        self.query_one(Input).clear()
        if self._palette is not None and self._palette.is_visible:
            self._palette.hide()
        if self._file_palette is not None and self._file_palette.is_visible:
            self._file_palette.hide()