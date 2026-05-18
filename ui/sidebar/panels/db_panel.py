"""DB panel — database connection browser sidebar tab.

Shows a tree of saved connections, each expandable to reveal tables,
views, and triggers.  Action buttons on each connection node:

- **open** (🔍) — open a query editor workspace tab connected to this database
- **edit** (🖉) — edit the connection parameters
- **delete** (🗑) — delete the connection after confirmation
- **refresh** (⟳) — reload the table/view/trigger listing

Clicking a table name opens a query editor with ``SELECT * FROM table LIMIT 200``
pre-filled.  Branch nodes are lazy-loaded — expanding a connection queries
the database for its schema.
"""

from __future__ import annotations

import os

from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.widgets import Button, Static

from context import AppContext
from core.db_connections import (
    ConnectionInfo,
    ConnectionManager,
    get_provider,
)
from core.events import CodyEvent, register_handler
from ui.sidebar.registry import register_sidebar_tab
from ui.tree.tree import NodeNeedsChildren, Tree
from ui.tree.tree_row import RowButton, TreeNode
from utils.icons import OPEN, EDIT, DELETE, REFRESH, SEARCH


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ACTION_OPEN = "open"
_ACTION_EDIT = "edit"
_ACTION_DEL = "del"
_ACTION_REFRESH = "refresh"
_ACTION_SELECT_TABLE = "select_table"


def _connection_buttons() -> list[RowButton]:
    return [
        RowButton(_ACTION_OPEN, OPEN, "db-connection-open"),
        RowButton(_ACTION_EDIT, EDIT, "db-connection-edit"),
        RowButton(_ACTION_DEL, DELETE, "db-connection-del"),
        RowButton(_ACTION_REFRESH, REFRESH, "db-connection-refresh"),
    ]


def _table_buttons() -> list[RowButton]:
    return [
        RowButton(_ACTION_SELECT_TABLE, SEARCH, "db-table-select"),
    ]


# ---------------------------------------------------------------------------
# DB sidebar panel
# ---------------------------------------------------------------------------


