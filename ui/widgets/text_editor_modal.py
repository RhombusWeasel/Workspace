"""Multi-line text editor modal — TextArea-based dialog for editing long text.

Returns the edited text on submit or ``None`` on cancel.  Suitable for
editing prompt templates, configuration values, and any multi-line text
content where a single-line ``InputModal`` is insufficient.

Provides:
* Full ``TextArea`` widget for multi-line editing with scrolling.
* OK / Cancel buttons.
* ``Ctrl+Enter`` shortcut to submit (in addition to the OK button).
* ``Escape`` to cancel.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, TextArea as TextAreaWidget


class TextEditorModal(ModalScreen[str | None]):
    """Modal screen with a multi-line text editor.

    Parameters
    ----------
    title:
        Heading shown at the top of the dialog.
    text:
        Initial text to load into the editor.
    language:
        Optional language for syntax highlighting (e.g. ``"markdown"``).
    read_only:
        If ``True``, the text area is read-only (for viewing only).
    """

    def __init__(
        self,
        title: str,
        text: str = "",
        language: str | None = None,
        read_only: bool = False,
    ) -> None:
        super().__init__()
        self._title = title
        self._text = text
        self._language = language
        self._read_only = read_only

    def compose(self) -> ComposeResult:
        with Vertical(id="text-editor-dialog"):
            yield TextAreaWidget(
                self._text,
                language=self._language,
                read_only=self._read_only,
                id="modal-textarea",
            )
            with Horizontal(id="text-editor-buttons"):
                yield Button("OK", variant="primary", id="btn-ok")
                yield Button("Cancel", variant="default", id="btn-cancel")

    def on_mount(self) -> None:
        self.query_one("#modal-textarea", TextAreaWidget).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "btn-ok":
            text = self.query_one("#modal-textarea", TextAreaWidget).text
            self.dismiss(text)
        else:
            self.dismiss(None)

    def on_key(self, event: object) -> None:
        """Handle Ctrl+Enter to submit, Escape to cancel."""
        from textual.events import Key

        if not isinstance(event, Key):
            return

        if event.key == "ctrl+enter":
            event.stop()
            text = self.query_one("#modal-textarea", TextAreaWidget).text
            self.dismiss(text)
        elif event.key == "escape":
            event.stop()
            self.dismiss(None)