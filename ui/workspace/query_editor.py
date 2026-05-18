"""Query editor — split-pane SQL editor with results display.

Opened inside a workspace tab when the user clicks the "open query" button
on a connection in the DB sidebar panel.  The top half is a
:class:`~textual.widgets.TextArea` for writing SQL, the bottom half is a
:class:`~textual.widgets.DataTable` for displaying results.

Pagination controls allow navigating large result sets.  Non-SELECT
queries show rows affected instead of a data table.

When the workspace is reorganised (split / close), the editor's query
text, result data, and pagination state are preserved across the DOM
rebuild so the user doesn't lose their work.  This relies on:

* :class:`QueryEditorSnapshot` — a dataclass bundling the current
  query text, the last ``QueryResult``, and pagination position.
* :meth:`detach_state` — captures the editor's state before
  recomposition.
* ``_inherited_snapshot`` — injected by ``restore_state``, consumed
  in ``on_mount`` so the fresh widget shows the same query and results.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widget import Widget
from textual.widgets import Button, DataTable, Static, TextArea

from context import AppContext
from core.db_connections import ConnectionInfo, ConnectionManager, QueryResult


# ---------------------------------------------------------------------------
# Query editor snapshot (for preservation across recomposition)
# ---------------------------------------------------------------------------


@dataclass
class QueryEditorSnapshot:
    """Captured state from a running query editor that can be restored
    after a workspace recomposition.

    Bundles the current query text, the last result, and pagination
    state so the editor looks exactly the same after a split / close.

    Like :class:`~ui.terminal.terminal.TerminalSnapshot`, these are
    **plain Python objects** — not Textual widgets — so they can be
    freely transferred between widget instances.
    """

    connection_id: str
    """Connection ID this editor was connected to."""

    query_text: str
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
    connection_id:
        ID of the database connection to query against.
    prefill:
        Initial SQL text to show in the editor (e.g. a SELECT statement).
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

    def __init__(self, connection_id: str, prefill: str = ""):
        super().__init__(id=f"query-editor-{connection_id}")
        self._connection_id = connection_id
        self._prefill = prefill
        self._mgr: ConnectionManager | None = None
        self._conn_info: ConnectionInfo | None = None

        # Pagination state
        self._current_query: str = ""
        self._page_size: int = 200
        self._current_offset: int = 0
        self._last_result: QueryResult | None = None

        # Snapshot injected by restore_state() — consumed in on_mount()
        self._inherited_snapshot: QueryEditorSnapshot | None = None

    # ------------------------------------------------------------------
    # State transfer (preservation across recomposition)
    # ------------------------------------------------------------------

    def detach_state(self) -> QueryEditorSnapshot | None:
        """Capture the editor's current state for preservation across
        a workspace recomposition.

        Called by :meth:`WorkspaceTabs.save_state` before the DOM
        rebuild.  The returned :class:`QueryEditorSnapshot` can be
        passed to a new ``QueryEditor`` via ``_inherited_snapshot``
        so the query text and results survive the recomposition.

        Returns a :class:`QueryEditorSnapshot`, or ``None`` if the
        widget isn't in a capturable state.
        """
        try:
            text_area = self.query_one("#query-input", TextArea)
            query_text = text_area.text
        except Exception:
            query_text = self._prefill

        return QueryEditorSnapshot(
            connection_id=self._connection_id,
            query_text=query_text,
            last_result=self._last_result,
            current_query=self._current_query,
            current_offset=self._current_offset,
            page_size=self._page_size,
        )

    # ------------------------------------------------------------------
    # Compose
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        # Header: connection name + run button
        with Horizontal(id="query-header"):
            yield Static("󰆼 Loading...", id="connection-label")
            yield Button("▶ Run", variant="primary", id="run-button")

        # Query editor
        yield TextArea(self._prefill, id="query-input", language="sql")

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
    # Mount — wire up from app context
    # ------------------------------------------------------------------

    def on_mount(self) -> None:
        app = self.app
        if hasattr(app, "context") and app.context is not None:
            self._mgr = app.context.db_connections
            self._conn_info = self._mgr.get_connection(self._connection_id)

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
            self._page_size = app.context.config.get("db.default_page_size", 200)

        # If a snapshot was transferred from a previous instance,
        # restore the editor's state so the user sees their query
        # and results immediately.
        if self._inherited_snapshot is not None:
            self._restore_from_snapshot(self._inherited_snapshot)
            self._inherited_snapshot = None

        # Focus the query input
        self.query_one("#query-input", TextArea).focus()

        # If there's a prefill AND no inherited snapshot, run it
        # automatically after a short delay.
        if self._prefill.strip() and self._last_result is None:
            self.run_worker(self._auto_run())

    def _restore_from_snapshot(self, snapshot: QueryEditorSnapshot) -> None:
        """Restore editor state from a captured snapshot.

        Replaces the TextArea content, restores pagination state,
        and re-displays the last result if one exists.
        """
        # Restore query text
        try:
            text_area = self.query_one("#query-input", TextArea)
            text_area.load_text(snapshot.query_text)
        except Exception:
            pass

        # Restore pagination state
        self._current_query = snapshot.current_query
        self._current_offset = snapshot.current_offset
        self._page_size = snapshot.page_size

        # Re-display last result
        if snapshot.last_result is not None:
            self._last_result = snapshot.last_result
            self._display_result(snapshot.last_result)

    async def _auto_run(self) -> None:
        """Run the prefill query after a brief delay to let the UI settle."""
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

        self._current_query = query
        self._current_offset = 0
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
                    self._connection_id,
                    self._current_query,
                    page_size=self._page_size,
                    offset=self._current_offset,
                )
                self._last_result = result
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
        start = self._current_offset + 1
        end = self._current_offset + row_count
        if result.total_count is not None:
            pagination_info.update(
                f"Rows {start}–{end} of {result.total_count}"
            )
        elif result.has_more:
            pagination_info.update(f"Rows {start}–{end}")
        else:
            pagination_info.update(f"Rows {start}–{end}")

        # Update pagination button states
        self.query_one("#btn-prev", Button).disabled = (self._current_offset == 0)
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
            self._current_offset = max(0, self._current_offset - self._page_size)
            self._run_with_pagination()
        elif btn_id == "btn-next":
            self._current_offset += self._page_size
            self._run_with_pagination()