@register_sidebar_tab(name="db", icon="󰆼", side="left", tooltip="Database")
class DBPanel(Container):
    """Sidebar panel showing database connections as an expandable tree.

    Each connection node can be expanded to reveal tables, views,
    and triggers.  Action buttons allow opening a query editor,
    editing the connection, deleting it, or refreshing the schema.
    """

    def __init__(self):
        super().__init__()
        self._mgr: ConnectionManager | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_connection_manager(self, mgr: ConnectionManager | None) -> None:
        """Bind a :class:`ConnectionManager` and rebuild the tree."""
        self._mgr = mgr
        if self.is_mounted:
            self._rebuild()

    # ------------------------------------------------------------------
    # Mount — self-wire from app context
    # ------------------------------------------------------------------

    def on_mount(self) -> None:
        if self._mgr is None:
            app = self.app
            if hasattr(app, "context") and app.context is not None:
                self._mgr = app.context.db_connections
        self._rebuild()

    # ------------------------------------------------------------------
    # Compose
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Static("󰆼  Database Connections", classes="db-section-header")
        self._tree = Tree(TreeNode("db-root", "Connections"))
        self._tree.id = "db-tree"
        yield self._tree

        with Horizontal(classes="db-actions"):
            yield Button("+ Add Connection", id="add-db-connection")

    # ------------------------------------------------------------------
    # Tree building
    # ------------------------------------------------------------------

    def _rebuild(self) -> None:
        """Rebuild the tree from the connection manager's data."""
        if self._mgr is None:
            self._tree.set_root(
                TreeNode("db-root", "Connections (no manager)")
            )
            return

        connections = self._mgr.list_connections()
        if not connections:
            self._tree.set_root(
                TreeNode(
                    "db-root",
                    "Connections",
                    children=[
                        TreeNode("db-empty", "(no connections)"),
                    ],
                )
            )
            self._tree.expand_all()
            return

        connection_nodes = []
        for conn in connections:
            provider_cls = get_provider(conn.provider_type)
            label = conn.name
            if provider_cls:
                label = f"{conn.name} ({provider_cls.display_label(conn.params)})"
            conn_node = TreeNode(
                f"conn-{conn.id}",
                label,
                data={"type": "connection", "conn_id": conn.id},
                buttons=_connection_buttons(),
                loaded=False,  # Lazy-load schema on expand
            )
            connection_nodes.append(conn_node)

        root = TreeNode(
            "db-root",
            "Connections",
            children=connection_nodes,
        )
        self._tree.set_root(root)

    def _build_connection_tree(self, conn: ConnectionInfo) -> TreeNode:
        """Build a full tree node for a connection with its schema."""
        try:
            schema = self._mgr.browse(conn.id)
        except Exception as e:
            return TreeNode(
                f"conn-{conn.id}-error",
                f"Error: {e}",
            )

        # Tables branch
        table_nodes = []
        for table in schema.get("tables", []):
            col_nodes = [
                TreeNode(
                    f"col-{conn.id}-{table.name}-{col.name}",
                    f"{col.name} {col.type}{' PK' if col.primary_key else ''}{'?' if col.nullable else ''}",
                    data={
                        "type": "column",
                        "conn_id": conn.id,
                        "table": table.name,
                        "column": col.name,
                    },
                )
                for col in table.columns
            ]
            table_node = TreeNode(
                f"table-{conn.id}-{table.name}",
                f" {table.name}",
                data={
                    "type": "table",
                    "conn_id": conn.id,
                    "table": table.name,
                },
                buttons=_table_buttons(),
                children=col_nodes,
            )
            table_nodes.append(table_node)

        tables_branch = TreeNode(
            f"tables-{conn.id}",
            "  Tables",
            children=table_nodes if table_nodes else [],
        )

        # Views branch
        view_nodes = [
            TreeNode(
                f"view-{conn.id}-{v.name}",
                f" {v.name}",
                data={
                    "type": "view",
                    "conn_id": conn.id,
                    "view": v.name,
                },
            )
            for v in schema.get("views", [])
        ]
        views_branch = TreeNode(
            f"views-{conn.id}",
            "  Views",
            children=view_nodes if view_nodes else [],
        )

        # Triggers branch
        trigger_nodes = [
            TreeNode(
                f"trigger-{conn.id}-{t.name}",
                f" {t.name}",
                data={
                    "type": "trigger",
                    "conn_id": conn.id,
                    "trigger": t.name,
                },
            )
            for t in schema.get("triggers", [])
        ]
        triggers_branch = TreeNode(
            f"triggers-{conn.id}",
            "  Triggers",
            children=trigger_nodes if trigger_nodes else [],
        )

        return TreeNode(
            f"conn-{conn.id}",
            conn.name,
            data={"type": "connection", "conn_id": conn.id},
            buttons=_connection_buttons(),
            children=[tables_branch, views_branch, triggers_branch],
        )

    # ------------------------------------------------------------------
    # Lazy loading
    # ------------------------------------------------------------------

    def on_node_needs_children(self, event: Tree.NodeNeedsChildren) -> None:
        """Load schema for a connection when it's expanded for the first time."""
        event.stop()
        node = event.node

        if not node.data:
            return

        node_type = node.data.get("type", "")

        # Only connection nodes are lazy-loaded for schema
        if node_type == "connection":
            conn_id = node.data.get("conn_id", "")
            conn_info = self._mgr.get_connection(conn_id) if self._mgr else None
            if conn_info is None:
                return

            try:
                schema = self._mgr.browse(conn_id)
            except Exception as e:
                # Replace children with an error node
                node.children = [
                    TreeNode(f"conn-{conn_id}-error", f"Connection error: {e}")
                ]
                node.loaded = True
                self._tree.rebuild()
                self._tree.expand_node(node.id)
                return

            # Build tables branch
            table_nodes = []
            for table in schema.get("tables", []):
                col_nodes = [
                    TreeNode(
                        f"col-{conn_id}-{table.name}-{col.name}",
                        f"{col.name} {col.type}{' PK' if col.primary_key else ''}{'?' if col.nullable else ''}",
                        data={
                            "type": "column",
                            "conn_id": conn_id,
                            "table": table.name,
                            "column": col.name,
                        },
                    )
                    for col in table.columns
                ]
                table_node = TreeNode(
                    f"table-{conn_id}-{table.name}",
                    f" {table.name}",
                    data={
                        "type": "table",
                        "conn_id": conn_id,
                        "table": table.name,
                    },
                    buttons=_table_buttons(),
                    children=col_nodes,
                )
                table_nodes.append(table_node)

            tables_branch = TreeNode(
                f"tables-{conn_id}",
                "  Tables",
                children=table_nodes if table_nodes else [],
            )

            # Views branch
            view_nodes = [
                TreeNode(
                    f"view-{conn_id}-{v.name}",
                    f" {v.name}",
                    data={
                        "type": "view",
                        "conn_id": conn_id,
                        "view": v.name,
                    },
                )
                for v in schema.get("views", [])
            ]
            views_branch = TreeNode(
                f"views-{conn_id}",
                "  Views",
                children=view_nodes if view_nodes else [],
            )

            # Triggers branch
            trigger_nodes = [
                TreeNode(
                    f"trigger-{conn_id}-{t.name}",
                    f" {t.name}",
                    data={
                        "type": "trigger",
                        "conn_id": conn_id,
                        "trigger": t.name,
                    },
                )
                for t in schema.get("triggers", [])
            ]
            triggers_branch = TreeNode(
                f"triggers-{conn_id}",
                "  Triggers",
                children=trigger_nodes if trigger_nodes else [],
            )

            # Update the node's children
            node.children = [tables_branch, views_branch, triggers_branch]
            node.loaded = True
            self._tree.rebuild()
            self._tree.expand_node(node.id)

    # ------------------------------------------------------------------
    # Button handlers — section-level
    # ------------------------------------------------------------------

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Route section-level buttons."""
        event.stop()
        btn_id = event.button.id

        if btn_id == "add-db-connection":
            self._add_connection()

    # ------------------------------------------------------------------
    # ActionRow button handlers — Connection-level actions
    # ------------------------------------------------------------------

    def on_tree_row_button_pressed(self, event: TreeRow.ButtonPressed) -> None:
        """Handle action buttons from tree rows."""
        event.stop()
        node = event.node
        action_id = event.action_id

        if not node.data:
            return

        node_type = node.data.get("type", "")

        if node_type == "connection":
            conn_id = node.data.get("conn_id", "")
            if action_id == _ACTION_OPEN:
                self._open_query(conn_id)
            elif action_id == _ACTION_EDIT:
                self._edit_connection(conn_id)
            elif action_id == _ACTION_DEL:
                self._delete_connection(conn_id)
            elif action_id == _ACTION_REFRESH:
                self._refresh_connection(conn_id)

        elif node_type == "table":
            conn_id = node.data.get("conn_id", "")
            table_name = node.data.get("table", "")
            if action_id == _ACTION_SELECT_TABLE:
                self._open_query(conn_id, f"SELECT * FROM {table_name} LIMIT 200;")

    # ------------------------------------------------------------------
    # Actions — Add connection
    # ------------------------------------------------------------------

    def _add_connection(self) -> None:
        """Push the connection form modal to add a new connection."""
        from ui.db.connection_form import ConnectionFormModal

        async def do_add() -> None:
            result = await self.app.push_screen_wait(ConnectionFormModal())
            if result is None:
                return

            if self._mgr is None:
                return

            self._mgr.add_connection(
                name=result["name"],
                provider_type=result["provider_type"],
                params=result["params"],
                sensitive_params=result.get("sensitive_params"),
            )
            self._rebuild()

        self.app.run_worker(do_add())

    # ------------------------------------------------------------------
    # Actions — Edit connection
    # ------------------------------------------------------------------

    def _edit_connection(self, conn_id: str) -> None:
        """Push the connection form modal to edit an existing connection."""
        if self._mgr is None:
            return
        conn_info = self._mgr.get_connection(conn_id)
        if conn_info is None:
            return

        from ui.db.connection_form import ConnectionFormModal

        async def do_edit() -> None:
            result = await self.app.push_screen_wait(
                ConnectionFormModal(edit_connection=conn_info)
            )
            if result is None:
                return

            self._mgr.update_connection(
                conn_id,
                name=result["name"],
                params=result["params"],
                sensitive_params=result.get("sensitive_params"),
            )
            self._rebuild()

        self.app.run_worker(do_edit())

    # ------------------------------------------------------------------
    # Actions — Delete connection
    # ------------------------------------------------------------------

    def _delete_connection(self, conn_id: str) -> None:
        """Delete a connection after confirmation."""
        from ui.widgets.confirm_modal import ConfirmModal

        async def do_delete() -> None:
            confirmed = await self.app.push_screen_wait(
                ConfirmModal("Delete Connection", f"Delete database connection '{conn_id}'? This cannot be undone.")
            )
            if not confirmed:
                return
            if self._mgr is not None:
                self._mgr.delete_connection(conn_id)
                self._rebuild()

        self.app.run_worker(do_delete())

    # ------------------------------------------------------------------
    # Actions — Refresh schema
    # ------------------------------------------------------------------

    def _refresh_connection(self, conn_id: str) -> None:
        """Force a reload of the connection's schema tree."""
        if self._mgr is None:
            return

        conn_info = self._mgr.get_connection(conn_id)
        if conn_info is None:
            return

        # Disconnect and reconnect to get fresh data
        self._mgr.disconnect(conn_id)

        # Find and reload the connection node
        conn_node_id = f"conn-{conn_id}"
        # Mark as not loaded so it will re-fetch
        for node_id, node in self._tree._node_map.items():
            if node_id == conn_node_id and node.data and node.data.get("type") == "connection":
                node.loaded = False
                node.children = []
                self._tree.collapse_node(conn_node_id)
                self._tree.expand_node(conn_node_id)
                return

        # Fallback: full rebuild
        self._rebuild()

    # ------------------------------------------------------------------
    # Actions — Open query editor
    # ------------------------------------------------------------------

    def _open_query(self, conn_id: str, prefill: str = "") -> None:
        """Post an event to open a query editor for this connection."""
        self.post_message(
            CodyEvent("db.open_query", {
                "connection_id": conn_id,
                "prefill": prefill,
            })
        )


