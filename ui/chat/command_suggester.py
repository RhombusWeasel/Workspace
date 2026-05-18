"""Command suggester — provides tab-completion for slash commands.

A Textual ``Suggester`` that dynamically reads from the command registry
so suggestions are always up-to-date (even after commands are loaded
during bootstrap or added by skills at runtime).

Only suggests when the input starts with ``/`` — for normal text
the suggester returns ``None``.
"""

from __future__ import annotations

from textual.suggester import Suggester


class CommandSuggester(Suggester):
    """Suggests slash command names when the input starts with ``/``.

    Queries :func:`core.commands.list_commands` on every suggestion
    request so newly-registered commands appear immediately.  Only
    activates when the current input value starts with ``/``.
    """

    def __init__(self) -> None:
        super().__init__(use_cache=False, case_sensitive=False)

    async def get_suggestion(self, value: str) -> str | None:
        """Return a matching command suggestion, or ``None``.

        If *value* starts with ``/``, looks for a command whose name
        begins with the text after the slash (case-insensitive).  Returns
        the full ``/command_name`` string for the first match.

        If *value* doesn't start with ``/``, returns ``None`` (no
        suggestion for normal chat text).
        """
        if not value.startswith("/"):
            return None

        # Get the partial command name (everything after /).
        # The Suggester base class may casefold the value when
        # case_sensitive=False, so we casefold both sides.
        partial = value[1:].casefold()

        # Import here to avoid circular imports at module load time.
        from core.commands import list_commands

        commands = list_commands()

        # Find the first command that starts with the partial text
        for cmd_name in commands:
            if cmd_name.casefold().startswith(partial):
                return f"/{cmd_name}"

        return None