"""Config panel — sidebar tab displaying and editing configuration values.

Uses the generic :class:`~ui.tree.tree.Tree` to show config keys
hierarchically.  Leaf nodes display ``key: value`` and have an
**Edit** button that opens an :class:`~ui.widgets.input_modal.InputModal`
for inline editing.  Changes are applied immediately via
:meth:`Config.set()`.

Tree structure::

    Configuration
    ├── session
    │   ├── provider: "ollama"
    │   └── model: "llama3"
    └── ui
        └── theme: "haxor"
"""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.containers import Container
from textual.widgets import Button

from core.config import Config
from ui.sidebar.registry import register_sidebar_tab
from ui.tree.tree import Tree
from ui.tree.tree_row import ActionRow, RowButton, TreeNode

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_EDIT = "edit"


def _edit_button() -> list[RowButton]:
    return [RowButton(_EDIT, "Edit", "config-edit")]


# ---------------------------------------------------------------------------
# Value formatting / coercion
# ---------------------------------------------------------------------------


def _format_value(value: Any) -> str:
    """Return a string representation suitable for display in the tree."""
    if value is None:
        return "None"
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, str):
        # Keep strings in quotes so user can tell them apart from raw values
        return repr(value)
    return repr(value)


def _coerce_value(raw: str, original: Any) -> Any:
    """Parse *raw* (from the modal input) into a Python value.

    Attempts to match the type of *original*:
    * ``bool`` → ``"true"`` / ``"false"`` (case-insensitive) → :class:`bool`
    * ``int`` → :func:`int` parse
    * ``float`` → :func:`float` parse
    * ``None`` → ``"null"`` / ``"none"`` (case-insensitive) → ``None``
    * Otherwise → raw string

    Also handles the special cases where the original was a string
    but the user enters something that looks like another type — in
    that case we trust the *raw* string.
    """
    stripped = raw.strip()
    lowered = stripped.lower()

    # null / none
    if lowered in ("null", "none"):
        return None

    # bool
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

    # Try int/float as a convenience even when original was a string —
    # but only if the string looks numeric and doesn't have quotes.
    try:
        # Only auto-coerce if the original wasn't explicitly a string
        # (avoid silently converting "123" from string to int if user
        # wanted it to stay a string).
        pass
    except Exception:
        pass

    return stripped


# ---------------------------------------------------------------------------
# ConfigPanel
# ---------------------------------------------------------------------------


@register_sidebar_tab(name="config", icon="\ue795", side="left",
                       tooltip="Config")
class ConfigPanel(Container):
    """Sidebar panel showing configuration as an editable tree.

    Provides:
    * :meth:`set_config` — bind a :class:`Config` instance and rebuild.
    * Inline **Edit** buttons on every leaf node.
    * **Save** button to persist changes to disk.
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
        yield Button("Save", id="config-save", variant="primary")

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

    def _build_children(
        self, prefix: str, data: dict[str, Any]
    ) -> list[TreeNode]:
        """Convert a dict to tree nodes.

        * Scalar values → leaf :class:`TreeNode` with an **Edit** button.
        * Dict values → branch :class:`TreeNode` with nested children.
        """
        nodes: list[TreeNode] = []

        for key, value in data.items():
            dot_key = f"{prefix}.{key}" if prefix else key
            # Sanitize for DOM — dots, braces are illegal in Textual IDs
            node_id = f"cfg-{dot_key.replace('.', '-').replace('[', '-').replace(']', '')}"

            if isinstance(value, dict):
                # Branch node
                child_nodes = self._build_children(dot_key, value)
                nodes.append(
                    TreeNode(
                        node_id,
                        f"\uf07b  {key}",  # folder icon
                        children=child_nodes,
                        data={"key": dot_key, "type": "dict"},
                    )
                )
            else:
                # Leaf node with Edit button
                nodes.append(
                    TreeNode(
                        node_id,
                        f"  {key}: {_format_value(value)}",
                        data={"key": dot_key, "type": "value",
                              "value": value},
                        buttons=_edit_button(),
                    )
                )

        return nodes

    # ------------------------------------------------------------------
    # Button handlers — Save
    # ------------------------------------------------------------------

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle Save button press."""
        if event.button.id == "config-save":
            event.stop()
            if self._config is not None:
                try:
                    self._config.save()
                except Exception:
                    pass

    # ------------------------------------------------------------------
    # ActionRow button handlers — Edit
    # ------------------------------------------------------------------

    def on_action_row_button_pressed(self, event: ActionRow.ButtonPressed) -> None:
        """Handle the Edit button on a leaf node.

        Opens an :class:`~ui.widgets.input_modal.InputModal` pre-filled
        with the current value.  On submit, updates ``Config.set()`` and
        rebuilds the tree.
        """
        event.stop()
        if event.action_id != _EDIT:
            return

        node = event.node
        dot_key: str = node.data.get("key", "")
        current: Any = node.data.get("value", "")

        self._prompt_edit(dot_key, current)

    def _prompt_edit(self, dot_key: str, current: Any) -> None:
        """Push an InputModal and apply the result."""
        from ui.widgets.input_modal import InputModal

        # Show the value without repr wrapping for strings (cleaner)
        if isinstance(current, str):
            default_display = current
        elif current is None:
            default_display = "null"
        elif isinstance(current, bool):
            default_display = "true" if current else "false"
        else:
            default_display = repr(current)

        async def do_edit() -> None:
            modal = InputModal(
                f"Edit '{dot_key}':",
                label=dot_key,
                default=default_display,
            )
            result = await self.app.push_screen_wait(modal)
            if result is None:
                return  # cancelled

            # Coerce the new value
            new_value = _coerce_value(result, current)

            # Apply
            if self._config is not None:
                self._config.set(dot_key, new_value)
                self._rebuild()

        self.app.run_worker(do_edit())
