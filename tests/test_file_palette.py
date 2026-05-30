"""Tests for FilePalette — popup file selector for @ mentions."""

import os
import tempfile
import pytest
from textual.app import App, ComposeResult
from textual.widgets import OptionList

from skills.chat.file_palette import FilePalette, scan_files, _IGNORED_NAMES


# ---------------------------------------------------------------------------
# Test app
# ---------------------------------------------------------------------------


class FilePaletteTestApp(App):
    """Minimal app hosting a FilePalette."""

    CSS = """
    FilePalette {
        width: 60;
    }
    """

    def __init__(self, working_directory: str = ""):
        super().__init__()
        self._wd = working_directory

    def compose(self) -> ComposeResult:
        palette = FilePalette()
        if self._wd:
            palette.set_working_directory(self._wd)
        yield palette


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_project_files(tmpdir: str) -> dict[str, str]:
    """Create a small project tree inside *tmpdir* and return {relpath: content}."""
    files = {
        "README.md": "# Hello",
        "main.py": "print('hi')",
        os.path.join("ui", "app.py"): "# app",
        os.path.join("ui", "widgets.py"): "# widgets",
        os.path.join("core", "config.py"): "# config",
        os.path.join("core", "agent.py"): "# agent",
        os.path.join("tests", "test_app.py"): "# test",
        "data.txt": "some data",
    }
    for relpath, content in files.items():
        full = os.path.join(tmpdir, relpath)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w") as f:
            f.write(content)
    return files


async def _settle(pilot, n: int = 2) -> None:
    for _ in range(n):
        await pilot.pause()


# ---------------------------------------------------------------------------
# Tests — scan_files
# ---------------------------------------------------------------------------


