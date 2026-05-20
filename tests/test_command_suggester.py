"""Tests for the CommandSuggester."""

import pytest

from plugins.chat.command_suggester import CommandSuggester
from core.commands import register_command, reset_commands


@pytest.fixture(autouse=True)
def _reset_commands():
    """Reset the command registry before every test."""
    reset_commands()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCommandSuggester:
    async def test_no_suggestion_for_normal_text(self):
        """Text that doesn't start with / gets no suggestion."""
        s = CommandSuggester()
        result = await s.get_suggestion("hello world")
        assert result is None

    async def test_no_suggestion_for_empty_string(self):
        """Empty string gets no suggestion."""
        s = CommandSuggester()
        result = await s.get_suggestion("")
        assert result is None

    async def test_suggestion_for_slash_prefix(self):
        """Text starting with / suggests a matching command."""
        @register_command(name="help", description="Show help")
        async def help_cmd(app, args: str) -> str:
            return "help"

        s = CommandSuggester()
        result = await s.get_suggestion("/h")
        assert result == "/help"

    async def test_suggestion_for_exact_command_name(self):
        """Typing the exact /command name suggests it back (useful for Tab to confirm)."""
        @register_command(name="clear", description="Clear")
        async def clear(app, args: str) -> str:
            return "cleared"

        s = CommandSuggester()
        result = await s.get_suggestion("/clear")
        assert result == "/clear"

    async def test_no_suggestion_for_non_matching_prefix(self):
        """If no command matches the prefix, no suggestion."""
        @register_command(name="help", description="Help")
        async def help_cmd(app, args: str) -> str:
            return "help"

        s = CommandSuggester()
        result = await s.get_suggestion("/xyz")
        assert result is None

    async def test_bare_slash_suggests_first_command(self):
        """Just '/' alone suggests the first command alphabetically."""
        @register_command(name="new", description="New chat")
        async def new_chat(app, args: str) -> str:
            return "new"

        @register_command(name="clear", description="Clear")
        async def clear(app, args: str) -> str:
            return "cleared"

        s = CommandSuggester()
        result = await s.get_suggestion("/")
        # Should suggest the alphabetically first command
        assert result == "/clear"

    async def test_bare_slash_no_commands_returns_none(self):
        """Just '/' with no registered commands returns None."""
        s = CommandSuggester()
        result = await s.get_suggestion("/")
        assert result is None

    async def test_suggestions_dynamic_after_registration(self):
        """Suggestions update when new commands are registered (no caching)."""
        s = CommandSuggester()

        # No commands yet
        result = await s.get_suggestion("/he")
        assert result is None

        # Register a command
        @register_command(name="help", description="Help")
        async def help_cmd(app, args: str) -> str:
            return "help"

        # Now it should be suggested (use_cache=False)
        result = await s.get_suggestion("/he")
        assert result == "/help"

    async def test_multiple_commands_suggests_first_match(self):
        """With multiple matching commands, the first alphabetically is suggested."""
        @register_command(name="help", description="Help")
        async def help_cmd(app, args: str) -> str:
            return "help"

        @register_command(name="history", description="Chat history")
        async def history(app, args: str) -> str:
            return "history"

        s = CommandSuggester()
        result = await s.get_suggestion("/h")
        # "help" comes before "history" alphabetically
        assert result == "/help"

    async def test_case_insensitive_matching(self):
        """Command matching is case-insensitive.

        The Suggester base class casefolds the input value when
        case_sensitive=False.  Our implementation also casefolds
        command names, so /H matches /Help.
        """
        @register_command(name="Help", description="Help")
        async def help_cmd(app, args: str) -> str:
            return "help"

        s = CommandSuggester()
        # The base class casefolds the value before passing to get_suggestion
        result = await s.get_suggestion("/H")
        assert result == "/Help"

        # Also works with lowercase
        result = await s.get_suggestion("/h")
        assert result == "/Help"