"""Tests for the edit_file tool — search/replace edits, uniqueness checks, diffs."""

import os
import tempfile

import pytest

from tools.edit_file import _find_occurrences, _count_occurrences, _apply_edits


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_dir():
    """Create a temporary working directory with test files."""
    with tempfile.TemporaryDirectory() as td:
        # Simple 3-line file.
        simple = os.path.join(td, "simple.txt")
        with open(simple, "w") as f:
            f.write("alpha\nbeta\ngamma\n")

        # File with duplicate lines.
        dupes = os.path.join(td, "dupes.txt")
        with open(dupes, "w") as f:
            f.write("hello\nhello\nworld\nhello\n")

        # Multi-line content for testing multiline search.
        multi = os.path.join(td, "multi.txt")
        with open(multi, "w") as f:
            f.write("function foo():\n    return 42\n\nfunction bar():\n    return 99\n")

        yield td


class FakeCtx:
    """Minimal AppContext with just working_directory and no app."""

    def __init__(self, wd: str):
        self.working_directory = wd
        self.app = None
        self.config = None


class FakeApp:
    """Minimal app that auto-confirms any modal."""

    async def push_screen_wait(self, modal):
        return True


class AutoConfirmCtx:
    """Context that auto-confirms edits."""

    def __init__(self, wd: str):
        self.working_directory = wd
        self.app = FakeApp()
        self.config = None


class FakeConfig:
    """Minimal config stub for testing yolo_mode."""

    def __init__(self, yolo_mode: bool = False):
        self._yolo_mode = yolo_mode

    def get(self, key: str, default=None):
        if key == "session.yolo_mode":
            return self._yolo_mode
        return default


class YoloCtx:
    """Context with yolo_mode enabled — no modal needed."""

    def __init__(self, wd: str):
        self.working_directory = wd
        self.app = None  # not needed in yolo mode
        self.config = FakeConfig(yolo_mode=True)


class RejectApp:
    """App that rejects any modal."""

    async def push_screen_wait(self, modal):
        return None


class CancelCtx:
    """Context that cancels edits."""

    def __init__(self, wd: str):
        self.working_directory = wd
        self.app = RejectApp()
        self.config = None


# ---------------------------------------------------------------------------
# _find_occurrences
# ---------------------------------------------------------------------------

class TestFindOccurrences:
    """Test the helper that finds line numbers of search strings."""

    def test_unique_match(self):
        text = "alpha\nbeta\ngamma\n"
        hits = _find_occurrences(text, "beta")
        assert hits == [2]

    def test_multiple_matches(self):
        text = "hello\nhello\nworld\nhello\n"
        hits = _find_occurrences(text, "hello")
        assert hits == [1, 2, 4]

    def test_no_match(self):
        text = "alpha\nbeta\ngamma\n"
        hits = _find_occurrences(text, "delta")
        assert hits == []

    def test_multiline_search(self):
        text = "function foo():\n    return 42\n\nfunction bar():\n    return 99\n"
        hits = _find_occurrences(text, "function foo():\n    return 42")
        assert hits == [1]

    def test_empty_search(self):
        # Empty search should find no occurrences
        # (we reject empty searches at a higher level)
        text = "alpha\nbeta\n"
        hits = _find_occurrences(text, "")
        # Empty string is found at every boundary — many hits
        assert len(hits) > 0

    def test_search_not_found(self):
        text = "alpha\nbeta\n"
        hits = _find_occurrences(text, "gamma")
        assert hits == []

    def test_line_number_is_correct_for_mid_file(self):
        text = "line1\nline2\nline3\nline4\n"
        hits = _find_occurrences(text, "line3")
        assert hits == [3]

    def test_match_at_end_of_file(self):
        text = "alpha\nbeta\n"
        hits = _find_occurrences(text, "beta")
        assert hits == [2]


# ---------------------------------------------------------------------------
# _count_occurrences
# ---------------------------------------------------------------------------

