"""Tests for the tool registry (core/tools.py)."""

import pytest


# ---------------------------------------------------------------------------
# Tool functions used in tests
# ---------------------------------------------------------------------------


def _echo(message: str, prefix: str = "") -> str:
    """Simple echo function for testing tool execution."""
    return f"{prefix}{message}"


def _add(a: int, b: int) -> int:
    return a + b


def _noop() -> None:
    return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


# We import the registry *after* defining helper functions, so they can be
# decorated at import time.  Each test uses reset() to start from a clean
# slate, then registers what it needs inline.
from core.tools import (  # noqa: E402
    register_tool,
    get_tools,
    execute_tool,
    disable_tool,
    enable_tool,
    disable_group,
    enable_group,
    reset,
)


_SIMPLE_PARAMS = {
    "type": "object",
    "properties": {
        "message": {"type": "string", "description": "The message to echo."},
        "prefix": {"type": "string", "description": "Optional prefix."},
    },
    "required": ["message"],
}

_ADD_PARAMS = {
    "type": "object",
    "properties": {
        "a": {"type": "integer", "description": "First number."},
        "b": {"type": "integer", "description": "Second number."},
    },
    "required": ["a", "b"],
}

_NOOP_PARAMS = {
    "type": "object",
    "properties": {},
}


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_decorator_registers_tool(self):
        """@register_tool() stores the function and its metadata."""
        reset()

        @register_tool(
            name="echo",
            tags=["test"],
            description="Echo back the message.",
            parameters=_SIMPLE_PARAMS,
        )
        def echo(message: str, prefix: str = "") -> str:
            return _echo(message, prefix)

        tools = get_tools()
        assert len(tools) == 1
        assert tools[0]["function"]["name"] == "echo"
        assert tools[0]["function"]["description"] == "Echo back the message."
        assert tools[0]["function"]["parameters"] == _SIMPLE_PARAMS

    def test_multiple_registrations(self):
        """Multiple registrations accumulate."""
        reset()

        @register_tool(
            name="echo",
            tags=["test"],
            description="Echo.",
            parameters=_SIMPLE_PARAMS,
        )
        def echo(message: str, prefix: str = "") -> str:
            return _echo(message, prefix)

        @register_tool(
            name="add",
            tags=["math"],
            description="Add two numbers.",
            parameters=_ADD_PARAMS,
        )
        def add(a: int, b: int) -> int:
            return _add(a, b)

        tools = get_tools()
        assert len(tools) == 2
        names = {t["function"]["name"] for t in tools}
        assert names == {"echo", "add"}

    def test_duplicate_name_raises(self):
        """Registering the same name twice raises an error."""
        reset()

        @register_tool(
            name="echo",
            tags=["test"],
            description="First.",
            parameters=_SIMPLE_PARAMS,
        )
        def echo1(message: str, prefix: str = "") -> str:
            return _echo(message, prefix)

        with pytest.raises(ValueError, match="already registered"):
            @register_tool(
                name="echo",
                tags=["test"],
                description="Second.",
                parameters=_SIMPLE_PARAMS,
            )
            def echo2(message: str, prefix: str = "") -> str:
                return _echo(message, prefix)

    def test_tags_default_to_empty_list(self):
        """If no tags are supplied, the tool has an empty tag list."""
        reset()

        @register_tool(
            name="tagless",
            description="No tags.",
            parameters=_NOOP_PARAMS,
        )
        def tagless() -> None:
            return None

        # Should still appear in unfiltered get_tools()
        tools = get_tools()
        assert len(tools) == 1
        assert tools[0]["function"]["name"] == "tagless"


# ---------------------------------------------------------------------------
# Tag filtering
# ---------------------------------------------------------------------------


