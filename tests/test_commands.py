"""Tests for the slash-command system (core/commands.py)."""

import pytest


@pytest.fixture(autouse=True)
def _reset_commands():
    """Reset the command registry before every test."""
    from core.commands import reset_commands
    reset_commands()


# ---------------------------------------------------------------------------
# Command functions used in tests
# ---------------------------------------------------------------------------


async def _clear_cmd(app, args: str) -> str:
    return f"cleared: {args}"


async def _help_cmd(app, args: str) -> str:
    return "help text"


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_register_single_command(self):
        from core.commands import register_command, get_commands

        @register_command(name="clear", description="Clear the chat")
        async def clear(app, args: str) -> str:
            return await _clear_cmd(app, args)

        cmds = get_commands()
        assert "clear" in cmds
        assert cmds["clear"].name == "clear"
        assert cmds["clear"].description == "Clear the chat"
        assert cmds["clear"].handler is not None

    def test_register_multiple_commands(self):
        from core.commands import register_command, get_commands

        @register_command(name="clear", description="Clear")
        async def clear(app, args: str) -> str:
            return await _clear_cmd(app, args)

        @register_command(name="help", description="Help")
        async def help_cmd(app, args: str) -> str:
            return await _help_cmd(app, args)

        cmds = get_commands()
        assert len(cmds) == 2
        assert "clear" in cmds
        assert "help" in cmds

    def test_duplicate_name_raises(self):
        from core.commands import register_command

        @register_command(name="dup", description="First")
        async def first(app, args: str) -> str:
            return "first"

        with pytest.raises(ValueError, match="already registered"):
            @register_command(name="dup", description="Second")
            async def second(app, args: str) -> str:
                return "second"


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


class TestExecution:
    async def test_execute_registered_command(self):
        from core.commands import register_command, execute_command

        @register_command(name="greet", description="Greet")
        async def greet(app, args: str) -> str:
            return f"hello {args}"

        result = await execute_command("greet", None, "world")
        assert result == "hello world"

    async def test_execute_command_with_no_args(self):
        from core.commands import register_command, execute_command

        @register_command(name="status", description="Status")
        async def status(app, args: str) -> str:
            return "all good"

        result = await execute_command("status", None, "")
        assert result == "all good"

    async def test_execute_unknown_command_raises(self):
        from core.commands import execute_command

        with pytest.raises(KeyError, match="not registered"):
            await execute_command("nonexistent", None, "")


# ---------------------------------------------------------------------------
# reset()
# ---------------------------------------------------------------------------


class TestReset:
    def test_reset_clears_all(self):
        from core.commands import register_command, get_commands, reset_commands

        @register_command(name="x", description="X")
        async def x(app, args: str) -> str:
            return "x"

        assert len(get_commands()) == 1
        reset_commands()
        assert len(get_commands()) == 0


# ---------------------------------------------------------------------------
# Directory loading
# ---------------------------------------------------------------------------


class TestDirectoryLoading:
    def test_loads_command_modules_from_directory(self, tmp_path):
        """Commands are discovered from Python files in a directory."""
        from core.commands import load_commands_from_paths, get_commands, reset_commands

        # Write a command module
        cmd_dir = tmp_path / "cmd"
        cmd_dir.mkdir()
        (cmd_dir / "__init__.py").write_text("")
        (cmd_dir / "clear_cmd.py").write_text("""
from core.commands import register_command

@register_command(name="clear", description="Clear the chat")
async def clear(app, args: str) -> str:
    return f"clear result: {args}"
""")

        load_commands_from_paths([str(cmd_dir)])
        assert "clear" in get_commands()

    def test_skips_nonexistent_directories(self, tmp_path):
        from core.commands import load_commands_from_paths, get_commands

        load_commands_from_paths(["/tmp/does_not_exist_xyz"])
        # Should not raise
        assert get_commands() == {}


# ---------------------------------------------------------------------------
# Listing
# ---------------------------------------------------------------------------


class TestListing:
    def test_list_commands_returns_sorted_names(self):
        from core.commands import register_command, list_commands

        @register_command(name="beta", description="B")
        async def beta(app, args: str) -> str:
            return "b"

        @register_command(name="alpha", description="A")
        async def alpha(app, args: str) -> str:
            return "a"

        assert list_commands() == ["alpha", "beta"]