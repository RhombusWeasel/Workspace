"""Tests for the ChatInput widget.

ChatInput wraps a Textual ``Input`` and a send/abort button.
It posts ``ChatSubmitted`` on submission and ``ChatAbortRequested``
when abort is triggered during streaming.
"""

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Button, Input

from plugins.chat.chat_input import ChatInput
from plugins.chat.command_palette import CommandPalette
from core.commands import reset_commands


# ---------------------------------------------------------------------------
# Test app
# ---------------------------------------------------------------------------


class ChatInputTestApp(App):
    """Minimal app hosting a ChatInput with a wired-up palette."""

    CSS = """
    ChatInput {
        width: 60;
    }
    """

    def __init__(self):
        super().__init__()
        self.submitted_messages: list[ChatInput.ChatSubmitted] = []
        self.abort_count: int = 0

    def compose(self) -> ComposeResult:
        self.chat_input = ChatInput()
        self._palette = CommandPalette()
        yield self.chat_input
        yield self._palette

    def on_mount(self) -> None:
        self.chat_input.set_palette(self._palette)

    def on_chat_input_chat_submitted(self, event: ChatInput.ChatSubmitted) -> None:
        self.submitted_messages.append(event)

    def on_chat_input_chat_abort_requested(self, event: ChatInput.ChatAbortRequested) -> None:
        self.abort_count += 1


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_commands():
    reset_commands()


async def _settle(pilot, n: int = 2) -> None:
    for _ in range(n):
        await pilot.pause()


# ---------------------------------------------------------------------------
# Tests — composition
# ---------------------------------------------------------------------------


class TestChatInputComposition:
    async def test_contains_input_widget(self):
        """ChatInput composes a Textual Input."""
        async with ChatInputTestApp().run_test() as pilot:
            await pilot.pause()
            widgets = pilot.app.chat_input.query(Input)
            assert len(widgets) == 1

    async def test_contains_action_button(self):
        """ChatInput composes a send/abort button."""
        async with ChatInputTestApp().run_test() as pilot:
            await pilot.pause()
            buttons = pilot.app.chat_input.query("#chat-action-btn")
            assert len(buttons) == 1

    async def test_button_starts_as_send(self):
        """The action button starts in send mode (icon)."""
        async with ChatInputTestApp().run_test() as pilot:
            await pilot.pause()
            btn = pilot.app.chat_input.query_one("#chat-action-btn", Button)
            # Just verify the button exists and isn't in abort mode
            assert not btn.has_class("-abort")


# ---------------------------------------------------------------------------
# Tests — submission
# ---------------------------------------------------------------------------


class TestChatInputSubmission:
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

    async def test_send_button_posts_submitted(self):
        """Clicking the send button posts ChatSubmitted."""
        async with ChatInputTestApp().run_test() as pilot:
            await pilot.pause()

            inp = pilot.app.chat_input.query_one(Input)
            inp.value = "Hello!"
            btn = pilot.app.chat_input.query_one("#chat-action-btn", Button)
            btn.press()
            await _settle(pilot)

            assert len(pilot.app.submitted_messages) == 1
            assert pilot.app.submitted_messages[0].text == "Hello!"

    async def test_send_button_ignores_empty(self):
        """Clicking send with empty input does not post ChatSubmitted."""
        async with ChatInputTestApp().run_test() as pilot:
            await pilot.pause()

            inp = pilot.app.chat_input.query_one(Input)
            inp.value = ""
            btn = pilot.app.chat_input.query_one("#chat-action-btn", Button)
            btn.press()
            await _settle(pilot)

            assert len(pilot.app.submitted_messages) == 0


# ---------------------------------------------------------------------------
# Tests — streaming state
# ---------------------------------------------------------------------------