class TestTagFiltering:
    def test_single_tag_filter(self):
        """get_tools('system') returns only tools with that tag."""
        reset()

        @register_tool(
            name="echo",
            tags=["system"],
            description="Echo.",
            parameters=_SIMPLE_PARAMS,
        )
        def echo(message: str, prefix: str = "") -> str:
            return _echo(message, prefix)

        @register_tool(
            name="add",
            tags=["math"],
            description="Add.",
            parameters=_ADD_PARAMS,
        )
        def add(a: int, b: int) -> int:
            return _add(a, b)

        sys_tools = get_tools("system")
        assert len(sys_tools) == 1
        assert sys_tools[0]["function"]["name"] == "echo"

    def test_multiple_tag_filter_union(self):
        """get_tools(['system', 'math']) returns tools matching any tag."""
        reset()

        @register_tool(
            name="echo",
            tags=["system"],
            description="Echo.",
            parameters=_SIMPLE_PARAMS,
        )
        def echo(message: str, prefix: str = "") -> str:
            return _echo(message, prefix)

        @register_tool(
            name="add",
            tags=["math"],
            description="Add.",
            parameters=_ADD_PARAMS,
        )
        def add(a: int, b: int) -> int:
            return _add(a, b)

        @register_tool(
            name="noop",
            tags=["admin"],
            description="No-op.",
            parameters=_NOOP_PARAMS,
        )
        def noop() -> None:
            return None

        tools = get_tools(["system", "math"])
        assert len(tools) == 2
        names = {t["function"]["name"] for t in tools}
        assert names == {"echo", "add"}

    def test_no_tags_returns_all(self):
        """get_tools() with no filter returns all enabled tools."""
        reset()

        @register_tool(
            name="echo",
            tags=["system"],
            description="Echo.",
            parameters=_SIMPLE_PARAMS,
        )
        def echo(message: str, prefix: str = "") -> str:
            return _echo(message, prefix)

        @register_tool(
            name="add",
            tags=["math"],
            description="Add.",
            parameters=_ADD_PARAMS,
        )
        def add(a: int, b: int) -> int:
            return _add(a, b)

        assert len(get_tools()) == 2

    def test_nonexistent_tag_returns_empty(self):
        """Filtering by a tag no tool has returns an empty list."""
        reset()

        @register_tool(
            name="echo",
            tags=["system"],
            description="Echo.",
            parameters=_SIMPLE_PARAMS,
        )
        def echo(message: str, prefix: str = "") -> str:
            return _echo(message, prefix)

        assert get_tools("nonexistent") == []


# ---------------------------------------------------------------------------
# Enable / disable individual tools
# ---------------------------------------------------------------------------


class TestEnableDisable:
    def test_disable_individual_tool_hides_it(self):
        """Disabling a tool removes it from get_tools()."""
        reset()

        @register_tool(
            name="echo",
            tags=["system"],
            description="Echo.",
            parameters=_SIMPLE_PARAMS,
        )
        def echo(message: str, prefix: str = "") -> str:
            return _echo(message, prefix)

        assert len(get_tools()) == 1
        disable_tool("echo")
        assert len(get_tools()) == 0

    def test_enable_tool_brings_it_back(self):
        """Re-enabling a disabled tool restores it."""
        reset()

        @register_tool(
            name="echo",
            tags=["system"],
            description="Echo.",
            parameters=_SIMPLE_PARAMS,
        )
        def echo(message: str, prefix: str = "") -> str:
            return _echo(message, prefix)

        disable_tool("echo")
        assert len(get_tools()) == 0
        enable_tool("echo")
        assert len(get_tools()) == 1

    def test_disable_unknown_tool_raises(self):
        """Disabling a tool that doesn't exist raises KeyError."""
        reset()
        with pytest.raises(KeyError, match="not registered"):
            disable_tool("nonexistent")

    def test_enable_unknown_tool_raises(self):
        """Enabling a tool that doesn't exist raises KeyError."""
        reset()
        with pytest.raises(KeyError, match="not registered"):
            enable_tool("nonexistent")

    def test_disabled_tool_still_executable(self):
        """Disabling hides from get_tools() but execute_tool() still works."""
        reset()

        @register_tool(
            name="echo",
            tags=["system"],
            description="Echo.",
            parameters=_SIMPLE_PARAMS,
        )
        def echo(message: str, prefix: str = "") -> str:
            return _echo(message, prefix)

        disable_tool("echo")
        result = execute_tool("echo", {"message": "hi"})
        assert result == "hi"


