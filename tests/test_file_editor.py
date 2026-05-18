"""Tests for FileEditor — editable file viewer with syntax highlighting."""

import os
import tempfile
import pytest
from textual.app import App, ComposeResult
from textual.widgets import TextArea

from ui.workspace.file_editor import FileEditor, _language_for_file


class FileEditorTestApp(App):
    """Minimal app hosting a FileEditor for testing."""

    CSS = "FileEditor { height: 100%; width: 100%; }"

    def __init__(self, filepath: str):
        super().__init__()
        self._filepath = filepath

    def compose(self) -> ComposeResult:
        self.editor_widget = FileEditor(self._filepath)
        yield self.editor_widget


class TestFileEditor:
    async def test_displays_file_content(self):
        """FileEditor shows the content of the file."""
        tmpdir = tempfile.mkdtemp()
        filepath = os.path.join(tmpdir, "test.txt")
        try:
            with open(filepath, "w") as f:
                f.write("Hello, World!\nSecond line.")

            async with FileEditorTestApp(filepath).run_test() as pilot:
                await pilot.pause()
                editor_widget = pilot.app.editor_widget
                text_area = editor_widget.query_one(TextArea)
                assert "Hello, World!" in text_area.text
                assert "Second line." in text_area.text
        finally:
            import shutil
            shutil.rmtree(tmpdir)

    async def test_missing_file_shows_error(self):
        """FileEditor shows an error message for a missing file."""
        filepath = "/nonexistent/path/file.txt"

        async with FileEditorTestApp(filepath).run_test() as pilot:
            await pilot.pause()
            editor_widget = pilot.app.editor_widget
            text_area = editor_widget.query_one(TextArea)
            assert "Could not read" in text_area.text

    async def test_filepath_property(self):
        """FileEditor exposes the filepath property."""
        tmpdir = tempfile.mkdtemp()
        filepath = os.path.join(tmpdir, "test.py")
        try:
            with open(filepath, "w") as f:
                f.write("print('hi')")

            async with FileEditorTestApp(filepath).run_test() as pilot:
                await pilot.pause()
                editor_widget = pilot.app.editor_widget
                assert editor_widget.filepath == filepath
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

            async with FileEditorTestApp(filepath).run_test() as pilot:
                await pilot.pause()
                editor_widget = pilot.app.editor_widget
                text_area = editor_widget.query_one(TextArea)
                assert "Original content" in text_area.text

                # Modify the file on disk
                with open(filepath, "w") as f:
                    f.write("Updated content")

                editor_widget.refresh_file()
                await pilot.pause()
                assert "Updated content" in text_area.text
        finally:
            import shutil
            shutil.rmtree(tmpdir)

    async def test_empty_file(self):
        """FileEditor handles empty files without error."""
        tmpdir = tempfile.mkdtemp()
        filepath = os.path.join(tmpdir, "empty.txt")
        try:
            with open(filepath, "w") as f:
                pass  # empty file

            async with FileEditorTestApp(filepath).run_test() as pilot:
                await pilot.pause()
                editor_widget = pilot.app.editor_widget
                text_area = editor_widget.query_one(TextArea)
                assert text_area.text == ""
        finally:
            import shutil
            shutil.rmtree(tmpdir)

    async def test_unicode_file(self):
        """FileEditor handles unicode content."""
        tmpdir = tempfile.mkdtemp()
        filepath = os.path.join(tmpdir, "unicode.txt")
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write("こんにちは世界\n🎉 Hello")

            async with FileEditorTestApp(filepath).run_test() as pilot:
                await pilot.pause()
                editor_widget = pilot.app.editor_widget
                text_area = editor_widget.query_one(TextArea)
                assert "こんにちは" in text_area.text
                assert "🎉" in text_area.text
        finally:
            import shutil
            shutil.rmtree(tmpdir)

    async def test_editor_property(self):
        """FileEditor exposes the editor property returning the TextArea."""
        tmpdir = tempfile.mkdtemp()
        filepath = os.path.join(tmpdir, "test.py")
        try:
            with open(filepath, "w") as f:
                f.write("print('hi')")

            async with FileEditorTestApp(filepath).run_test() as pilot:
                await pilot.pause()
                editor_widget = pilot.app.editor_widget
                text_area = editor_widget.editor
                assert isinstance(text_area, TextArea)
        finally:
            import shutil
            shutil.rmtree(tmpdir)

    async def test_python_syntax_highlighting(self):
        """FileEditor sets Python language for .py files."""
        tmpdir = tempfile.mkdtemp()
        filepath = os.path.join(tmpdir, "test.py")
        try:
            with open(filepath, "w") as f:
                f.write("def hello():\n    print('hi')")

            async with FileEditorTestApp(filepath).run_test() as pilot:
                await pilot.pause()
                editor_widget = pilot.app.editor_widget
                text_area = editor_widget.query_one(TextArea)
                assert text_area.language == "python"
                assert text_area.is_syntax_aware is True
        finally:
            import shutil
            shutil.rmtree(tmpdir)

    async def test_javascript_syntax_highlighting(self):
        """FileEditor sets JavaScript language for .js files."""
        tmpdir = tempfile.mkdtemp()
        filepath = os.path.join(tmpdir, "app.js")
        try:
            with open(filepath, "w") as f:
                f.write("console.log('hello');")

            async with FileEditorTestApp(filepath).run_test() as pilot:
                await pilot.pause()
                editor_widget = pilot.app.editor_widget
                text_area = editor_widget.query_one(TextArea)
                assert text_area.language == "javascript"
                assert text_area.is_syntax_aware is True
        finally:
            import shutil
            shutil.rmtree(tmpdir)

    async def test_unknown_extension_no_highlighting(self):
        """FileEditor uses plain text (no language) for unknown extensions."""
        tmpdir = tempfile.mkdtemp()
        filepath = os.path.join(tmpdir, "data.xyz")
        try:
            with open(filepath, "w") as f:
                f.write("some plain text content")

            async with FileEditorTestApp(filepath).run_test() as pilot:
                await pilot.pause()
                editor_widget = pilot.app.editor_widget
                text_area = editor_widget.query_one(TextArea)
                assert text_area.language is None
        finally:
            import shutil
            shutil.rmtree(tmpdir)

    async def test_editing_changes_text(self):
        """File content can be edited in the TextArea."""
        tmpdir = tempfile.mkdtemp()
        filepath = os.path.join(tmpdir, "editable.txt")
        try:
            with open(filepath, "w") as f:
                f.write("Original")

            async with FileEditorTestApp(filepath).run_test() as pilot:
                await pilot.pause()
                editor_widget = pilot.app.editor_widget
                text_area = editor_widget.query_one(TextArea)

                # Simulate typing — replace the content
                text_area.load_text("Modified")
                await pilot.pause()
                assert "Modified" in text_area.text
        finally:
            import shutil
            shutil.rmtree(tmpdir)

    async def test_save_file(self):
        """save_file() writes editor content back to disk."""
        tmpdir = tempfile.mkdtemp()
        filepath = os.path.join(tmpdir, "save_test.txt")
        try:
            with open(filepath, "w") as f:
                f.write("Original")

            async with FileEditorTestApp(filepath).run_test() as pilot:
                await pilot.pause()
                editor_widget = pilot.app.editor_widget
                text_area = editor_widget.query_one(TextArea)

                # Modify content
                text_area.load_text("Saved content")
                await pilot.pause()

                # Save to disk
                result = editor_widget.save_file()
                assert result is True

                # Verify file on disk
                with open(filepath) as f:
                    assert f.read() == "Saved content"
        finally:
            import shutil
            shutil.rmtree(tmpdir)

    async def test_line_numbers_enabled(self):
        """FileEditor shows line numbers by default."""
        tmpdir = tempfile.mkdtemp()
        filepath = os.path.join(tmpdir, "lines.py")
        try:
            with open(filepath, "w") as f:
                f.write("line1\nline2\nline3")

            async with FileEditorTestApp(filepath).run_test() as pilot:
                await pilot.pause()
                editor_widget = pilot.app.editor_widget
                text_area = editor_widget.query_one(TextArea)
                assert text_area.show_line_numbers is True
        finally:
            import shutil
            shutil.rmtree(tmpdir)


class TestLanguageForFile:
    def test_python(self):
        assert _language_for_file("hello.py") == "python"

    def test_javascript(self):
        assert _language_for_file("app.js") == "javascript"

    def test_typescript(self):
        assert _language_for_file("app.ts") == "javascript"

    def test_rust(self):
        assert _language_for_file("main.rs") == "rust"

    def test_go(self):
        assert _language_for_file("main.go") == "go"

    def test_json(self):
        assert _language_for_file("data.json") == "json"

    def test_yaml(self):
        assert _language_for_file("config.yaml") == "yaml"
        assert _language_for_file("config.yml") == "yaml"

    def test_html(self):
        assert _language_for_file("page.html") == "html"

    def test_css(self):
        assert _language_for_file("style.css") == "css"

    def test_markdown(self):
        assert _language_for_file("README.md") == "markdown"

    def test_toml(self):
        assert _language_for_file("pyproject.toml") == "toml"

    def test_sql(self):
        assert _language_for_file("query.sql") == "sql"

    def test_bash(self):
        assert _language_for_file("script.sh") == "bash"

    def test_unknown_extension(self):
        assert _language_for_file("data.xyz") is None

    def test_case_insensitive(self):
        assert _language_for_file("APP.PY") == "python"