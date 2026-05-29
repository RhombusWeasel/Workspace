"""File palette — a popup list of project files that appears above the chat input.

Shows files from the working directory when the user types ``@`` in the
chat input.  Filters as they type more characters after the ``@``.
Allows selection with arrow keys, Enter, Tab, or click.

File discovery is lazy — the working directory is only scanned the first
time the palette is shown, and results are cached so subsequent opens
are instant.  A re-scan can be triggered via :meth:`refresh_file_list`.

Respects the same ignore rules as the file browser (``_IGNORED_NAMES``).
Recursive scan is capped at a configurable depth and maximum results to
keep the UI snappy even for large projects.
"""

from __future__ import annotations

import os

from textual.app import ComposeResult
from textual.message import Message
from textual.containers import Vertical
from textual.widgets import OptionList
from textual.widgets.option_list import Option

from utils.icons import get_file_icon

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Directories and files to skip (same as file_browser.py)
_IGNORED_NAMES: set[str] = {
    "__pycache__",
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    ".venv",
    "venv",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "dist",
    "build",
    "*.egg-info",
    ".eggs",
    ".idea",
    ".vscode",
    ".DS_Store",
    "Thumbs.db",
}

_DEFAULT_MAX_DEPTH: int = 5
_DISPLAY_CAP: int = 50


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------


def scan_files(
    working_directory: str,
    max_depth: int = _DEFAULT_MAX_DEPTH,
    show_hidden: bool = False,
) -> list[str]:
    """Recursively scan *working_directory* and return relative file paths.

    Skips entries in :data:`_IGNORED_NAMES` and (unless *show_hidden* is
    True) dotfiles and dotdirs.  Limits recursion to *max_depth* levels.
    Results are sorted alphabetically by relative path.

    The scan is lazy (only triggered on first palette open) and cached,
    so collecting all files is acceptable.  The display cap is applied
    at the UI level in :class:`FilePalette` — not here — so that
    filtering can match files anywhere in the project.
    """
    results: list[str] = []
    _walk(working_directory, working_directory, 0, max_depth, show_hidden, results)
    return sorted(results)


def _walk(
    root: str,
    current: str,
    depth: int,
    max_depth: int,
    show_hidden: bool,
    results: list[str],
) -> None:
    """Recursive directory walker that respects depth cap."""
    if depth > max_depth:
        return

    try:
        entries = sorted(os.listdir(current))
    except (PermissionError, OSError):
        return

    for name in entries:
        if name in _IGNORED_NAMES:
            continue
        if not show_hidden and name.startswith("."):
            continue

        full = os.path.join(current, name)
        if not os.path.exists(full):
            continue

        if os.path.isdir(full) and not os.path.islink(full):
            _walk(root, full, depth + 1, max_depth, show_hidden, results)
        else:
            rel = os.path.relpath(full, root)
            results.append(rel)


# ---------------------------------------------------------------------------
# FilePalette widget
# ---------------------------------------------------------------------------


