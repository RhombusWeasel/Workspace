"""Query editor — split-pane SQL editor with results display.

Opened inside a workspace tab when the user clicks the "open query" button
on a connection in the DB sidebar panel.  The top half is a
:class:`~textual.widgets.TextArea` for writing SQL, the bottom half is a
:class:`~textual.widgets.DataTable` for displaying results.

Pagination controls allow navigating large result sets.  Non-SELECT
queries show rows affected instead of a data table.

Tab state is managed by :class:`QueryEditorState`, which holds the
connection ID, query text, last result, and pagination position.
When the workspace is reorganised (split / close), the state object
survives unchanged — the fresh widget reads from it in ``on_mount()``.
"""

from __future__ import annotations

from dataclasses import dataclass

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widget import Widget
from textual.widgets import Button, DataTable, Static, TextArea

from context import AppContext
from core.db_connections import ConnectionInfo, ConnectionManager, QueryResult
from ui.workspace.tabs import TabState


# ---------------------------------------------------------------------------
# QueryEditorState — persistent state for query editor tabs
# ---------------------------------------------------------------------------


@dataclass
class QueryEditorState(TabState):
    """State for a query editor tab that survives workspace recomposition.

    Holds the connection ID, current query text, the last query result,
    and pagination state.  When a query editor tab is closed permanently,
    ``dispose()`` is a no-op because database connections are managed
    by :class:`ConnectionManager` (pooled, not per-tab).
    """

    connection_id: str
    """Connection ID this editor is connected to."""

    query_text: str = ""
    """Current SQL text in the editor."""

    last_result: QueryResult | None = None
    """The most recent query result, if any."""

    current_query: str = ""
    """The query that produced *last_result* (may differ from
    *query_text* if the user edited but hasn't re-run)."""

    current_offset: int = 0
    """Pagination offset for the displayed result page."""

    page_size: int = 200
    """Configured page size."""


# ---------------------------------------------------------------------------
# Query editor
# ---------------------------------------------------------------------------


