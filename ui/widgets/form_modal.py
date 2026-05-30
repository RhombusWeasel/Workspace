"""Form modal — schema-driven multi-field dialog.

Takes a list of :class:`FormControl` descriptors and renders the correct
Textual widget for each field type.  Returns a ``dict[str, str]`` on
confirm or ``None`` on cancel.  All values are strings — the caller
parses/casts as needed.

Supported field types:

========= ================== =====================================
type      Textual widget     Notes
========= ================== =====================================
text      Input              Single-line text
password  Input              Masked input
number    Input              Validated as numeric on submit
select    Select             Dropdown, requires ``options``
textarea  Input + Edit btn   Opens :class:`TextEditorModal` for multi-line
toggle    Switch             Returns ``"true"`` / ``"false"``
taglist   Input              Comma-separated values
========= ================== =====================================

Example::

    from ui.widgets.form_modal import FormControl, FormModal

    controls = [
        FormControl(name="name", label="Agent Name", required=True),
        FormControl(name="provider", label="Provider", type="select",
                    options=["ollama-local", "openai-main"]),
        FormControl(name="model", label="Model", default="deepseek-r1"),
        FormControl(name="temperature", label="Temperature",
                    type="number", default="0.7", required=False),
        FormControl(name="template", label="System Prompt", type="textarea"),
        FormControl(name="tools", label="Tools", type="taglist",
                    required=False),
    ]

    result = await app.push_screen_wait(FormModal("New Agent", controls))
    if result is not None:
        # result = {"name": "...", "provider": "...", "model": "...", ...}
        agent_mgr.create_agent(**result)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Select, Switch


# ---------------------------------------------------------------------------
# FormControl — field descriptor
# ---------------------------------------------------------------------------


@dataclass
class FormControl:
    """Describes a single field in a :class:`FormModal`.

    Parameters
    ----------
    name:
        Machine key used in the returned dict (e.g. ``"provider"``).
    label:
        Human-readable label shown above the input.
    type:
        Input type: ``"text"``, ``"password"``, ``"number"``,
        ``"select"``, ``"textarea"``, ``"toggle"``, or ``"taglist"``.
    default:
        Pre-filled value.
    required:
        Whether the field must be non-empty to submit.
    options:
        Available choices for ``"select"`` type.
    placeholder:
        Placeholder text for empty inputs.
    min:
        Minimum value for ``"number"`` type (inclusive).
    max:
        Maximum value for ``"number"`` type (inclusive).
    """

    name: str
    label: str
    type: str = "text"
    default: str = ""
    required: bool = True
    options: list[str] | None = None
    placeholder: str = ""
    min: float | None = None
    max: float | None = None


# ---------------------------------------------------------------------------
# FormModal
# ---------------------------------------------------------------------------


class FormModal(ModalScreen[dict[str, str] | None]):
    """Schema-driven modal form.

    Renders one row per :class:`FormControl` with the appropriate
    Textual widget.  On confirm, returns a flat ``dict[str, str]`` mapping
    field names to their values.  On cancel, returns ``None``.

    Parameters
    ----------
    title:
        Heading shown at the top of the dialog.
    controls:
        List of field descriptors that drive form rendering.
    confirm_label:
        Text for the confirm button (default ``"OK"``).
    """

    def __init__(
        self,
        title: str,
        controls: list[FormControl],
        confirm_label: str = "OK",
    ) -> None:
        super().__init__()
        self._title = title
        self._controls = controls
        self._confirm_label = confirm_label
        # Track textarea values (they use a separate modal, not an in-form widget).
        # Pre-populate from control defaults so _collect() works pre-mount.
        self._textarea_values: dict[str, str] = {
            ctrl.name: ctrl.default
            for ctrl in controls
            if ctrl.type == "textarea"
        }

    # ------------------------------------------------------------------
    # Composition
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        with Vertical(id="form-dialog"):
            yield Label(self._title, id="form-title")
            with VerticalScroll(id="form-fields"):
                for ctrl in self._controls:
                    yield from self._compose_field(ctrl)
            # Status line for validation messages
            self._status = Label("", id="form-status")
            yield self._status
            with Horizontal(id="form-buttons"):
                yield Button(self._confirm_label, variant="primary", id="btn-form-ok")
                yield Button("Cancel", variant="default", id="btn-form-cancel")

    def _compose_field(self, ctrl: FormControl) -> ComposeResult:
        """Yield widgets for a single form control."""
        yield Label(ctrl.label, classes="form-field-label")

        if ctrl.type == "select":
            options = [(opt, opt) for opt in (ctrl.options or [])]
            # Use Select.NULL for no default, or the default value if provided.
            if ctrl.default and ctrl.default in (ctrl.options or []):
                default_val = ctrl.default
            else:
                default_val = Select.NULL
            yield Select(
                options=options,
                value=default_val,
                id=f"form-field-{ctrl.name}",
                classes="form-field-input",
            )

        elif ctrl.type == "toggle":
            yield Switch(
                value=str(ctrl.default).lower() in ("true", "1", "yes"),
                id=f"form-field-{ctrl.name}",
                classes="form-field-input",
            )

        elif ctrl.type == "textarea":
            # Show a preview input + edit button that opens TextEditorModal.
            initial = ctrl.default
            self._textarea_values[ctrl.name] = initial
            with Horizontal(classes="form-textarea-row"):
                yield Input(
                    value=self._preview(initial),
                    placeholder=ctrl.placeholder or "Click Edit…",
                    id=f"form-field-{ctrl.name}",
                    classes="form-field-input",
                    disabled=True,
                )
                yield Button(
                    "Edit",
                    id=f"form-btn-edit-{ctrl.name}",
                    classes="form-edit-btn",
                    variant="default",
                )

        else:
            # text, password, number, taglist — all use Input
            yield Input(
                value=ctrl.default,
                placeholder=ctrl.placeholder or ctrl.label,
                password=ctrl.type == "password",
                id=f"form-field-{ctrl.name}",
                classes="form-field-input",
            )

    @staticmethod
    def _preview(text: str, max_len: int = 60) -> str:
        """Truncate text for a single-line preview."""
        preview = text.replace("\n", " ↵ ")[:max_len]
        if len(text) > max_len:
            preview += "…"
        return preview

    # ------------------------------------------------------------------
    # Mount — focus first input
    # ------------------------------------------------------------------

    def on_mount(self) -> None:
        """Focus the first editable input widget."""
        try:
            inputs = self.query(".form-field-input")
            for widget in inputs:
                if isinstance(widget, Input) and not widget.disabled:
                    widget.focus()
                    return
            # Fallback: focus the first input even if disabled
            for widget in inputs:
                if isinstance(widget, Input):
                    widget.focus()
                    return
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        btn_id = event.button.id

        if btn_id == "btn-form-cancel":
            self.dismiss(None)
        elif btn_id == "btn-form-ok":
            result = self._collect()
            if result is not None:
                self.dismiss(result)
        elif btn_id and btn_id.startswith("form-btn-edit-"):
            field_name = btn_id[len("form-btn-edit-"):]
            self._open_textarea_editor(field_name)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Submit form on Enter in any input field."""
        event.stop()
        result = self._collect()
        if result is not None:
            self.dismiss(result)

    # ------------------------------------------------------------------
    # Textarea editor
    # ------------------------------------------------------------------

    def _open_textarea_editor(self, field_name: str) -> None:
        """Open a TextEditorModal for a textarea field."""
        from ui.widgets.text_editor_modal import TextEditorModal

        current = self._textarea_values.get(field_name, "")

        async def do_edit() -> None:
            modal = TextEditorModal(
                f"Edit: {field_name}",
                text=current,
                language="markdown",
            )
            result = await self.app.push_screen_wait(modal)
            if result is not None:
                self._textarea_values[field_name] = result
                # Update preview input
                try:
                    preview_input = self.query_one(
                        f"#form-field-{field_name}", Input
                    )
                    preview_input.value = self._preview(result)
                except Exception:
                    pass

        self.app.run_worker(do_edit())

    # ------------------------------------------------------------------
    # Collect & validate
    # ------------------------------------------------------------------

    def _collect(self) -> dict[str, str] | None:
        """Collect all field values, validate, and return a dict.

        Returns ``None`` if validation fails (sets the status label).
        """
        result: dict[str, str] = {}

        for ctrl in self._controls:
            value = self._get_value(ctrl)

            # Required check
            if ctrl.required and not value:
                self._set_status(f"'{ctrl.label}' is required.")
                return None

            # Type-specific validation
            if ctrl.type == "number" and value:
                try:
                    num = float(value)
                except (ValueError, TypeError):
                    self._set_status(f"'{ctrl.label}' must be a number.")
                    return None
                if ctrl.min is not None and num < ctrl.min:
                    self._set_status(
                        f"'{ctrl.label}' must be ≥ {ctrl.min}."
                    )
                    return None
                if ctrl.max is not None and num > ctrl.max:
                    self._set_status(
                        f"'{ctrl.label}' must be ≤ {ctrl.max}."
                    )
                    return None

            result[ctrl.name] = value

        return result

    def _set_status(self, message: str) -> None:
        """Set the status label text.  Safe to call before mount."""
        try:
            self._status.update(message)
        except Exception:
            pass  # Widget not mounted yet — validation message is lost.

    def _get_value(self, ctrl: FormControl) -> str:
        """Read the current value of a form control widget."""
        field_id = f"form-field-{ctrl.name}"

        if ctrl.type == "toggle":
            try:
                switch = self.query_one(f"#{field_id}", Switch)
                return "true" if switch.value else "false"
            except Exception:
                return ctrl.default

        if ctrl.type == "select":
            try:
                sel = self.query_one(f"#{field_id}", Select)
                val = sel.value
                if val is Select.NULL:
                    return ""
                return str(val)
            except Exception:
                return ctrl.default

        if ctrl.type == "textarea":
            return self._textarea_values.get(ctrl.name, ctrl.default)

        # text, password, number, taglist — all use Input
        try:
            inp = self.query_one(f"#{field_id}", Input)
            return (inp.value or "").strip()
        except Exception:
            return ctrl.default