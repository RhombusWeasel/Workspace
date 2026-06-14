"""Confirm modal — user-confirmation dialog for destructive tool actions.

Shows a title, a scrollable body (command or diff preview), and
Confirm / Cancel buttons.  Returns ``True`` when confirmed, ``None``
when cancelled or dismissed.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import VerticalScroll, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Static


class ConfirmModal(ModalScreen[bool | None]):
    """Modal screen that asks the user to confirm an action.

    Parameters
    ----------
    title:
        Heading shown at the top (e.g. "Run this command?").
    body:
        The content to display — a command string, file diff, etc.
    confirm_label:
        Text for the confirm button (default ``"Confirm"``).
    """

    def __init__(
        self,
        title: str,
        body: str,
        confirm_label: str = "Confirm",
    ):
        super().__init__()
        self._title = title
        self._body = body
        self._confirm_label = confirm_label

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="confirm-dialog"):
            yield Static(self._title, id="confirm-title", markup=False)
            yield Static(self._body, id="confirm-body", markup=False)
            with Horizontal(id="confirm-buttons"):
                yield Button(self._confirm_label, variant="primary", id="btn-confirm")
                yield Button("Cancel", variant="default", id="btn-cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "btn-confirm":
            self.dismiss(True)
        else:
            self.dismiss(None)
