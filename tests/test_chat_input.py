"""Tests for the ChatInput widget.

ChatInput wraps a Textual ``Input`` and posts a ``ChatSubmitted``
message on submission.
"""

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Input

from ui.chat.chat_input import ChatInput


# ---------------------------------------------------------------------------
# Test app
# ---------------------------------------------------------------------------


class ChatInputTestApp(App):
    """Minimal app hosting a ChatInput."""

    CSS = """
    ChatInput {
        width: 60;
    }
    """

    def __init__(self):
        super().__init__()
        self.submitted_messages: list[ChatInput.ChatSubmitted] = []

    def compose(self) -> ComposeResult:
        self.chat_input = ChatInput()
        yield self.chat_input

    def on_chat_input_chat_submitted(self, event: ChatInput.ChatSubmitted) -> None:
        self.submitted_messages.append(event)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _settle(pilot, n: int = 2) -> None:
    for _ in range(n):
        await pilot.pause()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestChatInput:
    async def test_contains_input_widget(self):
        """ChatInput composes a Textual Input."""
        async with ChatInputTestApp().run_test() as pilot:
            await pilot.pause()
            widgets = pilot.app.chat_input.query(Input)
            assert len(widgets) == 1

    async def test_posts_chat_submitted_on_input_submit(self):
        """When Input.Submitted fires with non-empty text, ChatSubmitted is posted."""
        async with ChatInputTestApp().run_test() as pilot:
            await pilot.pause()

            inp = pilot.app.chat_input.query_one(Input)
            inp.value = "Hello, world!"
            inp.post_message(Input.Submitted(inp, "Hello, world!"))
            await _settle(pilot)

            assert len(pilot.app.submitted_messages) == 1
            assert pilot.app.submitted_messages[0].text == "Hello, world!"

    async def test_ignores_empty_submissions(self):
        """Empty or whitespace-only input does not post ChatSubmitted."""
        async with ChatInputTestApp().run_test() as pilot:
            await pilot.pause()

            inp = pilot.app.chat_input.query_one(Input)
            inp.value = "   "
            inp.post_message(Input.Submitted(inp, "   "))
            await _settle(pilot)

            assert len(pilot.app.submitted_messages) == 0

    async def test_clear_empties_input(self):
        """clear() empties the internal Input value."""
        async with ChatInputTestApp().run_test() as pilot:
            await pilot.pause()

            inp = pilot.app.chat_input.query_one(Input)
            inp.value = "something"
            pilot.app.chat_input.clear()
            await _settle(pilot)
            assert inp.value == ""

    async def test_focus_focuses_input(self):
        """focus() gives keyboard focus to the internal Input."""
        async with ChatInputTestApp().run_test() as pilot:
            await pilot.pause()

            pilot.app.chat_input.focus()
            await _settle(pilot)
            focused = pilot.app.focused
            assert focused is not None
            assert isinstance(focused, Input)
