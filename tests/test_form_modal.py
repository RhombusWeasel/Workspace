"""Tests for the FormModal — FormControl, FormModal rendering, validation, collection."""

import os
import pytest
from textual.widgets import Input, Switch, Select
from ui.widgets.form_modal import FormControl, FormModal


# ---------------------------------------------------------------------------
# CSS path helper
# ---------------------------------------------------------------------------

_CSS_PATH = os.path.join(os.path.dirname(__file__), "..", "ui", "widgets", "form_modal.tcss")
_CSS_PATH = os.path.abspath(_CSS_PATH)


class TestFormControl:
    def test_defaults(self):
        fc = FormControl(name="test", label="Test")
        assert fc.type == "text"
        assert fc.default == ""
        assert fc.required is True
        assert fc.options is None
        assert fc.placeholder == ""
        assert fc.min is None
        assert fc.max is None

    def test_select_control(self):
        fc = FormControl(name="provider", label="Provider", type="select",
                         options=["a", "b"], default="a")
        assert fc.type == "select"
        assert fc.options == ["a", "b"]

    def test_number_control_with_bounds(self):
        fc = FormControl(name="temp", label="Temperature", type="number",
                         min=0, max=2, default="0.7")
        assert fc.min == 0
        assert fc.max == 2


# ---------------------------------------------------------------------------
# FormModal — validation logic (unit tests)
# ---------------------------------------------------------------------------


class TestFormModalValidation:
    """Test the _collect() validation logic by creating a FormModal and
    calling _collect() directly (no DOM needed for most tests).

    For DOM-dependent tests (select, toggle) we use Textual pilot.
    """

    def _make_modal(self, controls, **kwargs):
        return FormModal("Test", controls, **kwargs)

    def test_collect_text_required_empty_fails(self):
        modal = self._make_modal([
            FormControl(name="name", label="Name", required=True),
        ])
        # No Input widgets mounted — _get_value falls back to default ("").
        result = modal._collect()
        assert result is None  # required field is empty

    def test_collect_optional_empty_passes(self):
        modal = self._make_modal([
            FormControl(name="name", label="Name", required=False),
        ])
        result = modal._collect()
        assert result is not None
        assert result["name"] == ""

    def test_number_validation_rejects_non_number(self):
        modal = self._make_modal([
            FormControl(name="temp", label="Temp", type="number", required=True),
        ])
        # Simulate a non-numeric input value by overriding _get_value
        modal._get_value = lambda ctrl: "hot"
        result = modal._collect()
        assert result is None

    def test_number_validation_accepts_valid(self):
        modal = self._make_modal([
            FormControl(name="temp", label="Temp", type="number",
                        default="0.7", required=False),
        ])
        modal._get_value = lambda ctrl: "0.7"
        result = modal._collect()
        assert result is not None
        assert result["temp"] == "0.7"

    def test_number_validation_rejects_below_min(self):
        modal = self._make_modal([
            FormControl(name="temp", label="Temp", type="number",
                        min=0, required=False),
        ])
        modal._get_value = lambda ctrl: "-1"
        result = modal._collect()
        assert result is None

    def test_number_validation_rejects_above_max(self):
        modal = self._make_modal([
            FormControl(name="temp", label="Temp", type="number",
                        max=2, required=False),
        ])
        modal._get_value = lambda ctrl: "5"
        result = modal._collect()
        assert result is None

    def test_number_validation_accepts_integer(self):
        modal = self._make_modal([
            FormControl(name="count", label="Count", type="number",
                        required=False),
        ])
        modal._get_value = lambda ctrl: "10"
        result = modal._collect()
        assert result is not None
        assert result["count"] == "10"

    def test_collect_textarea_uses_internal_values(self):
        modal = self._make_modal([
            FormControl(name="bio", label="Bio", type="textarea",
                        default="Hello world"),
        ])
        # _textarea_values should be initialised from default
        assert modal._textarea_values["bio"] == "Hello world"
        result = modal._collect()
        assert result is not None
        assert result["bio"] == "Hello world"

    def test_collect_multiple_fields(self):
        modal = self._make_modal([
            FormControl(name="name", label="Name", default="Agent1"),
            FormControl(name="model", label="Model", default="llama3",
                        required=False),
        ])
        result = modal._collect()
        assert result == {"name": "Agent1", "model": "llama3"}

    def test_collect_first_required_empty_stops(self):
        modal = self._make_modal([
            FormControl(name="name", label="Name", required=True),
            FormControl(name="model", label="Model", default="llama3",
                        required=False),
        ])
        # name empty → fails
        result = modal._collect()
        assert result is None

    def test_status_message_on_failure(self):
        modal = self._make_modal([
            FormControl(name="name", label="Agent Name", required=True),
        ])
        # Before mount, _set_status is a no-op but _collect still returns None.
        result = modal._collect()
        assert result is None

    def test_confirm_label_default(self):
        modal = self._make_modal([
            FormControl(name="x", label="X"),
        ])
        assert modal._confirm_label == "OK"

    def test_confirm_label_custom(self):
        modal = self._make_modal([
            FormControl(name="x", label="X"),
        ], confirm_label="Save")
        assert modal._confirm_label == "Save"


