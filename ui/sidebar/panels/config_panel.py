"""Config panel — sidebar tab displaying and editing configuration values.

Uses the generic :class:`~ui.tree.tree.Tree` to show config keys
hierarchically.  Leaf nodes display ``key: value`` and have an
**Edit** button that opens an :class:`~ui.widgets.input_modal.InputModal`
for inline editing.  Changes are applied immediately via
:meth:`Config.set()`.

Dicts and lists are expanded as branch nodes, giving a full tree
view of structured data like database connections.  Only scalar leaf
values have Edit buttons — complex structures are navigable but
edited through their own dedicated UI.

Editing ``ui.theme`` also applies the theme live via ``app.theme``,
which triggers ``WorkspaceApp._watch_theme`` to persist the choice.

Tree structure::

    Configuration
    ├── session
    │   ├── provider: "ollama"
│   └── model: "llama3"
    ├── db
    │   ├── default_page_size: 200
    │   └── connections
    │       ├── 0: My DB
    │       │   ├── id: "abc123"
    │       │   ├── name: "My DB"
    │       │   ├── provider_type: "sqlite"
    │       │   └── params
    │       │       └── path: "/data/db.sqlite"
    │       └── 1: Other DB
    │           └── ...
    └── ui
        └── theme: "haxor"
"""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.containers import Container

from core.config import Config
from ui.sidebar.registry import register_sidebar_tab
from ui.tree.tree import Tree
from ui.tree.tree_row import TreeRow, RowButton, TreeNode
from utils.icons import EDIT

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_EDIT = "edit"


def _edit_button() -> list[RowButton]:
    return [RowButton(_EDIT, EDIT, "config-edit")]


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


@register_sidebar_tab(name="config", icon="", side="left",
                       tooltip="Config")
class ConfigPanel(Container):
    """Sidebar panel showing configuration as an editable tree.

    Provides:
    * :meth:`set_config` — bind a :class:`Config` instance and rebuild.
    * Inline **Edit** buttons on every leaf node — changes auto-persist.
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
        * Scalar values → leaf node with an **Edit** button.
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
                        f"{key}",  # folder icon
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
                # Scalar leaf node with Edit button
                nodes.append(
                    TreeNode(
                        node_id,
                        f"{key}: {_format_value(value)}",
                        data={"key": dot_key, "type": "value",
                              "value": value},
                        buttons=_edit_button(),
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
                nodes.append(
                    TreeNode(
                        node_id,
                        f"[{i}]: {_format_value(item)}",
                        data={"key": dot_key, "type": "value",
                              "value": item},
                        buttons=_edit_button(),
                    )
                )

        return nodes

    # ------------------------------------------------------------------
    # Edit handlers
    # ------------------------------------------------------------------

    def on_tree_row_button_pressed(self, event: TreeRow.ButtonPressed) -> None:
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

            # Apply & auto-persist
            if self._config is not None:
                self._config.set(dot_key, new_value)
                self._config.save()
                self._rebuild()

                # Live-apply config keys that have immediate UI effects.
                if dot_key == "ui.theme" and isinstance(new_value, str):
                    if new_value in self.app.available_themes:
                        self.app.theme = new_value

        self.app.run_worker(do_edit())
