"""Config panel — sidebar tab displaying and editing configuration values.

Uses the generic :class:`~ui.tree.tree.Tree` to show config keys
hierarchically.  Scalar leaf nodes display an **inline editor** whose
type matches the value:

* ``bool``   → :class:`~textual.widgets.Switch` (toggle)
* ``str``    → :class:`~textual.widgets.Input` (text field)
* ``int``    → :class:`~textual.widgets.Input` (integer field)
* ``float``  → :class:`~textual.widgets.Input` (decimal field)
* ``None``   → :class:`~textual.widgets.Input` (type ``null`` / ``none``)

List branch nodes display a **➕ button** to add new items.
For flat lists (scalars), an :class:`~ui.widgets.input_modal.InputModal`
collects the value.  For lists of dicts, a
:class:`~ui.widgets.form_modal.FormModal` collects the fields inferred
from the first existing item.

Changes are applied immediately via :meth:`Config.set()`.  Editing
``ui.theme`` also applies the theme live via ``app.theme``, which
triggers ``WorkspaceApp._watch_theme`` to persist the choice.

Tree structure::

    Configuration
    ├── session
    │   ├── provider  [ollama]
    │   └── model     [llama3]
    ├── db
    │   ├── default_page_size  [200]
    │   └── connections ＋
    │       ├── 0: My DB
    │       │   ├── id  [abc123]
    │       │   ├── name  [My DB]
    │       │   └── ...
    └── ui
        └── theme  ⬤ haxor
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from textual.app import ComposeResult
from textual.containers import Container
from textual.widgets import Input, Switch

from core.config import Config
from ui.sidebar.registry import register_sidebar_tab
from ui.tree.tree import Tree
from ui.tree.tree_row import TreeNode, RowButton
from ui.widgets.form_modal import FormControl, FormModal
from ui.widgets.input_modal import InputModal
from utils.icons import PLUS

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ADD = "config-add"


# ---------------------------------------------------------------------------
# Value formatting / coercion
# ---------------------------------------------------------------------------


def _display_value(value: Any) -> str:
    """Return a short string for the inline editor's initial value."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return ""  # Switch shows state visually; no text needed
    if isinstance(value, str):
        return value
    return repr(value)


def _coerce_value(raw: str, original: Any) -> Any:
    """Parse *raw* (from inline input) into a Python value.

    Attempts to match the type of *original*:
    * ``bool`` → ``"true"`` / ``"false"`` (case-insensitive) → :class:`bool`
    * ``int`` → :func:`int` parse
    * ``float`` → :func:`float` parse
    * ``None`` → ``"null"`` / ``"none"`` (case-insensitive) → ``None``
    * Otherwise → raw string
    """
    stripped = raw.strip()
    lowered = stripped.lower()

    # null / none
    if lowered in ("null", "none"):
        return None

    # bool — handled by Switch, not input; included for completeness
    if lowered == "true":
        return True
    if lowered == "false":
        return False

    # If original was a number, try to parse as number
    if isinstance(original, bool):
        # bool is a subclass of int; don't try numeric parse
        return stripped
    if isinstance(original, int):
        try:
            return int(stripped)
        except ValueError:
            pass
    if isinstance(original, float):
        try:
            return float(stripped)
        except ValueError:
            pass

    return stripped


# ---------------------------------------------------------------------------
# Inline editor helpers
# ---------------------------------------------------------------------------