# ---------------------------------------------------------------------------
# Event handler — open query editor in workspace
# ---------------------------------------------------------------------------


@register_handler("db.open_query")
def _on_db_open_query(data: dict, ctx: AppContext) -> None:
    """Open a query editor tab in the focused workspace pane."""
    from ui.workspace.query_editor import QueryEditor
    from ui.workspace.workspace import PaneContainer
    from ui.workspace.tabs import WorkspaceTabs

    connection_id = data.get("connection_id", "")
    prefill = data.get("prefill", "")

    if not connection_id or ctx.db_connections is None:
        return

    app = ctx.app
    if app is None:
        return

    try:
        ws = app.query_one("#workspace")
    except Exception:
        return

    focused_id = ws.focused_id
    try:
        container = app.query_one(f"#pane-{focused_id}", PaneContainer)
    except Exception:
        return

    # Get connection info for tab label
    conn_info = ctx.db_connections.get_connection(connection_id)
    if conn_info is None:
        return

    tab_label = f"󰆼 {conn_info.name}"

    # Factory for recreating the editor after workspace recomposition
    def _make_query_editor(
        _cid=connection_id, _pf=prefill
    ) -> QueryEditor:
        return QueryEditor(_cid, prefill=_pf)

    # Check if container already has WorkspaceTabs
    try:
        existing_tabs = container.query_one(WorkspaceTabs)
    except Exception:
        existing_tabs = None

    if existing_tabs is not None:
        existing_tabs.open_tab(
            f"query-{connection_id}",
            tab_label,
            content_factory=_make_query_editor,
        )
    else:
        tabs = WorkspaceTabs()

        async def _do() -> None:
            await container.mount(tabs)
            tabs.open_tab(
                f"query-{connection_id}",
                tab_label,
                content_factory=_make_query_editor,
            )

        app.run_worker(_do())