class TestScanFiles:
    def test_scans_files_recursively(self):
        """scan_files finds files at all depths."""
        tmpdir = tempfile.mkdtemp()
        try:
            _create_project_files(tmpdir)
            result = scan_files(tmpdir)
            assert "main.py" in result
            assert os.path.join("ui", "app.py") in result
            assert os.path.join("core", "config.py") in result
        finally:
            import shutil
            shutil.rmtree(tmpdir)

    def test_excludes_ignored_directories(self):
        """scan_files skips _IGNORED_NAMES directories."""
        tmpdir = tempfile.mkdtemp()
        try:
            # Create a file inside an ignored directory
            ignored_dir = os.path.join(tmpdir, "__pycache__")
            os.makedirs(ignored_dir)
            with open(os.path.join(ignored_dir, "cached.pyc"), "w") as f:
                f.write("bytecode")
            # And a normal file
            with open(os.path.join(tmpdir, "main.py"), "w") as f:
                f.write("code")

            result = scan_files(tmpdir)
            assert "main.py" in result
            assert os.path.join("__pycache__", "cached.pyc") not in result
        finally:
            import shutil
            shutil.rmtree(tmpdir)

    def test_excludes_hidden_by_default(self):
        """scan_files skips dotfiles and dotdirs unless show_hidden=True."""
        tmpdir = tempfile.mkdtemp()
        try:
            with open(os.path.join(tmpdir, ".env"), "w") as f:
                f.write("SECRET=1")
            dotdir = os.path.join(tmpdir, ".hidden_dir")
            os.makedirs(dotdir)
            with open(os.path.join(dotdir, "file.txt"), "w") as f:
                f.write("hidden")
            with open(os.path.join(tmpdir, "visible.py"), "w") as f:
                f.write("code")

            result_no_hidden = scan_files(tmpdir, show_hidden=False)
            assert "visible.py" in result_no_hidden
            assert ".env" not in result_no_hidden
            assert os.path.join(".hidden_dir", "file.txt") not in result_no_hidden

            result_with_hidden = scan_files(tmpdir, show_hidden=True)
            assert ".env" in result_with_hidden
            assert os.path.join(".hidden_dir", "file.txt") in result_with_hidden
        finally:
            import shutil
            shutil.rmtree(tmpdir)

    def test_respects_max_depth(self):
        """scan_files stops at max_depth."""
        tmpdir = tempfile.mkdtemp()
        try:
            deep = os.path.join(tmpdir, "a", "b", "c", "d", "e", "f")
            os.makedirs(deep)
            with open(os.path.join(deep, "deep.txt"), "w") as f:
                f.write("deep")
            with open(os.path.join(tmpdir, "shallow.txt"), "w") as f:
                f.write("shallow")

            # Depth 2 should not reach level 6
            result = scan_files(tmpdir, max_depth=2)
            assert "shallow.txt" in result
            assert os.path.join("a", "b", "deep.txt") not in result
        finally:
            import shutil
            shutil.rmtree(tmpdir)

    async def test_display_cap_in_populate(self):
        """FilePalette caps display to _DISPLAY_CAP entries."""
        from skills.chat.file_palette import _DISPLAY_CAP
        tmpdir = tempfile.mkdtemp()
        try:
            # Create more files than the display cap
            for i in range(_DISPLAY_CAP + 10):
                with open(os.path.join(tmpdir, f"file_{i:03d}.txt"), "w") as f:
                    f.write(f"content {i}")

            async with FilePaletteTestApp(tmpdir).run_test() as pilot:
                await pilot.pause()
                palette = pilot.app.query_one(FilePalette)
                palette.update_filter("")
                ol = palette.query_one(OptionList)
                # Option list should be capped, not show all files
                assert ol.option_count == _DISPLAY_CAP
        finally:
            import shutil
            shutil.rmtree(tmpdir)

    def test_scan_finds_deep_files(self):
        """scan_files finds files in deeply nested directories."""
        tmpdir = tempfile.mkdtemp()
        try:
            # Create skills/workspace_docs/docs/style.md nested structure
            deep = os.path.join(tmpdir, "skills", "workspace_docs", "docs")
            os.makedirs(deep)
            with open(os.path.join(deep, "style.md"), "w") as f:
                f.write("# Style")
            # Also a top-level file
            with open(os.path.join(tmpdir, "main.py"), "w") as f:
                f.write("code")

            result = scan_files(tmpdir)
            assert "main.py" in result
            assert os.path.join("skills", "workspace_docs", "docs", "style.md") in result
        finally:
            import shutil
            shutil.rmtree(tmpdir)

    def test_results_sorted_alphabetically(self):
        """scan_files returns results in sorted order."""
        tmpdir = tempfile.mkdtemp()
        try:
            for name in ["zebra.py", "alpha.py", "mid.py"]:
                with open(os.path.join(tmpdir, name), "w") as f:
                    f.write(name)

            result = scan_files(tmpdir)
            assert result == sorted(result)
        finally:
            import shutil
            shutil.rmtree(tmpdir)

    def test_empty_directory(self):
        """scan_files returns empty list for empty directory."""
        tmpdir = tempfile.mkdtemp()
        try:
            result = scan_files(tmpdir)
            assert result == []
        finally:
            import shutil
            shutil.rmtree(tmpdir)

    def test_excludes_special_ignored_names(self):
        """scan_files skips node_modules, .git, venv, etc."""
        tmpdir = tempfile.mkdtemp()
        try:
            for ignored in ["node_modules", ".git", "venv", ".venv"]:
                d = os.path.join(tmpdir, ignored)
                os.makedirs(d)
                with open(os.path.join(d, "file.txt"), "w") as f:
                    f.write("ignored")
            with open(os.path.join(tmpdir, "real.py"), "w") as f:
                f.write("real")

            result = scan_files(tmpdir)
            assert "real.py" in result
            for ignored in ["node_modules", ".git", "venv", ".venv"]:
                assert not any(ignored in r for r in result)
        finally:
            import shutil
            shutil.rmtree(tmpdir)


# ---------------------------------------------------------------------------
# Tests — FilePalette visibility
# ---------------------------------------------------------------------------