class TestChatInputStreaming:
    async def test_set_streaming_true_switches_to_abort(self):
        """set_streaming(True) changes the button to abort mode."""
        async with ChatInputTestApp().run_test() as pilot:
            await pilot.pause()

            ci = pilot.app.chat_input
            ci.set_streaming(True)
            await _settle(pilot)

            btn = ci.query_one("#chat-action-btn", Button)
            inp = ci.query_one(Input)
            assert btn.has_class("-abort")
            assert not btn.has_class("-send")
            assert inp.disabled is True

    async def test_set_streaming_false_switches_back(self):
        """set_streaming(False) restores the button to send mode."""
        async with ChatInputTestApp().run_test() as pilot:
            await pilot.pause()

            ci = pilot.app.chat_input
            ci.set_streaming(True)
            await _settle(pilot)
            ci.set_streaming(False)
            await _settle(pilot)

            btn = ci.query_one("#chat-action-btn", Button)
            inp = ci.query_one(Input)
            assert btn.has_class("-send")
            assert not btn.has_class("-abort")
            assert inp.disabled is False

    async def test_is_streaming_property(self):
        """is_streaming reflects the current streaming state."""
        async with ChatInputTestApp().run_test() as pilot:
            await pilot.pause()

            ci = pilot.app.chat_input
            assert ci.is_streaming is False
            ci.set_streaming(True)
            assert ci.is_streaming is True
            ci.set_streaming(False)
            assert ci.is_streaming is False

    async def test_abort_button_posts_abort_requested(self):
        """Clicking abort during streaming posts ChatAbortRequested."""
        async with ChatInputTestApp().run_test() as pilot:
            await pilot.pause()

            ci = pilot.app.chat_input
            ci.set_streaming(True)
            await _settle(pilot)

            btn = ci.query_one("#chat-action-btn", Button)
            btn.press()
            await _settle(pilot)

            assert pilot.app.abort_count == 1

    async def test_escape_during_streaming_posts_abort_requested(self):
        """Pressing Escape during streaming posts ChatAbortRequested."""
        async with ChatInputTestApp().run_test() as pilot:
            await pilot.pause()

            ci = pilot.app.chat_input
            ci.set_streaming(True)
            await _settle(pilot)

            # Simulate Escape key press
            ci.action_handle_escape()
            await _settle(pilot)

            assert pilot.app.abort_count == 1

    async def test_escape_when_not_streaming_is_noop(self):
        """Pressing Escape when not streaming does not post ChatAbortRequested."""
        async with ChatInputTestApp().run_test() as pilot:
            await pilot.pause()

            ci = pilot.app.chat_input
            assert ci.is_streaming is False
            ci.action_handle_escape()  # Escape when not streaming just hides palette

            assert pilot.app.abort_count == 0

    async def test_input_disabled_during_streaming(self):
        """The input field is disabled while streaming."""
        async with ChatInputTestApp().run_test() as pilot:
            await pilot.pause()

            ci = pilot.app.chat_input
            inp = ci.query_one(Input)

            assert inp.disabled is False
            ci.set_streaming(True)
            assert inp.disabled is True
            ci.set_streaming(False)
            assert inp.disabled is False

    async def test_send_button_does_not_submit_during_streaming(self):
        """Clicking the button during streaming aborts, doesn't submit."""
        async with ChatInputTestApp().run_test() as pilot:
            await pilot.pause()

            ci = pilot.app.chat_input
            inp = ci.query_one(Input)
            inp.value = "test"
            ci.set_streaming(True)
            await _settle(pilot)

            btn = ci.query_one("#chat-action-btn", Button)
            btn.press()
            await _settle(pilot)

            # Abort requested, not submitted
            assert pilot.app.abort_count == 1
            assert len(pilot.app.submitted_messages) == 0

    async def test_input_submitted_does_not_fire_during_streaming(self):
        """Pressing Enter in the input during streaming doesn't submit."""
        async with ChatInputTestApp().run_test() as pilot:
            await pilot.pause()

            ci = pilot.app.chat_input
            inp = ci.query_one(Input)

            ci.set_streaming(True)
            inp.value = "Hello"
            inp.post_message(Input.Submitted(inp, "Hello"))
            await _settle(pilot)

            assert len(pilot.app.submitted_messages) == 0


# ---------------------------------------------------------------------------
# Tests — convenience methods
# ---------------------------------------------------------------------------


class TestChatInputConvenience:
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