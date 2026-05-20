"""File suggester — provides inline completion for ``@`` file mentions.

A Textual ``Suggester`` that offers file path suggestions when the
input contains ``@`` followed by a partial filename.

The suggester lazily scans the working directory on first use and
caches the results.  It uses the same :func:`scan_files` function
as :class:`~plugins.chat.file_palette.FilePalette` for consistency.

Only suggests when the input contains ``@`` — for normal text
or ``/`` commands the suggester returns ``None``.
"""

from __future__ import annotations

import os

from textual.suggester import Suggester

from plugins.chat.file_palette import scan_files


class FileSuggester(Suggester):
    """Suggests file paths when the input contains ``@``.

    Detects the last ``@`` in the current input value and suggests
    a matching file path.  Uses case-insensitive substring matching
    on the relative path.

    The file list is lazily scanned on first suggestion request and
    cached thereafter.  Set the ``working_directory`` attribute to
    configure which directory to scan.
    """

    def __init__(self, working_directory: str = "") -> None:
        super().__init__(use_cache=False, case_sensitive=False)
        self._working_directory = working_directory
        self._all_files: list[str] | None = None

    @property
    def working_directory(self) -> str:
        """The directory to scan for files."""
        return self._working_directory

    @working_directory.setter
    def working_directory(self, wd: str) -> None:
        """Update the working directory, invalidating the cache on change."""
        if wd != self._working_directory:
            self._all_files = None
            self._working_directory = wd

    def _ensure_scanned(self) -> None:
        """Scan the working directory if the cache is cold."""
        if self._all_files is not None:
            return
        wd = self._working_directory or os.getcwd()
        self._all_files = scan_files(wd)

    async def get_suggestion(self, value: str) -> str | None:
        """Return a matching file suggestion, or ``None``.

        If *value* contains ``@``, extracts the query after the last
        ``@`` and looks for a file whose relative path contains the
        query (case-insensitive substring match).  Returns the
        ``@filepath`` string for the first match.

        If *value* doesn't contain ``@``, returns ``None``.
        """
        at_idx = value.rfind("@")
        if at_idx == -1:
            return None

        # Extract the partial query after the last @
        after_at = value[at_idx + 1 :]
        # Only consider text up to the first space as the query token
        space_idx = after_at.find(" ")
        if space_idx != -1:
            return None  # Space after @ means the mention is complete
        partial = after_at.casefold()

        self._ensure_scanned()

        if self._all_files is None:
            return None

        # Find the first file whose path contains the partial query
        for relpath in self._all_files:
            if partial in relpath.casefold():
                return f"@{relpath}"

        return None