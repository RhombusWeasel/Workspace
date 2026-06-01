"""Tests for the read_file tool — pagination, truncation, boundary checks."""

import os
import tempfile

import pytest

from tools.read_file import read_file


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_dir():
    """Create a temporary working directory with test files."""
    with tempfile.TemporaryDirectory() as td:
        # Small file — 5 lines.
        small = os.path.join(td, "small.txt")
        with open(small, "w") as f:
            f.write("line one\nline two\nline three\nline four\nline five\n")

        # Medium file — exactly _MAX_OUTPUT_LINES lines.
        from tools.read_file import _MAX_OUTPUT_LINES
        medium = os.path.join(td, "medium.txt")
        with open(medium, "w") as f:
            for i in range(1, _MAX_OUTPUT_LINES + 1):
                f.write(f"line {i}\n")

        # Large file — exceeds _MAX_OUTPUT_LINES.
        large = os.path.join(td, "large.txt")
        total_lines = _MAX_OUTPUT_LINES + 500
        with open(large, "w") as f:
            for i in range(1, total_lines + 1):
                f.write(f"line {i}\n")

        # Binary file (non-UTF-8).
        binary = os.path.join(td, "binary.bin")
        with open(binary, "wb") as f:
            f.write(b"\x80\x81\x82\xff")

        yield td


class FakeCtx:
    """Minimal AppContext with just working_directory."""

    def __init__(self, wd: str):
        self.working_directory = wd


# ---------------------------------------------------------------------------
# Basic reading
# ---------------------------------------------------------------------------

class TestBasicRead:
    """Test reading a full small file (no offset/limit)."""

    def test_read_small_file(self, tmp_dir):
        ctx = FakeCtx(tmp_dir)
        result = read_file("small.txt", ctx=ctx)
        assert "line one" in result
        assert "line five" in result
        assert result.count("\n") == 5  # 5 lines, each ending with \n

    def test_read_file_absolute_path(self, tmp_dir):
        ctx = FakeCtx(tmp_dir)
        result = read_file(os.path.join(tmp_dir, "small.txt"), ctx=ctx)
        assert "line one" in result

    def test_path_outside_working_directory(self, tmp_dir):
        ctx = FakeCtx(tmp_dir)
        result = read_file("/etc/passwd", ctx=ctx)
        assert "Access denied" in result

    def test_nonexistent_file(self, tmp_dir):
        ctx = FakeCtx(tmp_dir)
        result = read_file("no_such_file.txt", ctx=ctx)
        assert "Not a regular file" in result

    def test_binary_file(self, tmp_dir):
        ctx = FakeCtx(tmp_dir)
        result = read_file("binary.bin", ctx=ctx)
        assert "UTF-8" in result

    def test_no_ctx_uses_cwd(self, tmp_dir):
        # read_file with no ctx should use os.getcwd()
        # Just verify it doesn't crash — actual reading depends on cwd.
        result = read_file("nonexistent_for_sure.txt")
        assert "Not a regular file" in result


# ---------------------------------------------------------------------------
# Offset parameter
# ---------------------------------------------------------------------------

class TestOffset:
    """Test the offset (1-indexed start line) parameter."""

    def test_offset_from_middle(self, tmp_dir):
        ctx = FakeCtx(tmp_dir)
        result = read_file("small.txt", offset=3, ctx=ctx)
        # Line 3 onwards, with line numbers since offset is set
        assert "3\tline three" in result
        assert "line one" not in result

    def test_offset_1_reads_from_start(self, tmp_dir):
        ctx = FakeCtx(tmp_dir)
        result = read_file("small.txt", offset=1, ctx=ctx)
        assert "1\tline one" in result

    def test_offset_at_last_line(self, tmp_dir):
        ctx = FakeCtx(tmp_dir)
        result = read_file("small.txt", offset=5, ctx=ctx)
        assert "5\tline five" in result

    def test_offset_beyond_file_length(self, tmp_dir):
        ctx = FakeCtx(tmp_dir)
        result = read_file("small.txt", offset=100, ctx=ctx)
        assert "exceeds file length" in result
        assert "5 lines" in result

    def test_invalid_offset_zero(self, tmp_dir):
        ctx = FakeCtx(tmp_dir)
        result = read_file("small.txt", offset=0, ctx=ctx)
        assert "Invalid offset" in result

    def test_invalid_offset_negative(self, tmp_dir):
        ctx = FakeCtx(tmp_dir)
        result = read_file("small.txt", offset=-1, ctx=ctx)
        assert "Invalid offset" in result


# ---------------------------------------------------------------------------
# Limit parameter
# ---------------------------------------------------------------------------