class QueryEditor(Widget):
    """Split-pane SQL query editor with results table.

    Parameters
    ----------
    state:
        The :class:`QueryEditorState` for this tab.  Provides the
        connection ID, initial query text, and (after first run)
        the last result and pagination state.
    """

    DEFAULT_CSS = """
    QueryEditor {
        height: 100%;
    }

    QueryEditor #query-header {
        height: auto;
        padding: 0 1;
        background: $surface;
        border-bottom: solid $primary;
    }

    QueryEditor #connection-label {
        width: 1fr;
        padding: 0 1;
    }

    QueryEditor #run-button {
        margin: 0;
    }

    QueryEditor #query-input {
        height: 2fr;
        border-bottom: solid $primary;
    }

    QueryEditor #results-area {
        height: 1fr;
    }

    QueryEditor #results-header {
        height: auto;
        padding: 0 1;
        background: $surface;
    }

    QueryEditor #results-status {
        width: 1fr;
    }

    QueryEditor #results-table {
        height: 1fr;
    }

    QueryEditor #pagination-bar {
        height: auto;
        padding: 0 1;
        background: $surface;
        dock: bottom;
    }

    QueryEditor #pagination-info {
        width: 1fr;
    }
    """

    BINDINGS = [
        Binding("ctrl+enter", "run_query", "Run Query", show=True),
        Binding("ctrl+r", "run_query", "Run Query", show=False),
    ]

    def __init__(self, state: QueryEditorState):
        super().__init__(id=f"query-editor-{state.connection_id}")
        self.state = state
        self._mgr: ConnectionManager | None = None
        self._conn_info: ConnectionInfo | None = None

    # ------------------------------------------------------------------
    # State sync
    # ------------------------------------------------------------------

    def flush_state(self) -> None:
        """Sync current widget state back to ``self.state``.

        Called by :meth:`WorkspaceTabs.save_state` before recomposition.
        Writes the current TextArea content and result/pagination state
        back to the state object.
        """
        try:
            text_area = self.query_one("#query-input", TextArea)
            self.state.query_text = text_area.text
        except Exception:
            pass
        # last_result, current_query, current_offset, page_size are
        # already kept in sync via action handlers, so no extra work
        # needed here.

    # ------------------------------------------------------------------
    # Compose
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        # Header: connection name + run button
        with Horizontal(id="query-header"):
            yield Static("󰆼 Loading...", id="connection-label")
            yield Button("▶ Run", variant="primary", id="run-button")

        # Query editor — prefill from state if available
        yield TextArea(self.state.query_text, id="query-input", language="sql")

        # Results area
        with Vertical(id="results-area"):
            with Horizontal(id="results-header"):
                yield Static("", id="results-status")
            yield DataTable(id="results-table")
            with Horizontal(id="pagination-bar"):
                yield Static("", id="pagination-info")
                yield Button("◀", variant="default", id="btn-prev")
                yield Button("▶", variant="default", id="btn-next")

    # ------------------------------------------------------------------
    # Mount — wire up from app context and restore from state
    # ------------------------------------------------------------------

    def on_mount(self) -> None:
        app = self.app
        if hasattr(app, "context") and app.context is not None:
            self._mgr = app.context.db_connections
            self._conn_info = self._mgr.get_connection(self.state.connection_id)

        # Update header with connection info
        if self._conn_info:
            from core.db_connections import get_provider

            provider_cls = get_provider(self._conn_info.provider_type)
            if provider_cls:
                label = f"󰆼 {self._conn_info.name} ({provider_cls.display_label(self._conn_info.params)})"
            else:
                label = f"󰆼 {self._conn_info.name}"
            try:
                self.query_one("#connection-label", Static).update(label)
            except Exception:
                pass

        # Load page size from config
        if hasattr(app, "context") and app.context is not None:
            self.state.page_size = app.context.config.get("db.default_page_size", 200)

        # Restore from state: if we have a last result, display it.
        if self.state.last_result is not None:
            self._display_result(self.state.last_result)

        # Focus the query input
        self.query_one("#query-input", TextArea).focus()

        # If there's query text and no result yet, auto-run after a short delay.
        if self.state.query_text.strip() and self.state.last_result is None:
            self.run_worker(self._auto_run())

    async def _auto_run(self) -> None:
        """Run the query from state after a brief delay to let the UI settle."""
        import asyncio
        await asyncio.sleep(0.1)
        self.action_run_query()

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_run_query(self) -> None:
        """Execute the current SQL query."""
        if self._mgr is None or self._conn_info is None:
            self._show_error("No database connection available.")
            return

        query = self.query_one("#query-input", TextArea).text.strip()
        if not query:
            self._show_error("No query entered.")
            return

        self.state.current_query = query
        self.state.current_offset = 0
        self._run_with_pagination()

    def _run_with_pagination(self) -> None:
        """Execute the current query with the current offset."""
        if self._mgr is None:
            return

        # Show running status
        self.query_one("#results-status", Static).update("Running query...")
        self.query_one("#results-table", DataTable).clear()

        async def do_run() -> None:
            try:
                result = self._mgr.execute(
                    self.state.connection_id,
                    self.state.current_query,
                    page_size=self.state.page_size,
                    offset=self.state.current_offset,
                )
                self.state.last_result = result
                self._display_result(result)
            except Exception as e:
                self._show_error(f"Query error: {e}")

        self.run_worker(do_run())

    # ------------------------------------------------------------------
    # Results display
    # ------------------------------------------------------------------

    def _display_result(self, result: QueryResult) -> None:
        """Update the results table and status bar with a QueryResult."""
        table = self.query_one("#results-table", DataTable)
        status = self.query_one("#results-status", Static)
        pagination_info = self.query_one("#pagination-info", Static)

        if result.error:
            self._show_error(result.error)
            return

        # Clear existing data
        table.clear(columns=True)

        if result.rows_affected is not None and not result.columns:
            # DML/DDL result — show rows affected
            table.add_column("Result")
            table.add_row((f"{result.rows_affected} row(s) affected",))
            status.update(f"✓ {result.rows_affected} row(s) affected")

            # Hide pagination for DML results
            pagination_info.update("")
            return

        # SELECT result — populate the table
        if result.columns:
            for col in result.columns:
                table.add_column(col)

            for row in result.rows:
                # Convert all values to strings for display
                table.add_row(*[str(v) if v is not None else "NULL" for v in row])

        # Status line
        row_count = len(result.rows)
        if result.total_count is not None:
            status.update(
                f"✓ {row_count} row(s) returned"
                + (f" of {result.total_count}" if result.total_count > row_count else "")
            )
        else:
            status.update(f"✓ {row_count} row(s) returned")

        # Pagination info
        start = self.state.current_offset + 1
        end = self.state.current_offset + row_count
        if result.total_count is not None:
            pagination_info.update(
                f"Rows {start}–{end} of {result.total_count}"
            )
        elif result.has_more:
            pagination_info.update(f"Rows {start}–{end}")
        else:
            pagination_info.update(f"Rows {start}–{end}")

        # Update pagination button states
        self.query_one("#btn-prev", Button).disabled = (self.state.current_offset == 0)
        self.query_one("#btn-next", Button).disabled = not result.has_more

    def _show_error(self, message: str) -> None:
        """Display an error in the results area."""
        status = self.query_one("#results-status", Static)
        table = self.query_one("#results-table", DataTable)
        table.clear(columns=True)
        status.update(f"✗ {message}")
        pagination_info = self.query_one("#pagination-info", Static)
        pagination_info.update("")

    # ------------------------------------------------------------------
    # Pagination
    # ------------------------------------------------------------------

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button clicks."""
        event.stop()
        btn_id = event.button.id

        if btn_id == "run-button":
            self.action_run_query()
        elif btn_id == "btn-prev":
            self.state.current_offset = max(0, self.state.current_offset - self.state.page_size)
            self._run_with_pagination()
        elif btn_id == "btn-next":
            self.state.current_offset += self.state.page_size
            self._run_with_pagination()