class FilePalette(Vertical):
    """A popup list of project files, filtered by the current ``@`` query.

    Normally hidden.  Shown when the user types ``@`` in the chat input.
    Filters the file list as the user types more characters after ``@``.
    Pressing Enter on a highlighted item inserts the file path and closes
    the palette.  Pressing Escape closes it without selecting.

    The host widget (:class:`~skills.chat.chat_input.ChatInput`) is
    responsible for showing/hiding the palette and feeding it the
    current query via :meth:`update_filter`.

    File scanning is lazy — the first call to :meth:`show` or
    :meth:`update_filter` triggers a filesystem scan.  Results are
    cached so subsequent palette opens are instant.
    """

    class FileSelected(Message):
        """Posted when the user selects a file from the palette."""

        def __init__(self, filepath: str) -> None:
            super().__init__()
            self.filepath = filepath

    def __init__(self):
        super().__init__()
        self._filter: str = ""
        self._all_files: list[str] | None = None
        """Cached file list — ``None`` means not yet scanned."""
        self._working_directory: str = ""

    # ------------------------------------------------------------------
    # Composition
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        self._option_list = OptionList(id="file-option-list")
        yield self._option_list

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_working_directory(self, wd: str) -> None:
        """Set the working directory for file scanning.

        If the directory changes from the previous value, the cached
        file list is invalidated so the next palette open re-scans.
        """
        if wd != self._working_directory:
            self._all_files = None
            self._working_directory = wd

    def show(self) -> None:
        """Show the palette and populate with files.

        Triggers the initial filesystem scan if the cache is cold.
        """
        self._ensure_scanned()
        self._populate()
        self.add_class("-visible")
        self._option_list.highlighted = 0 if self._option_list.option_count > 0 else None

    def hide(self) -> None:
        """Hide the palette."""
        self.remove_class("-visible")

    @property
    def is_visible(self) -> bool:
        """Whether the palette is currently visible."""
        return self.has_class("-visible")

    def update_filter(self, query: str) -> None:
        """Update the filter text and refresh the file list.

        *query* should be the text after ``@`` (e.g. ``file_edit`` from
        an input of ``@file_edit``).  Files whose relative path contains
        the query (case-insensitive substring match) are shown.

        If *query* is empty, all files are shown (up to the display cap).
        Triggers the initial filesystem scan if the cache is cold.
        """
        self._filter = query.casefold()
        self._ensure_scanned()
        self._populate()
        if not self.is_visible:
            self.add_class("-visible")

    def move_highlight(self, delta: int) -> None:
        """Move the highlight up (delta=-1) or down (delta=+1)."""
        if not self.is_visible:
            return
        try:
            if delta > 0:
                self._option_list.action_cursor_down()
            else:
                self._option_list.action_cursor_up()
        except Exception:
            pass

    def select_highlighted(self) -> str | None:
        """Select the currently highlighted file.

        Returns the relative file path or ``None`` if the palette is
        not visible or nothing is highlighted.
        """
        if not self.is_visible:
            return None
        highlighted = self._option_list.highlighted
        if highlighted is None:
            return None
        option = self._option_list.get_option_at_index(highlighted)
        if option is None:
            return None
        return option.id

    def refresh_file_list(self) -> None:
        """Invalidate the cache and re-scan the working directory.

        The palette is re-populated if it is currently visible.
        """
        self._all_files = None
        if self.is_visible:
            self._ensure_scanned()
            self._populate()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _ensure_scanned(self) -> None:
        """Scan the working directory if the cache is cold."""
        if self._all_files is not None:
            return
        wd = self._working_directory
        if not wd:
            # Try to get working directory from AppContext
            app = self.app
            if hasattr(app, "context") and app.context is not None:
                wd = app.context.working_directory
            elif hasattr(app, "_wd"):
                wd = app._wd
            else:
                wd = os.getcwd()
            self._working_directory = wd
        self._all_files = scan_files(self._working_directory)

    def _populate(self) -> None:
        """Clear and repopulate the option list with filtered files.

        The display is capped at :data:`_DISPLAY_CAP` entries to keep
        the UI snappy, but the underlying file list contains every file
        in the project so filtering can match anywhere.
        """
        self._option_list.clear_options()

        if self._all_files is None:
            return

        shown = 0
        for relpath in self._all_files:
            # Case-insensitive substring match on the relative path
            if self._filter and self._filter not in relpath.casefold():
                continue
            icon = get_file_icon(relpath)
            prompt = f"  {icon}  {relpath}"
            self._option_list.add_option(Option(prompt, id=relpath))
            shown += 1
            if shown >= _DISPLAY_CAP:
                break

        # Highlight the first matching option
        if self._option_list.option_count > 0:
            self._option_list.highlighted = 0
        else:
            self._option_list.highlighted = None

    # ------------------------------------------------------------------
    # OptionList selection handler
    # ------------------------------------------------------------------

    def on_option_list_option_selected(
        self, event: OptionList.OptionSelected
    ) -> None:
        """Handle selection from the file palette."""
        event.stop()
        option = event.option
        if option and option.id:
            self.post_message(self.FileSelected(option.id))