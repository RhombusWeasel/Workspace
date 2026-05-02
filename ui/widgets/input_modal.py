"""Input modal — single-line text prompt dialog.

Returns the entered text on submit or ``None`` on cancel.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label


class InputModal(ModalScreen[str | None]):
    """Modal dialog that prompts for a single line of text.

    Parameters
    ----------
    prompt:
        Instructional text shown above the input field.
    label:
        Short label for the field.
    default:
        Pre-filled value (empty by default).
    password:
        If ``True``, the input is masked.
    """

    CSS = """
    InputModal {
        align: center middle;
    }

    #input-dialog {
        width: 60;
        height: auto;
        padding: 1 2;
        background: $surface;
        border: thick $primary;
    }

    #input-dialog Label {
        width: 100%;
        margin-bottom: 1;
    }

    #input-dialog Input {
        width: 100%;
        margin-bottom: 1;
    }

    #input-dialog Horizontal {
        width: 100%;
        align-horizontal: right;
    }

    #input-dialog Button {
        margin-left: 1;
    }
    """

    def __init__(
        self,
        prompt: str,
        label: str = "",
        default: str = "",
        password: bool = False,
    ) -> None:
        super().__init__()
        self._prompt = prompt
        self._label = label
        self._default = default
        self._password = password

    def compose(self) -> ComposeResult:
        yield Label(self._prompt, id="input-dialog")
        yield Input(
            value=self._default,
            placeholder=self._label,
            password=self._password,
            id="modal-input",
        )
        with Horizontal():
            yield Button("OK", variant="primary", id="btn-ok")
            yield Button("Cancel", variant="default", id="btn-cancel")

    def on_mount(self) -> None:
        self.query_one("#modal-input", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-ok":
            value = self.query_one("#modal-input", Input).value
            self.dismiss(value)
        else:
            self.dismiss(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value)
