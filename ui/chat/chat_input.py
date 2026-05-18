"""Chat input — wraps a Textual ``Input`` with send/abort button and command palette.

When idle, shows a **send** button.  When the agent is streaming,
the send button transforms into an **abort** button.  Pressing
``Escape`` while streaming also aborts.

Typing ``/`` shows a command palette above the input that lists
available slash commands.  Arrow keys navigate the palette, Enter
or Tab selects a command, and Escape dismisses it.

The palette widget is owned by :class:`~ui.chat.chat_manager.ChatManager`
and wired into the input via :meth:`set_palette`.  This keeps the
palette in the layout flow *between* the display and the input so
that the input bar stays anchored at the bottom even when the
palette is visible.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Button, Input

from ui.chat.command_palette import CommandPalette
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
        """Inject the command palette managed by :class:`~ui.chat.chat_manager.ChatManager`.

        The palette lives in the layout between the display and the
        input so that it can appear above the input without pushing
        the input around.  This method stores a reference so that
        key bindings and input-change handlers can control it.
        """
        self._palette = palette

    @property
    def palette(self) -> CommandPalette:
        """The command palette widget."""
        if self._palette is None:
            raise RuntimeError(
                "set_palette() must be called during mount — "
                "the palette is injected by ChatManager"
            )
        return self._palette

    # ------------------------------------------------------------------
    # Command palette integration
    # ------------------------------------------------------------------

    def on_input_changed(self, event: Input.Changed) -> None:
        """Show/filter the command palette when input starts with /.

        Programmatic changes (e.g. filling in a command name from the
        palette) set ``_suppress_palette_update`` so the palette isn't
        re-shown immediately after being hidden.
        """
        if self._suppress_palette_update:
            return
        text = event.value
        if text.startswith("/"):
            self.palette.update_filter(text)
        else:
            if self.palette.is_visible:
                self.palette.hide()

    def action_palette_up(self) -> None:
        """Navigate up in the command palette."""
        if self.palette.is_visible:
            self.palette.move_highlight(-1)

    def action_palette_down(self) -> None:
        """Navigate down in the command palette."""
        if self.palette.is_visible:
            self.palette.move_highlight(1)

    def action_palette_select_or_complete(self) -> None:
        """Tab key: fill the input with the selected command name."""
        if self.palette.is_visible:
            name = self.palette.select_highlighted()
            if name:
                self.palette.hide()
                # Suppress the on_input_changed that setting value triggers,
                # otherwise the palette re-shows because the text starts with /.
                self._suppress_palette_update = True
                try:
                    inp = self.query_one(Input)
                    inp.value = f"/{name} "
                    inp.cursor_end = True
                    inp.focus()
                finally:
                    self._suppress_palette_update = False

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
                # Hide palette when streaming starts
                if self.palette.is_visible:
                    self.palette.hide()
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

        If the command palette is currently visible, Enter selects
        from the palette and immediately submits the command — the
        palette closes and the command is dispatched.  If nothing is
        highlighted in the palette, it just closes without submitting.
        """
        if self.palette.is_visible:
            name = self.palette.select_highlighted()
            self.palette.hide()
            if name:
                # Submit the selected command immediately.
                self.post_message(self.ChatSubmitted(f"/{name}"))
            # If nothing was highlighted, just close the palette.
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
        """Escape key: close palette if visible, otherwise abort streaming."""
        if self.palette.is_visible:
            self.palette.hide()
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
        """Clear the underlying ``Input`` value and hide the palette."""
        self.query_one(Input).clear()
        if self.palette.is_visible:
            self.palette.hide()