"""Config panel — sidebar tab displaying and editing configuration values.

Uses the generic :class:`~ui.tree.tree.Tree` to show config keys
hierarchically.  Scalar leaf nodes display an **inline editor** whose
type matches the value:

* ``bool``   → :class:`~textual.widgets.Switch` (toggle)
* ``str``    → :class:`~textual.widgets.Input` (text field)
* ``int``    → :class:`~textual.widgets.Input` (integer field)
* ``float``  → :class:`~textual.widgets.Input` (decimal field)
* ``None``   → :class:`~textual.widgets.Input` (type ``null`` / ``none``)

Changes are applied immediately via :meth:`Config.set()`.  Editing
``ui.theme`` also applies the theme live via ``app.theme``, which
triggers ``WorkspaceApp._watch_theme`` to persist the choice.

Dicts and lists are expanded as branch nodes, giving a full tree
view of structured data like database connections.  Only scalar leaf
values have inline editors.

Tree structure::

    Configuration
    ├── session
    │   ├── provider  [ollama]
    │   └── model     [llama3]
    ├── db
    │   ├── default_page_size  [200]
    │   └── connections
    │       ├── 0: My DB
    │       │   ├── id  [abc123]
    │       │   ├── name  [My DB]
    │       │   └── ...
    └── ui
        └── theme  ⬤ haxor
"""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.containers import Container
from textual.widgets import Input, Switch

from core.config import Config
from ui.sidebar.registry import register_sidebar_tab
from ui.tree.tree import Tree
from ui.tree.tree_row import TreeNode

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
    panel: "ConfigPanel",
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
        * List values → branch node with indexed children.
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
                nodes.append(
                    TreeNode(
                        node_id,
                        f"{key}  [{len(value)}]",
                        children=child_nodes,
                        data={"key": dot_key, "type": "list"},
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