class TestFilePaletteVisibility:
    async def test_starts_hidden(self):
        """FilePalette starts hidden (no -visible class)."""
        async with FilePaletteTestApp().run_test() as pilot:
            await pilot.pause()
            palette = pilot.app.query_one(FilePalette)
            assert not palette.is_visible

    async def test_show_makes_visible(self):
        """show() adds the -visible class."""
        tmpdir = tempfile.mkdtemp()
        try:
            async with FilePaletteTestApp(tmpdir).run_test() as pilot:
                await pilot.pause()
                palette = pilot.app.query_one(FilePalette)
                palette.show()
                assert palette.is_visible
        finally:
            import shutil
            shutil.rmtree(tmpdir)

    async def test_hide_removes_visible(self):
        """hide() removes the -visible class."""
        tmpdir = tempfile.mkdtemp()
        try:
            async with FilePaletteTestApp(tmpdir).run_test() as pilot:
                await pilot.pause()
                palette = pilot.app.query_one(FilePalette)
                palette.show()
                assert palette.is_visible
                palette.hide()
                assert not palette.is_visible
        finally:
            import shutil
            shutil.rmtree(tmpdir)


# ---------------------------------------------------------------------------
# Tests — FilePalette filtering
# ---------------------------------------------------------------------------


class TestFilePaletteFiltering:
    async def test_update_filter_with_empty_query_shows_all(self):
        """update_filter('') shows all files."""
        tmpdir = tempfile.mkdtemp()
        try:
            _create_project_files(tmpdir)

            async with FilePaletteTestApp(tmpdir).run_test() as pilot:
                await pilot.pause()
                palette = pilot.app.query_one(FilePalette)
                palette.update_filter("")
                assert palette.is_visible
                ol = palette.query_one(OptionList)
                # All files should appear (8 project files)
                assert ol.option_count >= 8
        finally:
            import shutil
            shutil.rmtree(tmpdir)

    async def test_update_filter_narrows_results(self):
        """update_filter with a query shows only matching files."""
        tmpdir = tempfile.mkdtemp()
        try:
            _create_project_files(tmpdir)

            async with FilePaletteTestApp(tmpdir).run_test() as pilot:
                await pilot.pause()
                palette = pilot.app.query_one(FilePalette)
                # Filter for "config" — should match core/config.py
                palette.update_filter("config")
                assert palette.is_visible
                ol = palette.query_one(OptionList)
                assert ol.option_count == 1
        finally:
            import shutil
            shutil.rmtree(tmpdir)

    async def test_update_filter_no_match_shows_empty(self):
        """update_filter with no matching files shows empty list."""
        tmpdir = tempfile.mkdtemp()
        try:
            _create_project_files(tmpdir)

            async with FilePaletteTestApp(tmpdir).run_test() as pilot:
                await pilot.pause()
                palette = pilot.app.query_one(FilePalette)
                palette.update_filter("zzzznonexistent")
                assert palette.is_visible
                ol = palette.query_one(OptionList)
                assert ol.option_count == 0
        finally:
            import shutil
            shutil.rmtree(tmpdir)

    async def test_update_filter_case_insensitive(self):
        """File filtering is case-insensitive."""
        tmpdir = tempfile.mkdtemp()
        try:
            _create_project_files(tmpdir)

            async with FilePaletteTestApp(tmpdir).run_test() as pilot:
                await pilot.pause()
                palette = pilot.app.query_one(FilePalette)
                # "CONFIG" should match "core/config.py"
                palette.update_filter("CONFIG")
                assert palette.is_visible
                ol = palette.query_one(OptionList)
                assert ol.option_count == 1
        finally:
            import shutil
            shutil.rmtree(tmpdir)

    async def test_update_filter_substring_match_on_path(self):
        """Filtering matches substrings in the full relative path."""
        tmpdir = tempfile.mkdtemp()
        try:
            _create_project_files(tmpdir)

            async with FilePaletteTestApp(tmpdir).run_test() as pilot:
                await pilot.pause()
                palette = pilot.app.query_one(FilePalette)
                # "ui/app" should match "ui/app.py" by path substring
                palette.update_filter("ui/app")
                ol = palette.query_one(OptionList)
                assert ol.option_count == 1
        finally:
            import shutil
            shutil.rmtree(tmpdir)

    async def test_update_filter_bare_at_shows_all(self):
        """An empty filter (just @ with nothing after it) shows all files."""
        tmpdir = tempfile.mkdtemp()
        try:
            _create_project_files(tmpdir)

            async with FilePaletteTestApp(tmpdir).run_test() as pilot:
                await pilot.pause()
                palette = pilot.app.query_one(FilePalette)
                palette.update_filter("")
                ol = palette.query_one(OptionList)
                assert ol.option_count >= 8
        finally:
            import shutil
            shutil.rmtree(tmpdir)