def _make_inline_edit(
    dot_key: str,
    value: Any,
    config: Config,
    panel: ConfigPanel,
) -> Switch | Input:
    """Create the right inline editor widget for a config value.

    Booleans get a :class:`Switch`; everything else gets an :class:`Input`.
    The returned widget is pre-wired with metadata (``_cfg_key``,
    ``_cfg_original``, ``_cfg_panel``) so the panel's event handlers
    can persist changes via :meth:`Config.set()`.
    """
    node_id = ConfigPanel._sanitize_id(dot_key)

    if isinstance(value, bool):
        widget = Switch(value=value, id=f"cfg-sw-{node_id}")
        widget._cfg_key = dot_key  # type: ignore[attr-defined]
        widget._cfg_panel = panel  # type: ignore[attr-defined]
        return widget

    # String / int / float / None → Input
    input_type: str = "text"
    placeholder = ""

    if isinstance(value, int) and not isinstance(value, bool):
        input_type = "integer"
        placeholder = "0"
    elif isinstance(value, float):
        input_type = "number"
        placeholder = "0.0"
    elif value is None:
        placeholder = "null"

    initial = _display_value(value)
    widget = Input(
        value=initial,
        placeholder=placeholder,
        type=input_type,
        id=f"cfg-in-{node_id}",
        compact=True,
    )
    # Store metadata on the widget so the handler can look it up
    widget._cfg_key = dot_key  # type: ignore[attr-defined]
    widget._cfg_original = value  # type: ignore[attr-defined]
    widget._cfg_panel = panel  # type: ignore[attr-defined]
    return widget


def _infer_add_button(list_key: str, items: list) -> list[RowButton]:
    """Return a ➕ add-button for list nodes that support adding entries.

    Empty flat lists (e.g. ``[]``) get a button but the scalar type is
    unknown — the user enters a free-form value.
    """
    return [RowButton(_ADD, PLUS, "config-add")]


def _infer_dict_fields(template: dict[str, Any]) -> list[FormControl]:
    """Build :class:`FormControl` descriptors from a template dict.

    Used when adding a new dict to a list — the first existing item
    serves as the template for what fields the new entry needs.
    Nested dicts are represented as a ``textarea`` field with a
    JSON hint since :class:`FormModal` handles flat key-value pairs.
    """
    controls: list[FormControl] = []
    for key, value in template.items():
        if isinstance(value, dict):
            # Nested dict — offer a text area with a JSON hint
            controls.append(
                FormControl(
                    name=key,
                    label=key,
                    type="textarea",
                    default="{}",
                    required=False,
                    placeholder="JSON object",
                )
            )
        elif isinstance(value, bool):
            controls.append(
                FormControl(
                    name=key,
                    label=key,
                    type="toggle",
                    default="false",
                    required=False,
                )
            )
        elif isinstance(value, int):
            controls.append(
                FormControl(
                    name=key,
                    label=key,
                    type="number",
                    default="0",
                    required=False,
                )
            )
        else:
            controls.append(
                FormControl(
                    name=key,
                    label=key,
                    type="text",
                    default="",
                    required=False,
                )
            )
    return controls


# ---------------------------------------------------------------------------
# ConfigPanel
# ---------------------------------------------------------------------------


@register_sidebar_tab(name="config", icon="", side="right",
                       tooltip="Config")