# ---------------------------------------------------------------------------
# Enable / disable tag groups
# ---------------------------------------------------------------------------


class TestGroupEnableDisable:
    def test_disable_group_hides_all_tagged_tools(self):
        """Disabling a group removes all tools with that tag from get_tools()."""
        reset()

        @register_tool(
            name="echo",
            tags=["system"],
            description="Echo.",
            parameters=_SIMPLE_PARAMS,
        )
        def echo(message: str, prefix: str = "") -> str:
            return _echo(message, prefix)

        @register_tool(
            name="noop",
            tags=["system", "admin"],
            description="No-op.",
            parameters=_NOOP_PARAMS,
        )
        def noop() -> None:
            return None

        disable_group("system")
        assert len(get_tools()) == 0  # both had 'system' tag

    def test_enable_group_restores_all_tagged_tools(self):
        """Re-enabling a group restores all tools with that tag."""
        reset()

        @register_tool(
            name="echo",
            tags=["system"],
            description="Echo.",
            parameters=_SIMPLE_PARAMS,
        )
        def echo(message: str, prefix: str = "") -> str:
            return _echo(message, prefix)

        @register_tool(
            name="noop",
            tags=["system"],
            description="No-op.",
            parameters=_NOOP_PARAMS,
        )
        def noop() -> None:
            return None

        disable_group("system")
        assert len(get_tools()) == 0
        enable_group("system")
        assert len(get_tools()) == 2

    def test_group_disable_only_affects_tagged(self):
        """Disabling a group does not affect tools with other tags."""
        reset()

        @register_tool(
            name="echo",
            tags=["system"],
            description="Echo.",
            parameters=_SIMPLE_PARAMS,
        )
        def echo(message: str, prefix: str = "") -> str:
            return _echo(message, prefix)

        @register_tool(
            name="add",
            tags=["math"],
            description="Add.",
            parameters=_ADD_PARAMS,
        )
        def add(a: int, b: int) -> int:
            return _add(a, b)

        disable_group("system")
        tools = get_tools()
        assert len(tools) == 1
        assert tools[0]["function"]["name"] == "add"

    def test_tool_disable_overrides_group_enable(self):
        """Individually disabling a tool keeps it hidden even if its group is enabled."""
        reset()

        @register_tool(
            name="echo",
            tags=["system"],
            description="Echo.",
            parameters=_SIMPLE_PARAMS,
        )
        def echo(message: str, prefix: str = "") -> str:
            return _echo(message, prefix)

        disable_tool("echo")
        disable_group("system")
        enable_group("system")
        # Group re-enabled, but tool still individually disabled
        assert len(get_tools()) == 0

    def test_tool_enable_does_not_override_group_disable(self):
        """Enabling a tool while its group is disabled keeps it hidden."""
        reset()

        @register_tool(
            name="echo",
            tags=["system"],
            description="Echo.",
            parameters=_SIMPLE_PARAMS,
        )
        def echo(message: str, prefix: str = "") -> str:
            return _echo(message, prefix)

        disable_group("system")
        enable_tool("echo")  # try to enable individually
        # Group is still disabled, so tool is still hidden
        assert len(get_tools()) == 0

    def test_disable_nonexistent_group_noop(self):
        """Disabling a group that has no tools is fine (no-op)."""
        reset()
        disable_group("nonexistent")  # should not raise
        assert len(get_tools()) == 0

    def test_enable_nonexistent_group_noop(self):
        """Enabling a group that was never disabled is fine (no-op)."""
        reset()
        enable_group("nonexistent")  # should not raise


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


