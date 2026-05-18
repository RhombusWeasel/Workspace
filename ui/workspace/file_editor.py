"""File editor — editable file viewer with syntax highlighting.

Uses Textual's :class:`~textual.widgets.TextArea` to provide a rich
editing experience with syntax highlighting, line numbers, and undo/redo.

Opened inside workspace tabs when a file is selected from the file browser.
Reads the file from disk on mount.  Supports saving changes back to disk
via :meth:`save_file`.
"""

from __future__ import annotations

import os

from textual.app import ComposeResult
from textual.widgets import TextArea
from textual.widget import Widget

from utils.dom_id import path_to_id

# ---------------------------------------------------------------------------
# Language mapping — file extensions → Textual TextArea language names
# ---------------------------------------------------------------------------

_EXTENSION_TO_LANGUAGE: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "javascript",
    ".jsx": "javascript",
    ".tsx": "javascript",
    ".rs": "rust",
    ".go": "go",
    ".java": "java",
    ".html": "html",
    ".htm": "html",
    ".css": "css",
    ".scss": "css",
    ".less": "css",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".xml": "xml",
    ".sql": "sql",
    ".sh": "bash",
    ".bash": "bash",
    ".zsh": "bash",
    ".md": "markdown",
}


def _language_for_file(filepath: str) -> str | None:
    """Return the Textual TextArea language name for *filepath*, or None."""
    _, ext = os.path.splitext(filepath)
    return _EXTENSION_TO_LANGUAGE.get(ext.lower())


# ---------------------------------------------------------------------------
# FileEditor
# ---------------------------------------------------------------------------


class FileEditor(Widget):
    """Editable file viewer with syntax highlighting.

    Parameters
    ----------
    filepath:
        Absolute path to the file to edit.
    """

    DEFAULT_CSS = """
    FileEditor {
        height: 1fr;
        width: 1fr;
    }

    FileEditor TextArea {
        height: 1fr;
        width: 1fr;
    }
    """

    def __init__(self, filepath: str):
        super().__init__(id=path_to_id("fv", filepath))
        self._filepath = filepath
        self._content = ""
        self._language = _language_for_file(filepath)

    @property
    def filepath(self) -> str:
        return self._filepath

    @property
    def editor(self) -> TextArea:
        """Return the inner :class:`TextArea` widget."""
        return self.query_one(TextArea)

    def compose(self) -> ComposeResult:
        text_area = TextArea.code_editor(
            self._content,
            language=self._language,
            theme="monokai",
            soft_wrap=False,
            show_line_numbers=True,
            read_only=False,
            tab_behavior="indent",
        )
        yield text_area

    def on_mount(self) -> None:
        self._load_file()

    def _load_file(self) -> None:
        """Read the file from disk and update the editor."""
        try:
            with open(self._filepath, "r", encoding="utf-8", errors="replace") as f:
                self._content = f.read()
        except (OSError, UnicodeDecodeError):
            self._content = f"(Could not read file: {self._filepath})"

        # Update the TextArea if it's already mounted
        try:
            text_area = self.query_one(TextArea)
            text_area.load_text(self._content)
            # Apply language — None means plain text (no syntax highlighting)
            text_area.language = self._language
        except Exception:
            pass

    def refresh_file(self) -> None:
        """Re-read the file from disk and update the editor."""
        self._load_file()

    def save_file(self) -> bool:
        """Write the current editor content back to disk.

        Returns
        -------
        bool
            True if the save succeeded, False otherwise.
        """
        try:
            text_area = self.query_one(TextArea)
            content = text_area.text
            with open(self._filepath, "w", encoding="utf-8") as f:
                f.write(content)
            return True
        except (OSError, Exception):
            return False

    @property
    def is_modified(self) -> bool:
        """Whether the editor content differs from the on-disk file."""
        try:
            text_area = self.query_one(TextArea)
            return text_area.text != self._content
        except Exception:
            return False