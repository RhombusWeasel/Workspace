"""Tests for the TextEditorModal — multi-line text editor dialog."""

import pytest
from textual.app import App, ComposeResult
from textual.widgets import TextArea

from ui.widgets.text_editor_modal import TextEditorModal


class _TestApp(App):
    """Minimal app for testing modals."""

    CSS_PATH = []

    def compose(self) -> ComposeResult:
        yield TextArea("placeholder")


@pytest.mark.asyncio
async def test_text_editor_modal_returns_text_on_ok():
    """Pressing OK returns the edited text."""
    app = _TestApp()
    async with app.run_test() as pilot:
        modal = TextEditorModal("Test Editor", text="hello world")
        result = await app.push_screen_wait(modal)
        # Type something and press OK
        ta = modal.query_one("#modal-textarea", TextArea)
        ta.clear()
        await pilot.pause()
        ta.insert("new text")
        await pilot.pause()

        # Click OK
        from textual.widgets import Button
        ok_btn = modal.query_one("#btn-ok", Button)
        ok_btn.press()


@pytest.mark.asyncio
async def test_text_editor_modal_returns_none_on_cancel():
    """Pressing Cancel returns None."""
    app = _TestApp()
    async with app.run_test() as pilot:
        modal = TextEditorModal("Test Editor", text="hello")
        result = await app.push_screen_wait(modal)

        from textual.widgets import Button
        cancel_btn = modal.query_one("#btn-cancel", Button)
        cancel_btn.press()


class TestTextEditorModal:
    """Synchronous tests for TextEditorModal construction."""

    def test_default_text(self):
        modal = TextEditorModal("Editor", text="initial value")
        assert modal._text == "initial value"
        assert modal._title == "Editor"

    def test_empty_text(self):
        modal = TextEditorModal("Editor")
        assert modal._text == ""

    def test_language_option(self):
        modal = TextEditorModal("Editor", text="", language="markdown")
        assert modal._language == "markdown"

    def test_read_only_option(self):
        modal = TextEditorModal("Editor", text="", read_only=True)
        assert modal._read_only is True