class TestLimit:
    """Test the limit (max lines) parameter."""

    def test_limit_2(self, tmp_dir):
        ctx = FakeCtx(tmp_dir)
        result = read_file("small.txt", limit=2, ctx=ctx)
        # With limit set, line numbers are shown
        assert "1\tline one" in result
        assert "2\tline two" in result
        # Should NOT contain line 3
        assert "line three" not in result

    def test_offset_and_limit(self, tmp_dir):
        ctx = FakeCtx(tmp_dir)
        result = read_file("small.txt", offset=2, limit=2, ctx=ctx)
        # Lines 2-3, with line numbers
        assert "2\tline two" in result
        assert "3\tline three" in result
        assert "line one" not in result
        assert "line four" not in result

    def test_limit_larger_than_file(self, tmp_dir):
        ctx = FakeCtx(tmp_dir)
        result = read_file("small.txt", limit=100, ctx=ctx)
        assert "1\tline one" in result
        assert "5\tline five" in result

    def test_invalid_limit_zero(self, tmp_dir):
        ctx = FakeCtx(tmp_dir)
        result = read_file("small.txt", limit=0, ctx=ctx)
        assert "Invalid limit" in result

    def test_invalid_limit_negative(self, tmp_dir):
        ctx = FakeCtx(tmp_dir)
        result = read_file("small.txt", limit=-5, ctx=ctx)
        assert "Invalid limit" in result


# ---------------------------------------------------------------------------
# Truncation (no offset/limit on large files)
# ---------------------------------------------------------------------------

class TestTruncation:
    """Test auto-truncation when no offset/limit is given for large files."""

    def test_large_file_truncated_without_offset_limit(self, tmp_dir):
        from tools.read_file import _MAX_OUTPUT_LINES
        ctx = FakeCtx(tmp_dir)
        result = read_file("large.txt", ctx=ctx)
        # Should contain truncation notice
        assert "showing lines" in result
        assert "Use offset=" in result
        # Should NOT contain lines beyond the truncation point
        # The large file has _MAX_OUTPUT_LINES + 500 lines
        assert f"line {_MAX_OUTPUT_LINES + 500}" not in result

    def test_large_file_can_be_read_in_chunks(self, tmp_dir):
        ctx = FakeCtx(tmp_dir)
        # Read the first chunk
        result1 = read_file("large.txt", offset=1, limit=500, ctx=ctx)
        assert "1\tline 1" in result1
        # Still shows a truncation notice because file has more lines
        assert "Use offset=" in result1

        # Read a middle chunk
        result2 = read_file("large.txt", offset=500, limit=500, ctx=ctx)
        assert "500\tline 500" in result2

    def test_medium_file_exact_limit_no_truncation(self, tmp_dir):
        from tools.read_file import _MAX_OUTPUT_LINES
        ctx = FakeCtx(tmp_dir)
        result = read_file("medium.txt", ctx=ctx)
        # File is exactly _MAX_OUTPUT_LINES lines — no truncation
        assert no_truncation_notice(result)

    def test_large_file_with_explicit_limit_still_shows_continuation(self, tmp_dir):
        ctx = FakeCtx(tmp_dir)
        # When limit is specified but file has more lines, still show
        # a continuation hint (tells the agent how many total lines
        # and where to continue reading).
        result = read_file("large.txt", limit=100, ctx=ctx)
        assert "1\tline 1" in result
        assert "100\tline 100" in result
        assert "showing lines 1-100" in result
        assert "Use offset=101" in result


# ---------------------------------------------------------------------------
# Line numbering
# ---------------------------------------------------------------------------

class TestLineNumbers:
    """Test that line numbers are shown only when offset/limit are used."""

    def test_no_line_numbers_by_default_small_file(self, tmp_dir):
        ctx = FakeCtx(tmp_dir)
        result = read_file("small.txt", ctx=ctx)
        # No line numbers — just raw content
        assert "line one\n" in result
        # Should NOT have tab-separated line numbers
        assert "\tline one" not in result

    def test_line_numbers_with_offset(self, tmp_dir):
        ctx = FakeCtx(tmp_dir)
        result = read_file("small.txt", offset=1, ctx=ctx)
        assert "1\tline one" in result

    def test_line_numbers_with_limit(self, tmp_dir):
        ctx = FakeCtx(tmp_dir)
        result = read_file("small.txt", limit=5, ctx=ctx)
        assert "1\tline one" in result

    def test_line_numbers_with_both(self, tmp_dir):
        ctx = FakeCtx(tmp_dir)
        result = read_file("small.txt", offset=2, limit=3, ctx=ctx)
        assert "2\tline two" in result
        assert "3\tline three" in result
        assert "4\tline four" in result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def no_truncation_notice(text: str) -> bool:
    """Return True if text does NOT contain a truncation notice."""
    return "showing lines" not in text and "Use offset=" not in text