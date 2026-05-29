"""Tests for ui.workspace.suggestion_overlay — AI suggestion overlay widget."""

from textual.app import App, ComposeResult
from textual.widget import Widget

from ui.workspace.suggestion_overlay import SuggestionOverlay


class _TestApp(App):
    """Minimal app for testing SuggestionOverlay in isolation."""

    CSS_PATH = []

    def compose(self) -> ComposeResult:
        yield SuggestionOverlay()


async def test_overlay_hidden_by_default():
    """Overlay starts hidden (no -visible class)."""
    app = _TestApp()
    async with app.run_test() as pilot:
        overlay = app.query_one(SuggestionOverlay)
        assert not overlay.is_showing
        assert overlay.suggestion is None


async def test_show_suggestion_makes_visible():
    """show_suggestion adds -visible class and stores the text."""
    app = _TestApp()
    async with app.run_test() as pilot:
        overlay = app.query_one(SuggestionOverlay)
        overlay.show_suggestion("foo()\nbar()")
        assert overlay.is_showing
        assert overlay.suggestion == "foo()\nbar()"


async def test_hide_suggestion_removes_visible():
    """hide_suggestion removes -visible class and clears the text."""
    app = _TestApp()
    async with app.run_test() as pilot:
        overlay = app.query_one(SuggestionOverlay)
        overlay.show_suggestion("foo()")
        assert overlay.is_showing

        overlay.hide_suggestion()
        assert not overlay.is_showing
        assert overlay.suggestion is None


async def test_show_single_line():
    """Single-line suggestion works."""
    app = _TestApp()
    async with app.run_test() as pilot:
        overlay = app.query_one(SuggestionOverlay)
        overlay.show_suggestion("foo()")
        assert overlay.is_showing
        assert overlay.suggestion == "foo()"


async def test_show_multiline():
    """Multi-line suggestion preserves newlines."""
    app = _TestApp()
    async with app.run_test() as pilot:
        overlay = app.query_one(SuggestionOverlay)
        text = "    arg2,\n    arg3):\n    return result"
        overlay.show_suggestion(text)
        assert overlay.is_showing
        assert overlay.suggestion == text


async def test_hide_when_already_hidden():
    """hide_suggestion on an already-hidden overlay is a no-op."""
    app = _TestApp()
    async with app.run_test() as pilot:
        overlay = app.query_one(SuggestionOverlay)
        overlay.hide_suggestion()  # should not raise
        assert not overlay.is_showing
        assert overlay.suggestion is None