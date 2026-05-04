"""Chat input — wraps a Textual ``Input`` and posts a ``ChatSubmitted`` message."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Input


class ChatInput(Widget):
    """A chat input widget wrapping a Textual ``Input``.

    Posts a ``ChatSubmitted`` message (with the trimmed text) when the
    user presses Enter on non-whitespace content.  Provides ``focus()``
    and ``clear()`` convenience methods.
    """

    class ChatSubmitted(Message):
        """Posted when the user submits non-empty text."""

        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text

    def compose(self) -> ComposeResult:
        yield Input(placeholder="Type a message…")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Intercept ``Input.Submitted``, repost as ``ChatSubmitted`` if valid."""
        text = event.value.strip()
        if text:
            self.post_message(self.ChatSubmitted(text))

    def focus(self) -> None:
        """Focus the underlying ``Input`` widget."""
        self.query_one(Input).focus()

    def clear(self) -> None:
        """Clear the underlying ``Input`` value."""
        self.query_one(Input).clear()