class TestExecution:
    def test_execute_tool_calls_function(self):
        """execute_tool finds the function and calls it with the args dict."""
        reset()

        @register_tool(
            name="echo",
            tags=["test"],
            description="Echo.",
            parameters=_SIMPLE_PARAMS,
        )
        def echo(message: str, prefix: str = "") -> str:
            return _echo(message, prefix)

        result = execute_tool("echo", {"message": "hello", "prefix": ">> "})
        assert result == ">> hello"

    def test_execute_tool_missing_required_arg_raises(self):
        """Calling a tool without required args raises TypeError from the function."""
        reset()

        @register_tool(
            name="echo",
            tags=["test"],
            description="Echo.",
            parameters=_SIMPLE_PARAMS,
        )
        def echo(message: str, prefix: str = "") -> str:
            return _echo(message, prefix)

        with pytest.raises(TypeError):
            execute_tool("echo", {})

    def test_execute_unknown_tool_raises(self):
        """execute_tool with an unregistered name raises KeyError."""
        reset()
        with pytest.raises(KeyError, match="not registered"):
            execute_tool("nonexistent", {})

    def test_execute_disabled_tool(self):
        """execute_tool works even on disabled tools (LLM may still call them)."""
        reset()

        @register_tool(
            name="echo",
            tags=["test"],
            description="Echo.",
            parameters=_SIMPLE_PARAMS,
        )
        def echo(message: str, prefix: str = "") -> str:
            return _echo(message, prefix)

        disable_tool("echo")
        result = execute_tool("echo", {"message": "still works"})
        assert result == "still works"

    def test_execute_group_disabled_tool(self):
        """execute_tool works even when the tool's group is disabled."""
        reset()

        @register_tool(
            name="echo",
            tags=["system"],
            description="Echo.",
            parameters=_SIMPLE_PARAMS,
        )
        def echo(message: str, prefix: str = "") -> str:
            return _echo(message, prefix)

        disable_group("system")
        result = execute_tool("echo", {"message": "group disabled but works"})
        assert result == "group disabled but works"


# ---------------------------------------------------------------------------
# get_tools output format
# ---------------------------------------------------------------------------


class TestOutputFormat:
    def test_output_is_json_schema_format(self):
        """get_tools() returns the OpenAI/JSON Schema function-call format."""
        reset()

        @register_tool(
            name="add",
            tags=["math"],
            description="Add two integers.",
            parameters=_ADD_PARAMS,
        )
        def add(a: int, b: int) -> int:
            return _add(a, b)

        tools = get_tools()
        assert tools == [
            {
                "type": "function",
                "function": {
                    "name": "add",
                    "description": "Add two integers.",
                    "parameters": _ADD_PARAMS,
                },
            }
        ]


# ---------------------------------------------------------------------------
# reset()
# ---------------------------------------------------------------------------


class TestReset:
    def test_reset_clears_all_tools(self):
        reset()
        assert len(get_tools()) == 0

    def test_reset_clears_groups(self):
        """reset clears disabled groups and enabled state."""
        reset()

        @register_tool(
            name="echo",
            tags=["system"],
            description="Echo.",
            parameters=_SIMPLE_PARAMS,
        )
        def echo(message: str, prefix: str = "") -> str:
            return _echo(message, prefix)

        disable_group("system")
        disable_tool("echo")
        reset()

        # After reset, registry is completely empty
        assert len(get_tools()) == 0

    def test_reset_allows_re_registration(self):
        """After reset, previously-used names can be registered again."""
        reset()

        @register_tool(
            name="echo",
            tags=["test"],
            description="First.",
            parameters=_SIMPLE_PARAMS,
        )
        def echo1(message: str, prefix: str = "") -> str:
            return _echo(message, prefix)

        reset()

        # Should not raise
        @register_tool(
            name="echo",
            tags=["test"],
            description="Second.",
            parameters=_SIMPLE_PARAMS,
        )
        def echo2(message: str, prefix: str = "") -> str:
            return _echo(message, prefix) + "!"

        tools = get_tools()
        assert len(tools) == 1
        assert tools[0]["function"]["description"] == "Second."
        result = execute_tool("echo", {"message": "hi"})
        assert result == "hi!"


# ---------------------------------------------------------------------------
# Conftest-level fixture ensures clean state for every test module
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_registry():
    """Reset the tool registry before every test."""
    reset()