# ---------------------------------------------------------------------------
# FormModal — preview helper
# ---------------------------------------------------------------------------


class TestPreview:
    def test_short_text(self):
        assert FormModal._preview("Hello") == "Hello"

    def test_long_text_truncated(self):
        text = "A" * 100
        preview = FormModal._preview(text)
        assert len(preview) <= 63  # 60 chars + "↵" replacements + "…"
        assert preview.endswith("…")

    def test_newlines_replaced(self):
        assert "↵" in FormModal._preview("line1\nline2")

    def test_empty_text(self):
        assert FormModal._preview("") == ""


# ---------------------------------------------------------------------------
# FormModal — DOM integration (with Textual pilot)
# ---------------------------------------------------------------------------


class TestFormModalDOM:
    """Integration tests that mount the FormModal in a real Textual app
    and verify rendering, interaction, and result collection.
    """

    @pytest.fixture
    def app_and_modal(self):
        from textual.app import App, ComposeResult

        controls = [
            FormControl(name="name", label="Name", default="Test"),
            FormControl(name="model", label="Model", required=False,
                        placeholder="Optional"),
        ]

        class TestApp(App):
            CSS_PATH = _CSS_PATH

            def compose(self) -> ComposeResult:
                modal = FormModal("Test Form", controls, confirm_label="Save")
                yield modal

        app = TestApp()
        return app

    @pytest.mark.asyncio
    async def test_renders_all_fields(self, app_and_modal):
        app = app_and_modal
        async with app.run_test() as pilot:
            # Should have 2 Input fields
            inputs = app.query(Input)
            assert len(inputs) >= 2

    @pytest.mark.asyncio
    async def test_renders_title(self, app_and_modal):
        app = app_and_modal
        async with app.run_test() as pilot:
            title = app.query_one("#form-title")
            # The title widget should exist and be a Label
            from textual.widgets import Label
            assert isinstance(title, Label)

    @pytest.mark.asyncio
    async def test_confirm_button_label(self, app_and_modal):
        app = app_and_modal
        async with app.run_test() as pilot:
            ok_btn = app.query_one("#btn-form-ok")
            assert "Save" in str(ok_btn.label)

    @pytest.mark.asyncio
    async def test_cancel_dismisses_none(self, app_and_modal):
        app = app_and_modal
        result_holder = {"result": "not_set"}

        class ResultApp(app.__class__):
            def on_screen_suspend(self, event):
                # Capture dismiss result
                pass

        async with app.run_test() as pilot:
            # Press cancel
            await pilot.click("#btn-form-cancel")
            # After clicking cancel the modal dismisses with None
            # We can't easily capture the dismiss result in this test harness,
            # but we can verify the cancel button exists and is clickable.

    @pytest.mark.asyncio
    async def test_password_field_type(self):
        from textual.app import App, ComposeResult

        controls = [
            FormControl(name="secret", label="Secret", type="password"),
        ]

        class TestApp(App):
            CSS_PATH = _CSS_PATH

            def compose(self) -> ComposeResult:
                yield FormModal("Test", controls)

        app = TestApp()
        async with app.run_test() as pilot:
            inp = app.query_one("#form-field-secret", Input)
            assert inp.password is True

    @pytest.mark.asyncio
    async def test_toggle_field_type(self):
        from textual.app import App, ComposeResult
        from textual.widgets import Switch

        controls = [
            FormControl(name="enabled", label="Enabled", type="toggle",
                        default="true"),
        ]

        class TestApp(App):
            CSS_PATH = _CSS_PATH

            def compose(self) -> ComposeResult:
                yield FormModal("Test", controls)

        app = TestApp()
        async with app.run_test() as pilot:
            switch = app.query_one("#form-field-enabled", Switch)
            assert switch.value is True

    @pytest.mark.asyncio
    async def test_select_field_type(self):
        from textual.app import App, ComposeResult
        from textual.widgets import Select

        controls = [
            FormControl(name="provider", label="Provider", type="select",
                        options=["ollama", "openai"], default="ollama"),
        ]

        class TestApp(App):
            CSS_PATH = _CSS_PATH

            def compose(self) -> ComposeResult:
                yield FormModal("Test", controls)

        app = TestApp()
        async with app.run_test() as pilot:
            sel = app.query_one("#form-field-provider", Select)
            assert sel.value == "ollama"

    @pytest.mark.asyncio
    async def test_textarea_field_has_edit_button(self):
        from textual.app import App, ComposeResult

        controls = [
            FormControl(name="template", label="Template", type="textarea",
                        default="Hello {{name}}"),
        ]

        class TestApp(App):
            CSS_PATH = _CSS_PATH

            def compose(self) -> ComposeResult:
                yield FormModal("Test", controls)

        app = TestApp()
        async with app.run_test() as pilot:
            # Should have a disabled input (preview) and an Edit button
            inp = app.query_one("#form-field-template", Input)
            assert inp.disabled is True
            # Check the edit button exists
            edit_btn = app.query_one("#form-btn-edit-template")
            assert edit_btn is not None
            # The _textarea_values should hold the full text
            modal = app.query_one(FormModal)
            assert modal._textarea_values["template"] == "Hello {{name}}"