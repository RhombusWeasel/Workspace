"""Connection form modal — dynamic multi-field dialog for adding/editing DB connections.

The form fields are driven by the selected provider's ``form_fields()`` method,
so adding a new provider (e.g. PostgreSQL) automatically generates the right
fields without any UI changes.

For SQLite, this renders a single file-path field.  Future providers like
PostgreSQL will add host, port, database, username, and password fields.

Returns a ``(name, provider_type, params, sensitive_params)`` dict on submit
or ``None`` on cancel.
"""

from __future__ import annotations

import os
from typing import Any

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Select

from core.db_connections import (
    ConnectionInfo,
    DBProvider,
    FormField,
    get_provider,
    list_provider_types,
)


# ---------------------------------------------------------------------------
# Connection form modal
# ---------------------------------------------------------------------------


class ConnectionFormModal(ModalScreen[dict[str, Any] | None]):
    """Modal dialog for adding or editing a database connection.

    Dynamically renders form fields based on the selected provider.
    Includes a "Test Connection" button that attempts to connect and
    reports success or failure.

    Parameters
    ----------
    edit_connection:
        If provided, pre-fill the form with this connection's data
        (edit mode).  If ``None``, the form is in "add" mode.
    """

    def __init__(
        self,
        edit_connection: ConnectionInfo | None = None,
    ) -> None:
        super().__init__()
        self._edit = edit_connection
        self._selected_provider: str = (
            edit_connection.provider_type if edit_connection
            else (list_provider_types()[0] if list_provider_types() else "sqlite")
        )
        # Maps field name → current value (pre-filled for edit, or defaults)
        self._field_values: dict[str, str] = {}
        # Initialize field values from edit connection or defaults
        self._init_field_values()

    def _init_field_values(self) -> None:
        """Pre-fill field values from the edit connection or provider defaults."""
        provider_cls = get_provider(self._selected_provider)
        if provider_cls is None:
            return
        for field in provider_cls.form_fields():
            if self._edit and field.name in self._edit.params:
                self._field_values[field.name] = self._edit.params[field.name]
            else:
                self._field_values[field.name] = field.default

    def compose(self) -> ComposeResult:
        title = (
            f"Edit Connection: {self._edit.name}"
            if self._edit
            else "Add Database Connection"
        )

        with Vertical(id="connection-form-dialog"):
            yield Label(title, id="connection-form-title")

            # Connection name (always present)
            yield Label("Name:")
            name_default = self._edit.name if self._edit else ""
            self._name_input = Input(
                value=name_default,
                placeholder="Connection name",
                id="connection-name",
            )
            yield self._name_input

            # Provider type selector
            yield Label("Type:")
            provider_options = [(pt, pt) for pt in list_provider_types()]
            self._type_select = Select(
                options=provider_options,
                value=self._selected_provider,
                id="connection-type",
            )
            yield self._type_select

            # Dynamic fields container
            with VerticalScroll(id="connection-fields"):
                yield from self._compose_fields()

            # Status label for test connection feedback
            self._status = Label("", id="connection-status")
            yield self._status

            # Buttons
            with Horizontal(id="connection-form-buttons"):
                yield Button("Test Connection", variant="default", id="btn-test")
                yield Button("Save", variant="primary", id="btn-save")
                yield Button("Cancel", variant="default", id="btn-cancel")

    def _compose_fields(self) -> ComposeResult:
        """Render dynamic fields for the currently selected provider."""
        provider_cls = get_provider(self._selected_provider)
        if provider_cls is None:
            return
        for field in provider_cls.form_fields():
            # Section header for provider-specific fields
            yield Label(f"{field.label}:")
            value = self._field_values.get(field.name, field.default)
            input_widget = Input(
                value=value,
                placeholder=field.label,
                password=field.type == "password",
                id=f"connection-field-{field.name}",
            )
            input_widget.field_meta = field  # type: ignore[attr-defined]
            yield input_widget

            # For file-type fields, add a browse button
            if field.type == "file":
                yield Button(
                    "Browse",
                    id=f"connection-browse-{field.name}",
                    classes="connection-browse-btn",
                )

    def _rebuild_fields(self, new_provider: str) -> None:
        """Re-build the dynamic fields when the provider type changes."""
        self._selected_provider = new_provider
        self._field_values.clear()
        self._init_field_values()

        try:
            fields_container = self.query_one("#connection-fields", VerticalScroll)
            # Remove all children from fields container
            for child in list(fields_container.children):
                child.remove()

            # Re-add fields
            for field_meta in (get_provider(new_provider) or SQLiteProvider).form_fields():
                label = Label(f"{field_meta.label}:")
                value = self._field_values.get(field_meta.name, field_meta.default)
                input_widget = Input(
                    value=value,
                    placeholder=field_meta.label,
                    password=field_meta.type == "password",
                    id=f"connection-field-{field_meta.name}",
                )
                input_widget.field_meta = field_meta  # type: ignore[attr-defined]
                fields_container.mount(label)
                fields_container.mount(input_widget)

                if field_meta.type == "file":
                    browse_btn = Button(
                        "Browse",
                        id=f"connection-browse-{field_meta.name}",
                        classes="connection-browse-btn",
                    )
                    fields_container.mount(browse_btn)

        except Exception:
            pass

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def on_select_changed(self, event: Select.Changed) -> None:
        """Rebuild fields when the provider type changes."""
        if event.select.id == "connection-type":
            new_provider = str(event.value)
            if new_provider != self._selected_provider:
                self._rebuild_fields(new_provider)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        btn_id = event.button.id

        if btn_id == "btn-cancel":
            self.dismiss(None)

        elif btn_id == "btn-save":
            result = self._collect_form_data()
            if result is not None:
                self.dismiss(result)

        elif btn_id == "btn-test":
            self._test_connection()

        elif btn_id and btn_id.startswith("connection-browse-"):
            field_name = btn_id[len("connection-browse-"):]
            self._browse_file(field_name)

    def _browse_file(self, field_name: str) -> None:
        """Open a file-picker-style input for file-type fields."""
        # Use a simple input modal for now; can be upgraded to a
        # proper file picker in the future.
        from ui.widgets.input_modal import InputModal

        current_value = self._field_values.get(field_name, "")

        async def do_browse() -> None:
            modal = InputModal(
                f"Select file for {field_name}:",
                "File path",
                default=current_value,
            )
            result = await self.app.push_screen_wait(modal)
            if result is not None:
                self._field_values[field_name] = result
                # Update the corresponding input widget
                try:
                    input_widget = self.query_one(
                        f"#connection-field-{field_name}", Input
                    )
                    input_widget.value = result
                except Exception:
                    pass

        self.app.run_worker(do_browse())

    def _collect_form_data(self) -> dict[str, Any] | None:
        """Collect form data and return a dict, or None if validation fails."""
        name = self._name_input.value.strip()
        if not name:
            self._status.update("Please enter a connection name.")
            return None

        provider_type = self._selected_provider
        provider_cls = get_provider(provider_type)
        if provider_cls is None:
            self._status.update(f"Unknown provider: {provider_type}")
            return None

        params: dict[str, str] = {}
        sensitive_params: dict[str, str] = {}

        for field in provider_cls.form_fields():
            try:
                input_widget = self.query_one(
                    f"#connection-field-{field.name}", Input
                )
                value = input_widget.value.strip() if input_widget.value else ""
            except Exception:
                value = self._field_values.get(field.name, "")

            if field.required and not value:
                self._status.update(f"Field '{field.label}' is required.")
                return None

            if field.sensitive:
                sensitive_params[field.name] = value
            else:
                params[field.name] = value

        return {
            "name": name,
            "provider_type": provider_type,
            "params": params,
            "sensitive_params": sensitive_params,
        }

    def _test_connection(self) -> None:
        """Attempt to connect with the current form values."""
        data = self._collect_form_data()
        if data is None:
            return

        provider_cls = get_provider(data["provider_type"])
        if provider_cls is None:
            self._status.update("Unknown provider type.")
            return

        # Merge params for the connection attempt
        full_params = dict(data["params"])
        full_params.update(data["sensitive_params"])

        try:
            conn = provider_cls.connect(full_params)
            provider_cls.disconnect(conn)
            self._status.update("✓ Connection successful!")
        except Exception as e:
            self._status.update(f"✗ Connection failed: {e}")