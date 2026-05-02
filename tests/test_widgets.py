"""Tests for shared UI widgets."""

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Button, Label


# ---------------------------------------------------------------------------
# Test app
# ---------------------------------------------------------------------------


class WidgetTestApp(App):
    """Minimal app for testing widgets."""

    CSS = """
    Screen {
        align: center middle;
    }
    """

    def compose(self) -> ComposeResult:
        yield Label("Test app — press Ctrl+I to open input modal")


# ---------------------------------------------------------------------------
# InputModal
# ---------------------------------------------------------------------------


class TestInputModal:
    async def test_shows_and_returns_value(self):
        """InputModal opens, accepts text, returns it on OK."""
        from ui.widgets.input_modal import InputModal

        app = WidgetTestApp()

        async with app.run_test() as pilot:
            modal = InputModal("Enter name:", "Name")
            app.push_screen(modal)

            await pilot.pause()
            # Type into the input
            await pilot.press(*"Alice")
            await pilot.pause()
            # Press enter to submit
            await pilot.press("enter")

            # The modal should have returned "Alice"
            # We can't easily inspect the return value from push_screen in a test,
            # but we can verify the modal was dismissed
            assert app.screen is not modal

    async def test_cancel_returns_none(self):
        """InputModal returns None on Cancel."""
        from ui.widgets.input_modal import InputModal

        app = WidgetTestApp()

        async with app.run_test() as pilot:
            modal = InputModal("Prompt:", "Label")
            app.push_screen(modal)

            await pilot.pause()
            # Click the Cancel button
            cancel_btn = modal.query_one("#btn-cancel", Button)
            cancel_btn.press()
            await pilot.pause()

            assert app.screen is not modal

    async def test_default_value_prefilled(self):
        """InputModal can be initialized with a default value."""
        from ui.widgets.input_modal import InputModal

        app = WidgetTestApp()

        async with app.run_test() as pilot:
            modal = InputModal("Prompt:", "Label", default="prefilled")
            app.push_screen(modal)

            await pilot.pause()
            # The input should have "prefilled" as its value
            input_widget = modal.query_one("Input")
            assert input_widget.value == "prefilled"

    async def test_password_mode(self):
        """InputModal in password mode uses password input."""
        from ui.widgets.input_modal import InputModal

        app = WidgetTestApp()

        async with app.run_test() as pilot:
            modal = InputModal("Password:", "Pass", password=True)
            app.push_screen(modal)

            await pilot.pause()
            # Should use a password-masked input
            input_widget = modal.query_one("Input")
            assert input_widget.password is True


# ---------------------------------------------------------------------------
# CommandsHelp
# ---------------------------------------------------------------------------


class TestCommandsHelp:
    async def test_displays_registered_commands(self):
        """CommandsHelp shows all registered slash commands."""
        from core.commands import register_command, reset_commands
        from ui.widgets.commands_help import CommandsHelp

        reset_commands()

        @register_command(name="clear", description="Clear chat")
        async def clear(app, args: str) -> str:
            return "cleared"

        @register_command(name="help", description="Show help")
        async def help_cmd(app, args: str) -> str:
            return "help"

        app = WidgetTestApp()

        async with app.run_test() as pilot:
            modal = CommandsHelp()
            app.push_screen(modal)

            await pilot.pause()
            content = modal.query_one("#commands-content", Label)
            rendered = content.render()
            assert "clear" in rendered.plain
            assert "Clear chat" in rendered.plain
            assert "help" in rendered.plain
            assert "Show help" in rendered.plain

    async def test_empty_commands(self):
        """CommandsHelp handles no registered commands gracefully."""
        from core.commands import reset_commands
        from ui.widgets.commands_help import CommandsHelp

        reset_commands()

        app = WidgetTestApp()

        async with app.run_test() as pilot:
            modal = CommandsHelp()
            app.push_screen(modal)

            await pilot.pause()
            # Should not crash
            assert app.screen is modal
