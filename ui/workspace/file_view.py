"""File view — read-only file viewer for displaying file contents.

Used inside workspace tabs to show the contents of a selected file.
Reads the file from disk on mount and renders it as plain text.
Future enhancement: syntax highlighting and editing.
"""

from __future__ import annotations

import os

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Static

from utils.icons import get_file_icon
from ui.sidebar.panels.file_browser import _path_to_id


class FileView(Widget):
    """Read-only file viewer that displays file contents.

    Parameters
    ----------
    filepath:
        Absolute path to the file to display.
    """

    DEFAULT_CSS = """
    FileView {
        height: 1fr;
        width: 1fr;
        overflow-y: auto;
        padding: 0 1;
    }
    """

    def __init__(self, filepath: str):
        super().__init__(id=_path_to_id(filepath))
        self._filepath = filepath
        self._content = ""

    @property
    def filepath(self) -> str:
        return self._filepath

    def compose(self) -> ComposeResult:
        yield Static(self._content, classes="file-content")

    def on_mount(self) -> None:
        self._load_file()

    def _load_file(self) -> None:
        """Read the file from disk and update the display."""
        try:
            with open(self._filepath, "r", encoding="utf-8", errors="replace") as f:
                self._content = f.read()
        except (OSError, UnicodeDecodeError):
            self._content = f"(Could not read file: {self._filepath})"

        # Update the static widget if already mounted
        statics = self.query(Static)
        if statics:
            statics[0].update(self._content)

    def refresh_file(self) -> None:
        """Re-read the file from disk and update the display."""
        self._load_file()