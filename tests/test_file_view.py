"""Tests for FileView — read-only file viewer."""

import os
import tempfile
import pytest
from textual.app import App, ComposeResult
from textual.widgets import Static

from ui.workspace.file_view import FileView


class FileViewTestApp(App):
    """Minimal app hosting a FileView for testing."""

    CSS = "FileView { height: 100%; width: 100%; }"

    def __init__(self, filepath: str):
        super().__init__()
        self._filepath = filepath

    def compose(self) -> ComposeResult:
        self.view = FileView(self._filepath)
        yield self.view


class TestFileView:
    async def test_displays_file_content(self):
        """FileView shows the content of the file."""
        tmpdir = tempfile.mkdtemp()
        filepath = os.path.join(tmpdir, "test.txt")
        try:
            with open(filepath, "w") as f:
                f.write("Hello, World!\nSecond line.")

            async with FileViewTestApp(filepath).run_test() as pilot:
                await pilot.pause()
                view = pilot.app.view
                statics = view.query(Static)
                content = statics[0].render().plain
                assert "Hello, World!" in content
                assert "Second line." in content
        finally:
            import shutil
            shutil.rmtree(tmpdir)

    async def test_missing_file_shows_error(self):
        """FileView shows an error message for a missing file."""
        filepath = "/nonexistent/path/file.txt"

        async with FileViewTestApp(filepath).run_test() as pilot:
            await pilot.pause()
            view = pilot.app.view
            statics = view.query(Static)
            content = statics[0].render().plain
            assert "Could not read" in content

    async def test_filepath_property(self):
        """FileView exposes the filepath property."""
        tmpdir = tempfile.mkdtemp()
        filepath = os.path.join(tmpdir, "test.py")
        try:
            with open(filepath, "w") as f:
                f.write("print('hi')")

            async with FileViewTestApp(filepath).run_test() as pilot:
                await pilot.pause()
                view = pilot.app.view
                assert view.filepath == filepath
        finally:
            import shutil
            shutil.rmtree(tmpdir)

    async def test_refresh_file(self):
        """refresh_file() re-reads the file from disk."""
        tmpdir = tempfile.mkdtemp()
        filepath = os.path.join(tmpdir, "test.txt")
        try:
            with open(filepath, "w") as f:
                f.write("Original content")

            async with FileViewTestApp(filepath).run_test() as pilot:
                await pilot.pause()
                view = pilot.app.view
                statics = view.query(Static)
                assert "Original content" in statics[0].render().plain

                # Modify the file on disk
                with open(filepath, "w") as f:
                    f.write("Updated content")

                view.refresh_file()
                await pilot.pause()
                assert "Updated content" in statics[0].render().plain
        finally:
            import shutil
            shutil.rmtree(tmpdir)

    async def test_empty_file(self):
        """FileView handles empty files without error."""
        tmpdir = tempfile.mkdtemp()
        filepath = os.path.join(tmpdir, "empty.txt")
        try:
            with open(filepath, "w") as f:
                pass  # empty file

            async with FileViewTestApp(filepath).run_test() as pilot:
                await pilot.pause()
                view = pilot.app.view
                statics = view.query(Static)
                content = statics[0].render().plain
                assert content == ""
        finally:
            import shutil
            shutil.rmtree(tmpdir)

    async def test_unicode_file(self):
        """FileView handles unicode content."""
        tmpdir = tempfile.mkdtemp()
        filepath = os.path.join(tmpdir, "unicode.txt")
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write("こんにちは世界\n🎉 Hello")

            async with FileViewTestApp(filepath).run_test() as pilot:
                await pilot.pause()
                view = pilot.app.view
                statics = view.query(Static)
                content = statics[0].render().plain
                assert "こんにちは" in content
                assert "🎉" in content
        finally:
            import shutil
            shutil.rmtree(tmpdir)