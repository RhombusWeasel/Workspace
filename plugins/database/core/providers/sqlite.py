"""SQLite database provider — the bundled default backend.

Registers itself via ``@register_provider`` at import time.  Adding a new
provider is as simple as creating a ``.py`` file in this ``providers/``
directory and decorating the class with ``@register_provider`` — the
auto-discovery in ``__init__.py`` takes care of the rest.
"""

import os
import sqlite3
from typing import Any

from plugins.database.core.db_connections import (
    ColumnInfo,
    DBProvider,
    FormField,
    QueryResult,
    TableInfo,
    TriggerInfo,
    ViewInfo,
    register_provider,
)


# ---------------------------------------------------------------------------
# SQLite provider
# ---------------------------------------------------------------------------


@register_provider
class SQLiteProvider(DBProvider):
    """SQLite database provider — the only bundled backend."""

    @classmethod
    def provider_type(cls) -> str:
        return "sqlite"

    @classmethod
    def display_label(cls, params: dict[str, str]) -> str:
        path = params.get("path", "")
        # Show just the filename for brevity
        return os.path.basename(path) if path else "SQLite"

    @classmethod
    def form_fields(cls) -> list[FormField]:
        return [
            FormField(
                name="path",
                label="Database File Path",
                type="file",
                required=True,
            ),
        ]

    @classmethod
    def connect(cls, params: dict[str, str]) -> sqlite3.Connection:
        path = params.get("path", "")
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        return conn

    @classmethod
    def disconnect(cls, conn: Any) -> None:
        try:
            conn.close()
        except Exception:
            pass

    @classmethod
    def list_tables(cls, conn: Any) -> list[TableInfo]:
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
        return [TableInfo(name=row[0]) for row in cur.fetchall()]

    @classmethod
    def list_views(cls, conn: Any) -> list[ViewInfo]:
        cur = conn.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='view' ORDER BY name"
        )
        return [ViewInfo(name=row[0], sql=row[1] or "") for row in cur.fetchall()]

    @classmethod
    def list_triggers(cls, conn: Any) -> list[TriggerInfo]:
        cur = conn.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='trigger' ORDER BY name"
        )
        return [TriggerInfo(name=row[0], sql=row[1] or "") for row in cur.fetchall()]

    @classmethod
    def describe_table(cls, conn: Any, name: str) -> list[ColumnInfo]:
        cur = conn.execute(f'PRAGMA table_info("{name}")')
        columns = []
        for row in cur.fetchall():
            # row: (cid, name, type, notnull, dflt_value, pk)
            columns.append(
                ColumnInfo(
                    name=row[1],
                    type=row[2] or "",
                    nullable=not row[3],
                    primary_key=bool(row[5]),
                    default=row[4],
                )
            )
        return columns

    @classmethod
    def execute_query(
        cls,
        conn: Any,
        query: str,
        params: tuple = (),
        page_size: int = 200,
        offset: int = 0,
    ) -> QueryResult:
        try:
            # Determine if this is a SELECT-like query
            normalized = query.strip().lstrip("(").split()[0].upper()
            is_select = normalized in ("SELECT", "PRAGMA", "EXPLAIN", "WITH")

            if is_select:
                return cls._execute_select(conn, query, params, page_size, offset)
            else:
                return cls._execute_dml(conn, query, params)
        except Exception as e:
            return QueryResult(error=str(e))

    @classmethod
    def _execute_select(
        cls,
        conn: Any,
        query: str,
        params: tuple,
        page_size: int,
        offset: int,
    ) -> QueryResult:
        """Execute a SELECT query with pagination."""
        # Get total count
        total_count = None
        try:
            count_cur = conn.execute(
                f"SELECT COUNT(*) FROM ({query}) AS _sub", params
            )
            total_count = count_cur.fetchone()[0]
        except Exception:
            # COUNT query may fail for complex queries; just skip it
            pass

        # Fetch page of results
        if offset == 0 and page_size >= total_count if total_count is not None else False:
            # Small result set — no need for LIMIT/OFFSET
            cur = conn.execute(query, params)
            columns = [desc[0] for desc in cur.description] if cur.description else []
            rows = [tuple(row) for row in cur.fetchall()]
            return QueryResult(
                columns=columns,
                rows=rows,
                total_count=total_count,
                has_more=False,
            )

        # Apply pagination via subquery
        paged_query = f"SELECT * FROM ({query}) AS _sub LIMIT ? OFFSET ?"
        cur = conn.execute(paged_query, params + (page_size, offset))
        columns = [desc[0] for desc in cur.description] if cur.description else []
        rows = [tuple(row) for row in cur.fetchall()]
        has_more = len(rows) == page_size

        return QueryResult(
            columns=columns,
            rows=rows,
            total_count=total_count,
            has_more=has_more,
        )

    @classmethod
    def _execute_dml(
        cls,
        conn: Any,
        query: str,
        params: tuple,
    ) -> QueryResult:
        """Execute a DML/DDL query (INSERT, UPDATE, DELETE, CREATE, etc.)."""
        cur = conn.execute(query, params)
        conn.commit()
        rows_affected = cur.rowcount
        # For DDL statements, cursor.description may be None
        if cur.description:
            columns = [desc[0] for desc in cur.description]
            rows = [tuple(row) for row in cur.fetchall()]
            return QueryResult(
                columns=columns,
                rows=rows,
                rows_affected=rows_affected,
            )
        return QueryResult(rows_affected=rows_affected)