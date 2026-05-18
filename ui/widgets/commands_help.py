"""Commands help — modal listing available slash commands."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.widgets import Label
from textual.containers import VerticalScroll

from core.commands import get_commands


class CommandsHelp(ModalScreen[None]):
    """Modal overlay showing all registered slash commands.

    Press ``Escape`` to dismiss.
    """

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="commands-dialog"):
            yield Label("Slash Commands", id="commands-title")

            cmds = get_commands()
            if cmds:
                lines = []
                for name in sorted(cmds):
                    cmd = cmds[name]
                    lines.append(f" /{name}  —  {cmd.description}")
                yield Label("\n".join(lines), id="commands-content")
            else:
                yield Label("No commands registered.", id="commands-content")

            yield Label("Escape to close", id="commands-hint")

    def on_key(self, event) -> None:
        if event.key == "escape":
            self.dismiss(None)
