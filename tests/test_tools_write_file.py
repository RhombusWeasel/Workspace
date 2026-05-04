"""Tests for the write_file tool."""

import importlib
import os
import asyncio
import pytest

from core.tools import reset


def _load_tool():
    """Force-(re)load the write_file tool module to trigger @register_tool()."""
    mod = importlib.import_module("tools.write_file")
    if hasattr(mod, "write_file"):
        reset()
        importlib.reload(mod)


@pytest.fixture(autouse=True)
def _reset_tools():
    reset()
    yield
    reset()


class TestWriteFileValidation:
    """Tests that don't need a running app (ctx.app is None)."""

    def test_no_app_context_returns_error(self, tmp_path):
        """Without a running app, write_file returns an error."""
        _load_tool()
        from core.tools import execute_tool
        from context import AppContext

        ctx = AppContext(working_directory=str(tmp_path))
        result = execute_tool(
            "write_file",
            {"path": "test.txt", "content": "hello"},
            ctx=ctx,
        )
        text = asyncio.run(result)
        assert "no application context" in text.lower()

    def test_rejects_outside_working_dir(self, tmp_path):
        """Paths outside the working directory are rejected before app check."""
        _load_tool()
        from core.tools import execute_tool
        from context import AppContext

        sub = tmp_path / "sub"
        sub.mkdir()
        ctx = AppContext(working_directory=str(sub))
        result = execute_tool(
            "write_file",
            {"path": str(tmp_path / "outside.txt"), "content": "x"},
            ctx=ctx,
        )
        text = asyncio.run(result)
        assert "Access denied" in text

    def test_relative_escape_rejected(self, tmp_path):
        """'..' escapes are rejected."""
        _load_tool()
        from core.tools import execute_tool
        from context import AppContext

        sub = tmp_path / "sub"
        sub.mkdir()
        ctx = AppContext(working_directory=str(sub))
        result = execute_tool(
            "write_file",
            {"path": "../outside.txt", "content": "x"},
            ctx=ctx,
        )
        text = asyncio.run(result)
        assert "Access denied" in text