class ConfigPanel(Container):
    """Sidebar panel showing configuration as an editable tree.

    Provides:
    * :meth:`set_config` — bind a :class:`Config` instance and rebuild.
    * Inline editors on every leaf node — changes auto-persist.
    * ➕ add button on list nodes — adds new entries.
    """

    def __init__(self):
        super().__init__()
        self._config: Config | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_config(self, cfg: Config | None) -> None:
        """Bind a :class:`Config` instance and rebuild the tree."""
        self._config = cfg
        if self.is_mounted:
            self._rebuild()

    # ------------------------------------------------------------------
    # Compose
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        self._tree = Tree(TreeNode("config-root", "Configuration"))
        yield self._tree

    # ------------------------------------------------------------------
    # Mount
    # ------------------------------------------------------------------

    def on_mount(self) -> None:
        # Wire config from the running app's AppContext
        app = self.app
        if hasattr(app, "context") and app.context is not None:
            self._config = app.context.config
        self._rebuild()

    # ------------------------------------------------------------------
    # Rebuild
    # ------------------------------------------------------------------

    def _rebuild(self) -> None:
        """Walk ``self._config._data`` and build a tree of nodes."""
        if self._config is None:
            return

        data = self._config._data
        children = self._build_children("", data)
        root = TreeNode("config-root", "Configuration", children=children)
        self._tree.set_root(root)
        self._tree.expand_all()

    # ------------------------------------------------------------------
    # Tree building
    # ------------------------------------------------------------------

    @staticmethod
    def _sanitize_id(dot_key: str) -> str:
        """Turn a dot-path into a valid DOM id."""
        return f"cfg-{dot_key.replace('.', '-').replace('[', '-').replace(']', '')}"

    def _build_children(
        self, prefix: str, data: dict[str, Any]
    ) -> list[TreeNode]:
        """Convert a dict to tree nodes.

        * Dict values → branch node with nested children.
        * List values → branch node with indexed children + ➕ add button.
        * Scalar values → leaf node with an inline editor.
        """
        nodes: list[TreeNode] = []

        for key, value in data.items():
            dot_key = f"{prefix}.{key}" if prefix else key
            node_id = self._sanitize_id(dot_key)

            if isinstance(value, dict):
                child_nodes = self._build_children(dot_key, value)
                nodes.append(
                    TreeNode(
                        node_id,
                        f"{key}",
                        children=child_nodes,
                        data={"key": dot_key, "type": "dict"},
                    )
                )
            elif isinstance(value, list):
                child_nodes = self._build_list_children(dot_key, value)
                # Determine list element type from the first item
                list_type = "dict" if value and isinstance(value[0], dict) else "scalar"
                nodes.append(
                    TreeNode(
                        node_id,
                        f"{key}  [{len(value)}]",
                        children=child_nodes,
                        data={"key": dot_key, "type": "list",
                              "list_type": list_type},
                        buttons=_infer_add_button(dot_key, value),
                    )
                )
            else:
                # Scalar leaf node — show key label, value in inline editor
                inline = _make_inline_edit(dot_key, value, self._config, self)
                nodes.append(
                    TreeNode(
                        node_id,
                        f"{key}",
                        data={"key": dot_key, "type": "value",
                              "value": value},
                        inline_edit=inline,
                    )
                )

        return nodes

    def _build_list_children(
        self, prefix: str, items: list[Any]
    ) -> list[TreeNode]:
        """Convert a list to tree nodes.

        Each item becomes a child node.  Dict items are expanded as
        branches (using ``name`` or ``id`` for the label if available).
        Scalar items appear as editable leaves.
        """
        nodes: list[TreeNode] = []

        for i, item in enumerate(items):
            dot_key = f"{prefix}[{i}]"
            node_id = self._sanitize_id(dot_key)

            if isinstance(item, dict):
                # Use a human-friendly label if the dict has name or id
                heading = item.get("name") or item.get("id") or f"item {i}"
                child_nodes = self._build_children(dot_key, item)
                nodes.append(
                    TreeNode(
                        node_id,
                        f"[{i}] {heading}",
                        children=child_nodes,
                        data={"key": dot_key, "type": "dict"},
                    )
                )
            elif isinstance(item, list):
                # Nested list
                child_nodes = self._build_list_children(dot_key, item)
                nodes.append(
                    TreeNode(
                        node_id,
                        f"[{i}]  [{len(item)}]",
                        children=child_nodes,
                        data={"key": dot_key, "type": "list"},
                    )
                )
            else:
                # Scalar list item — editable
                inline = _make_inline_edit(dot_key, item, self._config, self)
                nodes.append(
                    TreeNode(
                        node_id,
                        f"[{i}]",
                        data={"key": dot_key, "type": "value",
                              "value": item},
                        inline_edit=inline,
                    )
                )

        return nodes

    # ------------------------------------------------------------------
    # Inline edit handlers
    # ------------------------------------------------------------------

    def on_switch_changed(self, event: Switch.Changed) -> None:
        """Handle boolean toggle — persist immediately."""
        event.stop()
        sw = event.switch
        dot_key: str | None = getattr(sw, "_cfg_key", None)
        if dot_key is None or self._config is None:
            return

        new_value = sw.value
        self._config.set(dot_key, new_value)
        # No rebuild needed — the switch already shows the new state

        # Live-apply config keys that have immediate UI effects.
        if dot_key == "ui.theme" and isinstance(new_value, str):
            if new_value in self.app.available_themes:
                self.app.theme = new_value

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle text/number input — persist on Enter."""
        event.stop()
        inp = event.input
        dot_key: str | None = getattr(inp, "_cfg_key", None)
        original: Any = getattr(inp, "_cfg_original", "")
        if dot_key is None or self._config is None:
            return

        new_value = _coerce_value(event.value, original)
        self._config.set(dot_key, new_value)
        # Update the stored original so subsequent edits coerce relative
        # to the new type (e.g. if user changed "123" from string to int).
        inp._cfg_original = new_value  # type: ignore[attr-defined]
        # Update the input display to the canonical form of the value
        inp.value = _display_value(new_value)

        # Live-apply config keys that have immediate UI effects.
        if dot_key == "ui.theme" and isinstance(new_value, str):
            if new_value in self.app.available_themes:
                self.app.theme = new_value

    # ------------------------------------------------------------------
    # List add handler
    # ------------------------------------------------------------------

    def on_tree_row_button_pressed(self, event: RowButton.ButtonPressed) -> None:
        """Handle the ➕ add button on list nodes."""
        event.stop()
        if event.action_id != _ADD:
            return

        node = event.node
        dot_key: str | None = node.data.get("key") if node.data else None
        if dot_key is None or self._config is None:
            return

        current_list: Any = self._config.get(dot_key, [])
        if not isinstance(current_list, list):
            return

        # Determine list type from data stored on the node, or from
        # the first item if the list is non-empty.
        list_type = node.data.get("list_type", "scalar") if node.data else "scalar"
        if list_type == "scalar" and current_list and isinstance(current_list[0], dict):
            list_type = "dict"

        if list_type == "dict":
            self._add_dict_item(dot_key, current_list)
        else:
            self._add_scalar_item(dot_key, current_list)

    # ------------------------------------------------------------------
    # Add helpers
    # ------------------------------------------------------------------

    def _add_scalar_item(self, list_key: str, current_list: list) -> None:
        """Add a new scalar value to a flat list via InputModal."""
        # Infer default value type from existing items
        default = ""
        if current_list:
            sample = current_list[0]
            if isinstance(sample, bool):
                default = "false"
            elif isinstance(sample, int):
                default = "0"
            elif isinstance(sample, float):
                default = "0.0"
            elif sample is None:
                default = "null"

        async def do_add() -> None:
            modal = InputModal(
                f"Add to '{list_key}':",
                label="Value",
                default=default,
            )
            result = await self.app.push_screen_wait(modal)
            if result is None:
                return  # cancelled

            # Coerce the new value using an existing item as type hint
            original = current_list[0] if current_list else ""
            new_value = _coerce_value(result, original)

            new_list = list(current_list) + [new_value]
            self._config.set(list_key, new_list)
            self._rebuild()

        self.app.run_worker(do_add())

    def _add_dict_item(self, list_key: str, current_list: list) -> None:
        """Add a new dict entry to a list via FormModal.

        Infers the form fields from the first existing dict in the list.
        For empty lists, creates a minimal form with name + id fields.
        Nested dict values are entered as JSON in a text area.
        """
        if current_list and isinstance(current_list[0], dict):
            template = current_list[0]
        else:
            # No existing items — use a minimal template
            template = {"name": "", "id": ""}

        controls = _infer_dict_fields(template)

        async def do_add() -> None:
            result = await self.app.push_screen_wait(
                FormModal(f"Add to '{list_key}'", controls)
            )
            if result is None:
                return  # cancelled

            # Build the new dict from form results
            new_item: dict[str, Any] = {}
            for ctrl in controls:
                raw = result.get(ctrl.name, "")
                if ctrl.type == "textarea":
                    # Parse JSON for nested dicts
                    import json
                    try:
                        new_item[ctrl.name] = json.loads(raw) if raw.strip() else {}
                    except json.JSONDecodeError:
                        new_item[ctrl.name] = {}
                elif ctrl.type == "toggle":
                    new_item[ctrl.name] = raw.lower() in ("true", "1", "yes")
                elif ctrl.type == "number":
                    try:
                        new_item[ctrl.name] = int(raw) if "." not in raw else float(raw)
                    except ValueError:
                        new_item[ctrl.name] = raw
                else:
                    new_item[ctrl.name] = raw

            new_list = list(current_list) + [new_item]
            self._config.set(list_key, new_list)
            self._rebuild()

        self.app.run_worker(do_add())