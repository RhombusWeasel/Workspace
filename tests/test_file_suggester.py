"""Tests for FileSuggester — inline file path completion for @ mentions."""

import os
import tempfile
import pytest

from skills.chat.file_suggester import FileSuggester
from skills.chat.file_palette import scan_files


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _create_project_files(tmpdir: str) -> None:
    """Create a small project tree inside *tmpdir*."""
    files = {
        "main.py": "print('hi')",
        "config.py": "# config",
        os.path.join("ui", "app.py"): "# app",
    }
    for relpath, content in files.items():
        full = os.path.join(tmpdir, relpath)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w") as f:
            f.write(content)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestFileSuggester:
    async def test_no_suggestion_for_normal_text(self):
        """Text without @ gets no suggestion."""
        s = FileSuggester()
        result = await s.get_suggestion("hello world")
        assert result is None

    async def test_no_suggestion_for_empty_string(self):
        """Empty string gets no suggestion."""
        s = FileSuggester()
        result = await s.get_suggestion("")
        assert result is None

    async def test_suggestion_for_at_prefix(self):
        """Text containing @ with matching file suggests a path."""
        tmpdir = tempfile.mkdtemp()
        try:
            _create_project_files(tmpdir)
            s = FileSuggester(working_directory=tmpdir)
            result = await s.get_suggestion("@main")
            assert result is not None
            assert result.startswith("@")
            assert "main.py" in result
        finally:
            import shutil
            shutil.rmtree(tmpdir)

    async def test_suggestion_matches_substring(self):
        """File suggestion uses substring matching on the path."""
        tmpdir = tempfile.mkdtemp()
        try:
            _create_project_files(tmpdir)
            s = FileSuggester(working_directory=tmpdir)
            result = await s.get_suggestion("@config")
            assert result is not None
            assert "config.py" in result
        finally:
            import shutil
            shutil.rmtree(tmpdir)

    async def test_no_suggestion_after_space_in_at_mention(self):
        """Once a space follows the @ query, the mention is complete — no suggestion."""
        tmpdir = tempfile.mkdtemp()
        try:
            _create_project_files(tmpdir)
            s = FileSuggester(working_directory=tmpdir)
            # Space after @main means the mention is already complete
            result = await s.get_suggestion("Look at @main for details")
            assert result is None
        finally:
            import shutil
            shutil.rmtree(tmpdir)

    async def test_suggestion_mid_message_active(self):
        """@ in the middle of a message (still typing the query) triggers suggestion."""
        tmpdir = tempfile.mkdtemp()
        try:
            _create_project_files(tmpdir)
            s = FileSuggester(working_directory=tmpdir)
            result = await s.get_suggestion("Look at @main")
            assert result is not None
            assert "main.py" in result
        finally:
            import shutil
            shutil.rmtree(tmpdir)

    async def test_bare_at_suggests_first_file(self):
        """Just '@' suggests the first file alphabetically."""
        tmpdir = tempfile.mkdtemp()
        try:
            _create_project_files(tmpdir)
            s = FileSuggester(working_directory=tmpdir)
            result = await s.get_suggestion("@")
            assert result is not None
            assert result.startswith("@")
        finally:
            import shutil
            shutil.rmtree(tmpdir)

    async def test_no_suggestion_for_non_matching(self):
        """@ with no matching files returns None."""
        tmpdir = tempfile.mkdtemp()
        try:
            _create_project_files(tmpdir)
            s = FileSuggester(working_directory=tmpdir)
            result = await s.get_suggestion("@zzzzznonexistent")
            assert result is None
        finally:
            import shutil
            shutil.rmtree(tmpdir)

    async def test_no_suggestion_for_slash_commands(self):
        """/command text doesn't trigger file suggestions."""
        s = FileSuggester()
        result = await s.get_suggestion("/help")
        assert result is None

    async def test_working_directory_change_invalidates_cache(self):
        """Changing working_directory invalidates the file list cache."""
        tmpdir1 = tempfile.mkdtemp()
        tmpdir2 = tempfile.mkdtemp()
        try:
            _create_project_files(tmpdir1)
            with open(os.path.join(tmpdir2, "other.txt"), "w") as f:
                f.write("other")

            s = FileSuggester(working_directory=tmpdir1)
            result1 = await s.get_suggestion("@main")
            assert "main.py" in result1

            # Change working directory — cache invalidated
            s.working_directory = tmpdir2
            result2 = await s.get_suggestion("@other")
            assert "other.txt" in result2
        finally:
            import shutil
            shutil.rmtree(tmpdir1)
            shutil.rmtree(tmpdir2)

    async def test_case_insensitive_matching(self):
        """File suggestion matching is case-insensitive."""
        tmpdir = tempfile.mkdtemp()
        try:
            _create_project_files(tmpdir)
            s = FileSuggester(working_directory=tmpdir)
            result = await s.get_suggestion("@MAIN")
            assert result is not None
            assert "main.py" in result
        finally:
            import shutil
            shutil.rmtree(tmpdir)