class TestCountOccurrences:
    """Test the helper that counts non-overlapping occurrences."""

    def test_unique(self):
        assert _count_occurrences("alpha\nbeta\ngamma\n", "beta") == 1

    def test_multiple(self):
        assert _count_occurrences("hello\nhello\nworld\nhello\n", "hello") == 3

    def test_none(self):
        assert _count_occurrences("alpha\nbeta\n", "gamma") == 0

    def test_empty_search(self):
        # Empty search is guarded — returns 0
        assert _count_occurrences("abc", "") == 0
# ---------------------------------------------------------------------------
# _apply_edits
# ---------------------------------------------------------------------------

class TestApplyEdits:
    """Test the core edit application logic (no user confirmation)."""

    def test_single_edit(self):
        content = "alpha\nbeta\ngamma\n"
        edits = [{"search": "beta", "replace": "BETA"}]
        new_content, diff = _apply_edits(content, edits)
        assert new_content == "alpha\nBETA\ngamma\n"
        assert "BETA" in diff
        assert "-beta" in diff

    def test_multiple_edits_sequential(self):
        content = "alpha\nbeta\ngamma\n"
        edits = [
            {"search": "alpha", "replace": "ALPHA"},
            {"search": "beta", "replace": "BETA"},
        ]
        new_content, diff = _apply_edits(content, edits)
        assert new_content == "ALPHA\nBETA\ngamma\n"

    def test_edit_sees_prior_result(self):
        # Second edit modifies text introduced by the first.
        content = "hello world\n"
        edits = [
            {"search": "hello", "replace": "goodbye"},
            {"search": "goodbye world", "replace": "farewell earth"},
        ]
        new_content, diff = _apply_edits(content, edits)
        assert new_content == "farewell earth\n"

    def test_non_unique_search_fails(self):
        content = "hello\nhello\nworld\nhello\n"
        edits = [{"search": "hello", "replace": "hi"}]
        result = _apply_edits(content, edits)
        # First element is None on error
        assert result[0] is None
        assert "not unique" in result[1]
        assert "3 occurrences" in result[1]
        # Should include line numbers
        assert "lines" in result[1].lower() or "1" in result[1]

    def test_not_found_fails(self):
        content = "alpha\nbeta\ngamma\n"
        edits = [{"search": "delta", "replace": "DELTA"}]
        result = _apply_edits(content, edits)
        assert result[0] is None
        assert "not found" in result[1]

    def test_empty_search_fails(self):
        content = "alpha\nbeta\n"
        edits = [{"search": "", "replace": "X"}]
        result = _apply_edits(content, edits)
        assert result[0] is None
        assert "empty" in result[1].lower()

    def test_no_changes_when_search_equals_replace(self):
        content = "alpha\nbeta\n"
        edits = [{"search": "alpha", "replace": "alpha"}]
        new_content, diff = _apply_edits(content, edits)
        # Content is identical — no meaningful diff
        assert new_content == content

    def test_multiline_replacement(self):
        content = "function foo():\n    return 42\n\nfunction bar():\n    return 99\n"
        edits = [{"search": "function foo():\n    return 42", "replace": "def foo() -> int:\n    return 42"}]
        new_content, diff = _apply_edits(content, edits)
        assert "def foo() -> int:" in new_content
        assert "function foo():" not in new_content
        # Second function should be untouched
        assert "function bar():" in new_content

    def test_second_edit_not_unique_due_to_first(self):
        # After first edit, second search string becomes non-unique
        content = "foo\nbar\nbaz\n"
        edits = [
            {"search": "foo", "replace": "baz"},  # now "baz" appears twice
            {"search": "baz", "replace": "BAZ"},  # not unique!
        ]
        result = _apply_edits(content, edits)
        assert result[0] is None
        assert "not unique" in result[1]

    def test_error_includes_edit_number(self):
        content = "alpha\nbeta\ngamma\n"
        edits = [
            {"search": "alpha", "replace": "ALPHA"},  # ok
            {"search": "missing", "replace": "FOUND"},  # not found
        ]
        result = _apply_edits(content, edits)
        assert result[0] is None
        assert "Edit 2" in result[1]

    def test_error_includes_line_numbers(self):
        content = "x\ny\nx\nz\nx\n"
        edits = [{"search": "x", "replace": "X"}]
        result = _apply_edits(content, edits)
        assert result[0] is None
        # Should mention 3 occurrences and line numbers
        assert "3 occurrences" in result[1]
        assert "1" in result[1]  # line 1
        assert "3" in result[1]  # line 3
        assert "5" in result[1]  # line 5


