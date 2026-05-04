"""Tests for the run_command tool."""

import importlib
import asyncio
import pytest

from core.tools import reset


def _load_tool():
    """Force-(re)load the run_command tool module to trigger @register_tool()."""
    mod = importlib.import_module("tools.run_command")
    if hasattr(mod, "run_command"):
        reset()
        importlib.reload(mod)


@pytest.fixture(autouse=True)
def _reset_tools():
    reset()
    yield
    reset()


class TestRunCommandValidation:
    """Tests that don't need a running app (ctx.app is None)."""

    def test_no_app_context_returns_error(self, tmp_path):
        """Without a running app, run_command returns an error."""
        _load_tool()
        from core.tools import execute_tool
        from context import AppContext

        ctx = AppContext(working_directory=str(tmp_path))
        result = execute_tool(
            "run_command",
            {"command": "echo hello"},
            ctx=ctx,
        )
        text = asyncio.run(result)
        assert "no application context" in text.lower()
