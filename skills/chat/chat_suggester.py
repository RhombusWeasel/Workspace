"""Chat suggester — combined inline completion for slash commands and file paths.

A Textual ``Suggester`` that delegates to :class:`CommandSuggester` when the
input starts with ``/`` and to :class:`FileSuggester` when the input contains
``@``.  For normal text (no ``/`` or ``@``), returns ``None``.

.. note::

    This suggester is designed for use with Textual ``Input`` widgets.
    For the ``ChatTextArea`` (which extends ``TextArea``), inline suggestions
    are handled directly by overriding ``update_suggestion()`` in
    :class:`ChatTextArea`, because ``TextArea`` uses a ``suggestion`` reactive
    attribute rather than the ``Suggester`` protocol.

    This class is kept for potential use with other input widgets or for
    future integration if ``TextArea`` gains native ``Suggester`` support.
"""

from __future__ import annotations

from textual.suggester import Suggester

from skills.chat.command_suggester import CommandSuggester
from skills.chat.file_suggester import FileSuggester


class ChatSuggester(Suggester):
    """Combined suggester that provides inline completions for ``/`` commands
    and ``@`` file mentions.

    Delegates to :class:`CommandSuggester` when the input starts with ``/``,
    and to :class:`FileSuggester` when the input contains ``@``.  For normal
    text, returns ``None`` (no suggestion).

    The working directory for file scanning can be set via the
    ``working_directory`` property, which is forwarded to the underlying
    :class:`FileSuggester`.
    """

    def __init__(self, working_directory: str = "") -> None:
        super().__init__(use_cache=False, case_sensitive=False)
        self._command_suggester = CommandSuggester()
        self._file_suggester = FileSuggester(working_directory)

    @property
    def working_directory(self) -> str:
        """The directory to scan for files (forwarded to FileSuggester)."""
        return self._file_suggester.working_directory

    @working_directory.setter
    def working_directory(self, wd: str) -> None:
        """Update the working directory, invalidating the file cache on change."""
        self._file_suggester.working_directory = wd

    async def get_suggestion(self, value: str) -> str | None:
        """Return a completion suggestion based on the current input.

        * If *value* starts with ``/``, delegates to :class:`CommandSuggester`.
        * If *value* contains ``@``, delegates to :class:`FileSuggester`.
        * Otherwise, returns ``None``.

        Note: *value* is already casefolded by the ``Suggester`` base class
        when ``case_sensitive=False`` (the default).  The delegate suggesters
        must handle casefolded input correctly.
        """
        if value.startswith("/"):
            return await self._command_suggester.get_suggestion(value)
        if "@" in value:
            return await self._file_suggester.get_suggestion(value)
        return None