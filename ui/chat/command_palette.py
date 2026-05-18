"""Command palette — a popup list of slash commands that appears above the input.

Shows all registered commands when the user types ``/``, filters as
they type, and allows selection with arrow keys, Enter, or click.
Each entry shows the command name and its description.

Styling matches the existing dark minimalist theme.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.message import Message
from textual.containers import Vertical
from textual.widgets import OptionList
from textual.widgets.option_list import Option

from core.commands import get_commands


class CommandPalette(Vertical):
    """A popup list of slash commands, filtered by the current input.

    Normally hidden.  Shown when the input starts with ``/``.
    Filters the command list as the user types more characters.
    Pressing Enter on a highlighted item fills the input and closes
    the palette.  Pressing Escape closes it without selecting.

    The host widget (:class:`~ui.chat.chat_input.ChatInput`) is
    responsible for showing/hiding the palette and feeding it the
    current input text via :meth:`update_filter`.
    """

    class CommandSelected(Message):
        """Posted when the user selects a command from the palette."""

        def __init__(self, command_name: str) -> None:
            super().__init__()
            self.command_name = command_name

    def __init__(self):
        super().__init__()
        self._filter: str = ""

    # ------------------------------------------------------------------
    # Composition
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        self._option_list = OptionList(id="cmd-option-list")
        yield self._option_list

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def show(self) -> None:
        """Show the palette and populate with all commands."""
        self._populate()
        self.add_class("-visible")
        # Highlight the first item if available
        self._option_list.highlighted = 0 if self._option_list.option_count > 0 else None

    def hide(self) -> None:
        """Hide the palette."""
        self.remove_class("-visible")

    @property
    def is_visible(self) -> bool:
        """Whether the palette is currently visible."""
        return self.has_class("-visible")

    def update_filter(self, text: str) -> None:
        """Update the filter text and refresh the command list.

        *text* should be the current input value (e.g. ``/he``).
        Commands whose name starts with the text after ``/`` are shown.
        If the text doesn't start with ``/``, the palette is hidden.
        """
        if not text.startswith("/"):
            self.hide()
            return

        self._filter = text[1:].casefold()  # strip leading /
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
        """Select the currently highlighted command.

        Returns the command name (without leading ``/``) or ``None``
        if the palette is not visible or nothing is highlighted.
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

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _populate(self) -> None:
        """Clear and repopulate the option list with filtered commands."""
        self._option_list.clear_options()

        cmds = get_commands()
        if not cmds:
            return

        for name in sorted(cmds.keys()):
            cmd = cmds[name]
            # Filter by the current prefix
            if self._filter and not name.casefold().startswith(self._filter):
                    continue
            # Prompt shows: command name and description
            prompt = f"  /{name}  —  {cmd.description}"
            self._option_list.add_option(Option(prompt, id=name))

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
        """Handle selection from the command palette."""
        event.stop()
        option = event.option
        if option and option.id:
            self.post_message(self.CommandSelected(option.id))