# ---------------------------------------------------------------------------
# edit_file tool (async, with confirmation)
# ---------------------------------------------------------------------------

class TestEditFileTool:
    """Test the full edit_file tool including path checks and confirmation."""

    @pytest.mark.asyncio
    async def test_simple_edit_confirmed(self, tmp_dir):
        from tools.edit_file import edit_file

        ctx = AutoConfirmCtx(tmp_dir)
        result = await edit_file(
            "simple.txt",
            [{"search": "beta", "replace": "BETA"}],
            ctx=ctx,
        )
        assert "Applied 1 edit" in result

        # Verify file was actually changed
        with open(os.path.join(tmp_dir, "simple.txt")) as f:
            assert f.read() == "alpha\nBETA\ngamma\n"

    @pytest.mark.asyncio
    async def test_edit_cancelled_by_user(self, tmp_dir):
        from tools.edit_file import edit_file

        ctx = CancelCtx(tmp_dir)
        result = await edit_file(
            "simple.txt",
            [{"search": "beta", "replace": "BETA"}],
            ctx=ctx,
        )
        assert "cancelled" in result

        # Verify file was NOT changed
        with open(os.path.join(tmp_dir, "simple.txt")) as f:
            assert f.read() == "alpha\nbeta\ngamma\n"

    @pytest.mark.asyncio
    async def test_path_outside_working_directory(self, tmp_dir):
        from tools.edit_file import edit_file

        ctx = AutoConfirmCtx(tmp_dir)
        result = await edit_file(
            "/etc/passwd",
            [{"search": "root", "replace": "admin"}],
            ctx=ctx,
        )
        assert "Access denied" in result

    @pytest.mark.asyncio
    async def test_nonexistent_file(self, tmp_dir):
        from tools.edit_file import edit_file

        ctx = AutoConfirmCtx(tmp_dir)
        result = await edit_file(
            "nonexistent.txt",
            [{"search": "foo", "replace": "bar"}],
            ctx=ctx,
        )
        assert "not an existing regular file" in result

    @pytest.mark.asyncio
    async def test_no_context(self, tmp_dir):
        from tools.edit_file import edit_file

        result = await edit_file(
            "simple.txt",
            [{"search": "beta", "replace": "BETA"}],
            ctx=None,
        )
        assert "no context" in result

    @pytest.mark.asyncio
    async def test_non_unique_search_returns_error(self, tmp_dir):
        from tools.edit_file import edit_file

        ctx = AutoConfirmCtx(tmp_dir)
        result = await edit_file(
            "dupes.txt",
            [{"search": "hello", "replace": "hi"}],
            ctx=ctx,
        )
        assert "not unique" in result
        assert "3 occurrences" in result

        # Verify file was NOT changed
        with open(os.path.join(tmp_dir, "dupes.txt")) as f:
            content = f.read()
        assert content == "hello\nhello\nworld\nhello\n"

    @pytest.mark.asyncio
    async def test_search_not_found_returns_error(self, tmp_dir):
        from tools.edit_file import edit_file

        ctx = AutoConfirmCtx(tmp_dir)
        result = await edit_file(
            "simple.txt",
            [{"search": "missing", "replace": "found"}],
            ctx=ctx,
        )
        assert "not found" in result

    @pytest.mark.asyncio
    async def test_empty_search_returns_error(self, tmp_dir):
        from tools.edit_file import edit_file

        ctx = AutoConfirmCtx(tmp_dir)
        result = await edit_file(
            "simple.txt",
            [{"search": "", "replace": "X"}],
            ctx=ctx,
        )
        assert "empty" in result.lower()

    @pytest.mark.asyncio
    async def test_identical_search_and_replace(self, tmp_dir):
        from tools.edit_file import edit_file

        ctx = AutoConfirmCtx(tmp_dir)
        result = await edit_file(
            "simple.txt",
            [{"search": "beta", "replace": "beta"}],
            ctx=ctx,
        )
        assert "No changes" in result

    @pytest.mark.asyncio
    async def test_multiple_edits_applied(self, tmp_dir):
        from tools.edit_file import edit_file

        ctx = AutoConfirmCtx(tmp_dir)
        result = await edit_file(
            "simple.txt",
            [
                {"search": "alpha", "replace": "ALPHA"},
                {"search": "gamma", "replace": "GAMMA"},
            ],
            ctx=ctx,
        )
        assert "Applied 2 edits" in result

        with open(os.path.join(tmp_dir, "simple.txt")) as f:
            assert f.read() == "ALPHA\nbeta\nGAMMA\n"

    @pytest.mark.asyncio
    async def test_absolute_path_inside_working_dir(self, tmp_dir):
        from tools.edit_file import edit_file

        ctx = AutoConfirmCtx(tmp_dir)
        abs_path = os.path.join(tmp_dir, "simple.txt")
        result = await edit_file(
            abs_path,
            [{"search": "beta", "replace": "BETA"}],
            ctx=ctx,
        )
        assert "Applied 1 edit" in result

    @pytest.mark.asyncio
    async def test_edit_preserves_other_content(self, tmp_dir):
        from tools.edit_file import edit_file

        ctx = AutoConfirmCtx(tmp_dir)
        await edit_file(
            "simple.txt",
            [{"search": "beta", "replace": "BETA"}],
            ctx=ctx,
        )

        with open(os.path.join(tmp_dir, "simple.txt")) as f:
            content = f.read()
        # alpha and gamma unchanged
        assert content.startswith("alpha\n")
        assert content.endswith("gamma\n")