# ---------------------------------------------------------------------------
# Tests — FilePalette selection
# ---------------------------------------------------------------------------


class TestFilePaletteSelection:
    async def test_select_highlighted_returns_filepath(self):
        """select_highlighted() returns the relative path of the highlighted option."""
        tmpdir = tempfile.mkdtemp()
        try:
            _create_project_files(tmpdir)

            async with FilePaletteTestApp(tmpdir).run_test() as pilot:
                await pilot.pause()
                palette = pilot.app.query_one(FilePalette)
                palette.update_filter("")
                await _settle(pilot)

                name = palette.select_highlighted()
                # First file alphabetically should be "core/agent.py" (sorted)
                assert name is not None
                assert isinstance(name, str)
        finally:
            import shutil
            shutil.rmtree(tmpdir)

    async def test_select_highlighted_returns_none_when_hidden(self):
        """select_highlighted() returns None when palette is hidden."""
        async with FilePaletteTestApp().run_test() as pilot:
            await pilot.pause()
            palette = pilot.app.query_one(FilePalette)
            assert palette.select_highlighted() is None

    async def test_move_highlight_changes_selection(self):
        """move_highlight() changes the highlighted item."""
        tmpdir = tempfile.mkdtemp()
        try:
            _create_project_files(tmpdir)

            async with FilePaletteTestApp(tmpdir).run_test() as pilot:
                await pilot.pause()
                palette = pilot.app.query_one(FilePalette)
                palette.update_filter("")
                await _settle(pilot)

                first = palette.select_highlighted()
                palette.move_highlight(1)
                second = palette.select_highlighted()
                assert first != second
        finally:
            import shutil
            shutil.rmtree(tmpdir)


# ---------------------------------------------------------------------------
# Tests — caching / lazy scan
# ---------------------------------------------------------------------------


class TestFilePaletteCaching:
    async def test_lazy_scan_only_on_first_show(self):
        """File list is scanned lazily — cache starts empty."""
        tmpdir = tempfile.mkdtemp()
        try:
            async with FilePaletteTestApp(tmpdir).run_test() as pilot:
                await pilot.pause()
                palette = pilot.app.query_one(FilePalette)
                # Before first show, cache should be empty
                assert palette._all_files is None

                # Trigger scan
                palette.show()
                assert palette._all_files is not None
        finally:
            import shutil
            shutil.rmtree(tmpdir)

    async def test_cache_reused_on_second_show(self):
        """Second show() uses cached file list (same object)."""
        tmpdir = tempfile.mkdtemp()
        try:
            async with FilePaletteTestApp(tmpdir).run_test() as pilot:
                await pilot.pause()
                palette = pilot.app.query_one(FilePalette)
                palette.show()
                first_cache = palette._all_files

                palette.hide()
                palette.show()
                assert palette._all_files is first_cache
        finally:
            import shutil
            shutil.rmtree(tmpdir)

    async def test_refresh_invalidates_cache(self):
        """refresh_file_list() clears the cache and re-scans."""
        tmpdir = tempfile.mkdtemp()
        try:
            async with FilePaletteTestApp(tmpdir).run_test() as pilot:
                await pilot.pause()
                palette = pilot.app.query_one(FilePalette)
                palette.show()
                first_cache = palette._all_files

                palette.refresh_file_list()
                # Cache was invalidated and re-scanned
                assert palette._all_files is not None
                assert palette._all_files is not first_cache
        finally:
            import shutil
            shutil.rmtree(tmpdir)

    async def test_working_directory_change_invalidates_cache(self):
        """Changing the working directory invalidates the cache."""
        tmpdir = tempfile.mkdtemp()
        try:
            async with FilePaletteTestApp(tmpdir).run_test() as pilot:
                await pilot.pause()
                palette = pilot.app.query_one(FilePalette)
                palette.show()
                first_cache = palette._all_files

                palette.set_working_directory("/tmp")
                assert palette._all_files is None  # Invalidated
        finally:
            import shutil
            shutil.rmtree(tmpdir)