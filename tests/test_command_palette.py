"""Tests for the CommandPalette widget."""

import pytest
from textual.app import App, ComposeResult

from core.commands import register_command, reset_commands
from ui.chat.command_palette import CommandPalette


# ---------------------------------------------------------------------------
# Test app
# ---------------------------------------------------------------------------


class PaletteTestApp(App):
    """Minimal app hosting a CommandPalette."""

    CSS = """
    CommandPalette {
        width: 60;
    }
    """

    def compose(self) -> ComposeResult:
        yield CommandPalette()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_commands():
    reset_commands()


async def _settle(pilot, n: int = 2) -> None:
    for _ in range(n):
        await pilot.pause()


def _register_test_commands():
    """Register three test commands and return their names."""

    @register_command(name="clear", description="Clear the chat display")
    async def clear(app, args: str) -> str:
        return "cleared"

    @register_command(name="help", description="Show available commands")
    async def help_cmd(app, args: str) -> str:
        return "help"

    @register_command(name="new", description="Start a new conversation")
    async def new_chat(app, args: str) -> str:
        return "new"

    return ["clear", "help", "new"]


# ---------------------------------------------------------------------------
# Tests — visibility
# ---------------------------------------------------------------------------


class TestCommandPaletteVisibility:
    async def test_starts_hidden(self):
        """CommandPalette starts hidden (no -visible class)."""
        async with PaletteTestApp().run_test() as pilot:
            await pilot.pause()
            palette = pilot.app.query_one(CommandPalette)
            assert not palette.is_visible

    async def test_show_makes_visible(self):
        """show() adds the -visible class."""
        async with PaletteTestApp().run_test() as pilot:
            await pilot.pause()
            palette = pilot.app.query_one(CommandPalette)
            palette.show()
            assert palette.is_visible

    async def test_hide_removes_visible(self):
        """hide() removes the -visible class."""
        async with PaletteTestApp().run_test() as pilot:
            await pilot.pause()
            palette = pilot.app.query_one(CommandPalette)
            palette.show()
            assert palette.is_visible
            palette.hide()
            assert not palette.is_visible


# ---------------------------------------------------------------------------
# Tests — filtering
# ------------------------------------------------------------------


class TestCommandPaletteFiltering:
    async def test_update_filter_with_slash_shows_all(self):
        """update_filter('/') shows all commands."""
        _register_test_commands()

        async with PaletteTestApp().run_test() as pilot:
            await pilot.pause()
            palette = pilot.app.query_one(CommandPalette)
            palette.update_filter("/")
            assert palette.is_visible
            # OptionList should show all commands
            from textual.widgets import OptionList
            ol = palette.query_one(OptionList)
            assert ol.option_count == 3

    async def test_update_filter_narrows_results(self):
        """update_filter('/he') shows only matching commands."""
        _register_test_commands()

        async with PaletteTestApp().run_test() as pilot:
            await pilot.pause()
            palette = pilot.app.query_one(CommandPalette)
            palette.update_filter("/he")
            assert palette.is_visible
            from textual.widgets import OptionList
            ol = palette.query_one(OptionList)
            assert ol.option_count == 1  # only "help"

    async def test_update_filter_no_match_hides_nothing(self):
        """update_filter with no matching commands shows empty list."""
        _register_test_commands()

        async with PaletteTestApp().run_test() as pilot:
            await pilot.pause()
            palette = pilot.app.query_one(CommandPalette)
            palette.update_filter("/xyz")
            assert palette.is_visible
            from textual.widgets import OptionList
            ol = palette.query_one(OptionList)
            assert ol.option_count == 0

    async def test_update_filter_without_slash_hides(self):
        """update_filter with non-slash text hides the palette."""
        _register_test_commands()

        async with PaletteTestApp().run_test() as pilot:
            await pilot.pause()
            palette = pilot.app.query_one(CommandPalette)
            palette.show()
            assert palette.is_visible
            palette.update_filter("hello")
            assert not palette.is_visible

    async def test_update_filter_case_insensitive(self):
        """Command filtering is case-insensitive."""
        _register_test_commands()

        async with PaletteTestApp().run_test() as pilot:
            await pilot.pause()
            palette = pilot.app.query_one(CommandPalette)
            palette.update_filter("/CL")
            assert palette.is_visible
            from textual.widgets import OptionList
            ol = palette.query_one(OptionList)
            assert ol.option_count == 1  # "clear" matches "CL"


# ---------------------------------------------------------------------------
# Tests — selection
# ---------------------------------------------------------------------------


class TestCommandPaletteSelection:
    async def test_select_highlighted_returns_command_name(self):
        """select_highlighted() returns the command name of the highlighted option."""
        _register_test_commands()

        async with PaletteTestApp().run_test() as pilot:
            await pilot.pause()
            palette = pilot.app.query_one(CommandPalette)
            palette.update_filter("/")
            await _settle(pilot)

            # First command should be highlighted by default
            name = palette.select_highlighted()
            assert name == "clear"  # alphabetically first

    async def test_select_highlighted_returns_none_when_hidden(self):
        """select_highlighted() returns None when palette is hidden."""
        async with PaletteTestApp().run_test() as pilot:
            await pilot.pause()
            palette = pilot.app.query_one(CommandPalette)
            assert palette.select_highlighted() is None

    async def test_move_highlight_changes_selection(self):
        """move_highlight() changes the highlighted item."""
        _register_test_commands()

        async with PaletteTestApp().run_test() as pilot:
            await pilot.pause()
            palette = pilot.app.query_one(CommandPalette)
            palette.update_filter("/")
            await _settle(pilot)

            # Move down one
            palette.move_highlight(1)
            name = palette.select_highlighted()
            assert name == "help"  # second item


# ---------------------------------------------------------------------------
# Tests — dynamic registration
# ---------------------------------------------------------------------------


class TestCommandPaletteDynamic:
    async def test_new_commands_appear_after_registration(self):
        """Commands registered after mount show up in the palette."""
        async with PaletteTestApp().run_test() as pilot:
            await pilot.pause()
            palette = pilot.app.query_one(CommandPalette)

            # No commands yet
            palette.update_filter("/")
            from textual.widgets import OptionList
            ol = palette.query_one(OptionList)
            assert ol.option_count == 0

            # Register a command
            @register_command(name="test", description="A test")
            async def test_cmd(app, args: str) -> str:
                return "test"

            # Refresh the palette
            palette.update_filter("/")
            assert ol.option_count == 1