# ---------------------------------------------------------------------------
# YOLO mode tests
# ---------------------------------------------------------------------------

class TestYoloMode:
    """Test that session.yolo_mode skips confirmation modals."""

    @pytest.mark.asyncio
    async def test_yolo_mode_skips_modal_edit(self, tmp_dir):
        from tools.edit_file import edit_file

        # YOLO mode — no app needed, edits apply immediately
        ctx = YoloCtx(tmp_dir)
        result = await edit_file(
            "simple.txt",
            [{"search": "beta", "replace": "BETA"}],
            ctx=ctx,
        )
        assert "Applied 1 edit" in result

        with open(os.path.join(tmp_dir, "simple.txt")) as f:
            assert f.read() == "alpha\nBETA\ngamma\n"

    @pytest.mark.asyncio
    async def test_yolo_mode_skips_modal_write(self, tmp_dir):
        from tools.write_file import write_file

        ctx = YoloCtx(tmp_dir)
        result = await write_file(
            "new_file.txt",
            "hello world",
            ctx=ctx,
        )
        assert "Wrote" in result

        with open(os.path.join(tmp_dir, "new_file.txt")) as f:
            assert f.read() == "hello world"

    @pytest.mark.asyncio
    async def test_yolo_mode_false_still_requires_app(self, tmp_dir):
        """When yolo_mode is False, lack of app should still cause an error."""
        from tools.edit_file import edit_file

        # Config says yolo_mode=False, no app — should fail
        ctx = FakeCtx(tmp_dir)
        ctx.config = FakeConfig(yolo_mode=False)
        result = await edit_file(
            "simple.txt",
            [{"search": "beta", "replace": "BETA"}],
            ctx=ctx,
        )
        assert "no application context" in result.lower() or "error" in result.lower()