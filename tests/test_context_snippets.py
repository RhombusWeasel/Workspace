"""Tests for core.context_snippets — inline suggestion context builder."""

from core.context_snippets import gather_context


# ---------------------------------------------------------------------------
# Basic functionality
# ---------------------------------------------------------------------------


class TestGatherContext:
    """Test gather_context builds correct context strings."""

    def test_simple_insertion(self):
        """CURSOR marker is inserted at the exact position."""
        code = "hello world\nsecond line"
        result = gather_context(code, cursor_row=0, cursor_col=5)
        assert "<CURSOR>" in result
        assert "hello<CURSOR> world" in result

    def test_cursor_at_line_start(self):
        """CURSOR at column 0 appears at the very start of the line."""
        code = "hello"
        result = gather_context(code, cursor_row=0, cursor_col=0)
        assert result == "<CURSOR>hello"

    def test_cursor_at_line_end(self):
        """CURSOR at end of line appears after all characters."""
        code = "hello"
        result = gather_context(code, cursor_row=0, cursor_col=5)
        assert result == "hello<CURSOR>"

    def test_empty_line(self):
        """CURSOR on an empty line is just the marker."""
        code = "\n\n"
        result = gather_context(code, cursor_row=1, cursor_col=0)
        # The cursor line (row 1) should just be the marker
        assert "<CURSOR>" in result
        # Verify the marker line has nothing else
        lines = result.split("\n")
        assert lines[1] == "<CURSOR>"

    def test_multiline_context(self):
        """Lines above and below the cursor are included."""
        code = "line0\nline1\nline2\nline3\nline4"
        result = gather_context(code, cursor_row=2, cursor_col=0)
        assert "line0" in result
        assert "line1" in result
        assert "<CURSOR>line2" in result
        assert "line3" in result
        assert "line4" in result

    def test_lines_above_limit(self):
        """Only lines_above lines are included before cursor."""
        code = "\n".join(f"line{i}" for i in range(100))
        result = gather_context(code, cursor_row=50, cursor_col=0, lines_above=5)
        # Should include line45..line50 (with cursor on line50)
        assert "line45" in result
        assert "line44" not in result

    def test_lines_below_limit(self):
        """Only lines_below lines are included after cursor."""
        code = "\n".join(f"line{i}" for i in range(100))
        result = gather_context(code, cursor_row=50, cursor_col=0, lines_below=5)
        # Should include line50..line55
        assert "line55" in result
        assert "line56" not in result

    def test_cursor_near_top(self):
        """When cursor is near the top, no lines_above are skipped."""
        code = "\n".join(f"line{i}" for i in range(20))
        result = gather_context(code, cursor_row=2, cursor_col=0, lines_above=10)
        assert "line0" in result

    def test_cursor_near_bottom(self):
        """When cursor is near the bottom, no lines_below are skipped."""
        code = "\n".join(f"line{i}" for i in range(20))
        result = gather_context(code, cursor_row=18, cursor_col=0, lines_below=10)
        assert "line19" in result

    def test_file_path_header(self):
        """File path is included as a header when provided."""
        code = "x = 1"
        result = gather_context(code, cursor_row=0, cursor_col=0, file_path="test.py")
        assert "File: test.py" in result

    def test_no_file_path_header(self):
        """No header when file_path is empty."""
        code = "x = 1"
        result = gather_context(code, cursor_row=0, cursor_col=0, file_path="")
        assert "File:" not in result

    def test_no_file_path_header_for_no_extension(self):
        """No header when file_path has no extension."""
        code = "x = 1"
        result = gather_context(code, cursor_row=0, cursor_col=0, file_path="Makefile")
        assert "File:" not in result

    def test_cursor_column_mid_token(self):
        """CURSOR in the middle of a word."""
        code = "foobar"
        result = gather_context(code, cursor_row=0, cursor_col=3)
        assert "foo<CURSOR>bar" in result

    def test_empty_file(self):
        """An empty file produces a CURSOR marker."""
        code = ""
        result = gather_context(code, cursor_row=0, cursor_col=0)
        assert "<CURSOR>" in result