"""Tests for the read_file tool."""

import importlib
import os
import pytest

from core.tools import reset


def _load_tool():
    """Force-(re)load the read_file tool module to trigger @register_tool()."""
    mod = importlib.import_module("tools.read_file")
    if hasattr(mod, "read_file"):
        reset()
        importlib.reload(mod)


@pytest.fixture(autouse=True)
def _reset_tools():
    reset()
    yield
    reset()


class TestReadFile:
    def test_read_file_within_working_dir(self, tmp_path):
        """Reading a file within the working directory returns its contents."""
        f = tmp_path / "test.txt"
        f.write_text("hello world")

        _load_tool()
        from core.tools import execute_tool
        from context import AppContext

        ctx = AppContext(working_directory=str(tmp_path))
        result = execute_tool("read_file", {"path": "test.txt"}, ctx=ctx)
        assert "hello world" in result

    def test_read_file_absolute_within_wd(self, tmp_path):
        """An absolute path inside the working directory is allowed."""
        f = tmp_path / "nested" / "data.txt"
        f.parent.mkdir()
        f.write_text("nested data")

        _load_tool()
        from core.tools import execute_tool
        from context import AppContext

        ctx = AppContext(working_directory=str(tmp_path))
        result = execute_tool(
            "read_file",
            {"path": str(f)},
            ctx=ctx,
        )
        assert "nested data" in result

    def test_rejects_outside_working_dir(self, tmp_path):
        """Paths outside the working directory are rejected."""
        _load_tool()
        from core.tools import execute_tool
        from context import AppContext

        ctx = AppContext(working_directory=str(tmp_path / "sub"))
        (tmp_path / "sub").mkdir()
        result = execute_tool(
            "read_file",
            {"path": str(tmp_path / "outside.txt")},
            ctx=ctx,
        )
        assert "Access denied" in result

    def test_relative_escape_rejected(self, tmp_path):
        """Relative paths with '..' that escape are rejected."""
        sub = tmp_path / "sub"
        sub.mkdir()

        _load_tool()
        from core.tools import execute_tool
        from context import AppContext

        ctx = AppContext(working_directory=str(sub))
        result = execute_tool(
            "read_file",
            {"path": "../outside.txt"},
            ctx=ctx,
        )
        assert "Access denied" in result

    def test_rejects_directory(self, tmp_path):
        """Passing a directory path returns an error."""
        d = tmp_path / "mydir"
        d.mkdir()

        _load_tool()
        from core.tools import execute_tool
        from context import AppContext

        ctx = AppContext(working_directory=str(tmp_path))
        result = execute_tool("read_file", {"path": "mydir"}, ctx=ctx)
        assert "Not a regular file" in result

    def test_missing_file(self, tmp_path):
        """Non-existent files produce a clear error."""
        _load_tool()
        from core.tools import execute_tool
        from context import AppContext

        ctx = AppContext(working_directory=str(tmp_path))
        result = execute_tool(
            "read_file",
            {"path": "nope.txt"},
            ctx=ctx,
        )
        assert "Not a regular file" in result

    def test_defaults_to_cwd_when_no_ctx(self):
        """Without a context, the working directory defaults to os.getcwd()."""
        _load_tool()
        from core.tools import execute_tool

        result = execute_tool("read_file", {"path": "nonexistent_file_xyz.txt"})
        assert "Not a regular file" in result

    def test_binary_file_handled(self, tmp_path):
        """Binary files produce a clean error message."""
        f = tmp_path / "binary.dat"
        f.write_bytes(b"\x00\x01\x02\xff\xfe")

        _load_tool()
        from core.tools import execute_tool
        from context import AppContext

        ctx = AppContext(working_directory=str(tmp_path))
        result = execute_tool("read_file", {"path": "binary.dat"}, ctx=ctx)
        assert "Cannot read" in result
        assert "binary" in result.lower()

    def test_large_file_rejected(self, tmp_path):
        """Files larger than MAX_BYTES are rejected."""
        f = tmp_path / "large.txt"
        f.write_text("x" * (257 * 1024))

        _load_tool()
        from core.tools import execute_tool
        from context import AppContext

        ctx = AppContext(working_directory=str(tmp_path))
        result = execute_tool("read_file", {"path": "large.txt"}, ctx=ctx)
        assert "too large" in result.lower()
