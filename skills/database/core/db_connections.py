"""Database connection manager — multi-connection query interface.

Manages user-defined database connections backed by the layered config
system.  Connection metadata (name, provider type, params) lives in
``db.connections`` config; sensitive fields (passwords) are stored in the
vault as credentials keyed ``dbconn:{id}``.

A provider abstraction (``DBProvider``) describes what fields the
connection form needs and how to connect/query a specific database
backend.  Providers are discovered automatically from the
``providers/`` sub-package — drop a new ``.py`` file there, decorate
the class with ``@register_provider``, and it becomes available at
startup.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from core.config import Config
    from core.vault import VaultManager


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class FormField:
    """Describes a single field in the connection form.

    Parameters
    ----------
    name:
        Machine key (e.g. ``"path"``, ``"host"``, ``"password"``).
    label:
        Human-readable label shown in the form.
    type:
        Input type: ``"text"``, ``"password"``, ``"number"``, or ``"file"``.
    default:
        Pre-filled value.
    required:
        Whether the field must be non-empty to submit.
    sensitive:
        If ``True``, the value is stored in the vault (not config).
    """

    name: str
    label: str
    type: str = "text"
    default: str = ""
    required: bool = True
    sensitive: bool = False


@dataclass
class ColumnInfo:
    """Describes a single column in a table."""

    name: str
    type: str = ""
    nullable: bool = True
    primary_key: bool = False
    default: str | None = None


@dataclass
class TableInfo:
    """Describes a table in the database."""

    name: str
    columns: list[ColumnInfo] = field(default_factory=list)


@dataclass
class ViewInfo:
    """Describes a view in the database."""

    name: str
    sql: str = ""


@dataclass
class TriggerInfo:
    """Describes a trigger in the database."""

    name: str
    sql: str = ""


@dataclass
class ConnectionInfo:
    """A saved database connection.

    Parameters
    ----------
    id:
        Unique identifier (UUID hex).
    name:
        User-friendly display name.
    provider_type:
        Provider key, e.g. ``"sqlite"``.
    params:
        Non-sensitive connection parameters (provider-specific).
    created_at:
        ISO-8601 creation timestamp.
    updated_at:
        ISO-8601 last-update timestamp.
    """

    id: str
    name: str
    provider_type: str = "sqlite"
    params: dict[str, str] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a dict suitable for config storage."""
        return {
            "id": self.id,
            "name": self.name,
            "provider_type": self.provider_type,
            "params": dict(self.params),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ConnectionInfo:
        """Deserialise from a config dict."""
        return cls(
            id=d.get("id", ""),
            name=d.get("name", ""),
            provider_type=d.get("provider_type", "sqlite"),
            params=d.get("params", {}),
            created_at=d.get("created_at", ""),
            updated_at=d.get("updated_at", ""),
        )


@dataclass
class QueryResult:
    """Result of executing a SQL query.

    Parameters
    ----------
    columns:
        Column names from ``cursor.description``.
    rows:
        Data rows (limited to *page_size*).
    total_count:
        Total row count if known, ``None`` otherwise.
    has_more:
        ``True`` if more rows exist beyond this page.
    rows_affected:
        For INSERT/UPDATE/DELETE — number of rows modified.
        ``None`` for SELECT queries.
    error:
        Error message if execution failed.
    """

    columns: list[str] = field(default_factory=list)
    rows: list[tuple] = field(default_factory=list)
    total_count: int | None = None
    has_more: bool = False
    rows_affected: int | None = None
    error: str | None = None


# ---------------------------------------------------------------------------
# Provider interface
# ---------------------------------------------------------------------------


class DBProvider(ABC):
    """Abstract base for database connection providers.

    Each provider declares the form fields it needs and implements
    connection / query / introspection methods.
    """

    @classmethod
    @abstractmethod
    def provider_type(cls) -> str:
        """Machine key for this provider (e.g. ``"sqlite"``)."""
        ...

    @classmethod
    @abstractmethod
    def display_label(cls, params: dict[str, str]) -> str:
        """Return a human-readable label for a connection with these params."""
        ...

    @classmethod
    @abstractmethod
    def form_fields(cls) -> list[FormField]:
        """Return the form fields this provider requires."""
        ...

    @classmethod
    @abstractmethod
    def connect(cls, params: dict[str, str]) -> Any:
        """Open and return a connection object."""
        ...

    @classmethod
    @abstractmethod
    def disconnect(cls, conn: Any) -> None:
        """Close a connection opened by :meth:`connect`."""
        ...

    @classmethod
    @abstractmethod
    def list_tables(cls, conn: Any) -> list[TableInfo]:
        """Return all user tables in the database."""
        ...

    @classmethod
    @abstractmethod
    def list_views(cls, conn: Any) -> list[ViewInfo]:
        """Return all views in the database."""
        ...

    @classmethod
    @abstractmethod
    def list_triggers(cls, conn: Any) -> list[TriggerInfo]:
        """Return all triggers in the database."""
        ...

    @classmethod
    @abstractmethod
    def describe_table(cls, conn: Any, name: str) -> list[ColumnInfo]:
        """Return column info for *name*."""
        ...

    @classmethod
    @abstractmethod
    def execute_query(
        cls,
        conn: Any,
        query: str,
        params: tuple = (),
        page_size: int = 200,
        offset: int = 0,
    ) -> QueryResult:
        """Execute *query* and return a :class:`QueryResult`.

        For SELECT queries, *page_size* and *offset* control pagination.
        For DML/DDL queries, pagination is ignored.
        """
        ...


# ---------------------------------------------------------------------------
# Provider registry
# ---------------------------------------------------------------------------

_providers: dict[str, type[DBProvider]] = {}
"""provider_type → DBProvider subclass."""


def register_provider(cls: type[DBProvider]) -> type[DBProvider]:
    """Register a DB provider class.

    Used as a class decorator or called directly::

        @register_provider
        class SQLiteProvider(DBProvider):
            ...

    Or::

        register_provider(SQLiteProvider)

    Each provider module in ``skills/database/core/providers/`` uses this
decorator to self-register at import time.  The ``providers/__init__.py``
auto-discovers all ``.py`` files in the directory and imports them, so
adding a new provider is just a matter of dropping in a new file.
    """
    key = cls.provider_type()
    _providers[key] = cls
    return cls


def get_provider(provider_type: str) -> type[DBProvider] | None:
    """Return the registered provider class for *provider_type*, or ``None``."""
    return _providers.get(provider_type)


def list_provider_types() -> list[str]:
    """Return all registered provider type keys."""
    return sorted(_providers.keys())


# Auto-discover provider modules from the providers/ sub-package.
# Each module uses @register_provider to self-register its provider class.
from skills.database.core.providers import *  # noqa: F401,F403,E402


# ---------------------------------------------------------------------------
# Connection manager
# ---------------------------------------------------------------------------


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ConnectionManager:
    """Manages saved database connections and open connection pool.

    Reads/writes connection metadata from the layered config under
    ``db.connections``.  Sensitive fields (passwords) are stored in the
    vault as credentials keyed ``dbconn:{id}``.

    Parameters
    ----------
    config:
        The application config instance.
    vault:
        The vault manager (may be locked; sensitive fields are
        unavailable until unlock).
    """

    def __init__(self, config: Config, vault: VaultManager) -> None:
        self._config = config
        self._vault = vault
        self._open_connections: dict[str, Any] = {}
        # conn_id → open connection object

    # ------------------------------------------------------------------
    # CRUD — Connection metadata
    # ------------------------------------------------------------------

    def list_connections(self) -> list[ConnectionInfo]:
        """Return all saved connections from config."""
        raw = self._config.get("db.connections", [])
        if not isinstance(raw, list):
            return []
        return [ConnectionInfo.from_dict(d) for d in raw]

    def get_connection(self, conn_id: str) -> ConnectionInfo | None:
        """Return a single connection by ID, or ``None``."""
        for conn in self.list_connections():
            if conn.id == conn_id:
                return conn
        return None

    def add_connection(
        self,
        name: str,
        provider_type: str = "sqlite",
        params: dict[str, str] | None = None,
        sensitive_params: dict[str, str] | None = None,
    ) -> ConnectionInfo:
        """Create and persist a new connection.

        Non-sensitive *params* are stored in config.
        *sensitive_params* (e.g. passwords) are stored in the vault
        under the key ``dbconn:{id}``.
        """
        conn_id = uuid.uuid4().hex[:12]
        now = _now()

        info = ConnectionInfo(
            id=conn_id,
            name=name,
            provider_type=provider_type,
            params=params or {},
            created_at=now,
            updated_at=now,
        )

        # Save non-sensitive params to config
        connections = list(self._config.get("db.connections", []))
        connections.append(info.to_dict())
        self._config.set("db.connections", connections)
        self._config.save()

        # Save sensitive params to vault
        if sensitive_params:
            self._store_sensitive(conn_id, sensitive_params)

        return info

    def update_connection(
        self,
        conn_id: str,
        *,
        name: str | None = None,
        params: dict[str, str] | None = None,
        sensitive_params: dict[str, str] | None = None,
    ) -> ConnectionInfo | None:
        """Update an existing connection's metadata.

        Only the fields that are passed are changed.
        """
        connections = list(self._config.get("db.connections", []))
        found = False
        for i, raw in enumerate(connections):
            info = ConnectionInfo.from_dict(raw)
            if info.id == conn_id:
                if name is not None:
                    info.name = name
                if params is not None:
                    info.params = params
                info.updated_at = _now()
                connections[i] = info.to_dict()
                found = True
                break

        if not found:
            return None

        self._config.set("db.connections", connections)
        self._config.save()

        # Update sensitive params in vault
        if sensitive_params is not None:
            self._store_sensitive(conn_id, sensitive_params)

        # Close any cached connection so it reconnects with new params
        self.disconnect(conn_id)

        return ConnectionInfo.from_dict(connections[i])

    def delete_connection(self, conn_id: str) -> bool:
        """Remove a connection from config, vault, and close any open connection."""
        connections = list(self._config.get("db.connections", []))
        new_connections = [c for c in connections if c.get("id") != conn_id]

        if len(new_connections) == len(connections):
            return False  # Not found

        self._config.set("db.connections", new_connections)
        self._config.save()

        # Remove from vault
        self._remove_sensitive(conn_id)

        # Close cached connection
        self.disconnect(conn_id)

        return True

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    def connect(self, conn_id: str) -> Any:
        """Open (or return cached) connection for *conn_id*.

        Merges non-sensitive params from config with sensitive params
        from the vault before passing them to the provider.

        Raises ``ValueError`` if the connection ID is not found or the
        provider is not registered.
        """
        if conn_id in self._open_connections:
            return self._open_connections[conn_id]

        info = self.get_connection(conn_id)
        if info is None:
            raise ValueError(f"Connection not found: {conn_id}")

        provider_cls = get_provider(info.provider_type)
        if provider_cls is None:
            raise ValueError(f"Unknown provider type: {info.provider_type}")

        # Merge sensitive params from vault
        full_params = dict(info.params)
        sensitive = self._load_sensitive(conn_id)
        full_params.update(sensitive)

        conn = provider_cls.connect(full_params)
        self._open_connections[conn_id] = conn
        return conn

    def disconnect(self, conn_id: str) -> None:
        """Close a cached connection, if open."""
        conn = self._open_connections.pop(conn_id, None)
        if conn is None:
            return
        info = self.get_connection(conn_id)
        if info is None:
            return
        provider_cls = get_provider(info.provider_type)
        if provider_cls is not None:
            provider_cls.disconnect(conn)

    def disconnect_all(self) -> None:
        """Close all cached connections."""
        for conn_id in list(self._open_connections):
            self.disconnect(conn_id)

    # ------------------------------------------------------------------
    # Browsing / introspection
    # ------------------------------------------------------------------

    def browse(self, conn_id: str) -> dict[str, Any]:
        """Return tables, views, and triggers for *conn_id*.

        Returns a dict::

            {
                "tables": [TableInfo(...), ...],
                "views": [ViewInfo(...), ...],
                "triggers": [TriggerInfo(...), ...],
            }

        Raises ``ValueError`` if the connection cannot be opened.
        """
        conn = self.connect(conn_id)
        info = self.get_connection(conn_id)
        if info is None:
            raise ValueError(f"Connection not found: {conn_id}")
        provider_cls = get_provider(info.provider_type)

        # Populate columns for tables
        tables = provider_cls.list_tables(conn)
        for table in tables:
            table.columns = provider_cls.describe_table(conn, table.name)

        return {
            "tables": tables,
            "views": provider_cls.list_views(conn),
            "triggers": provider_cls.list_triggers(conn),
        }

    def execute(
        self,
        conn_id: str,
        query: str,
        page_size: int = 200,
        offset: int = 0,
    ) -> QueryResult:
        """Execute *query* on *conn_id* with pagination.

        Returns a :class:`QueryResult`.  Raises ``ValueError`` if the
        connection cannot be opened.
        """
        conn = self.connect(conn_id)
        info = self.get_connection(conn_id)
        if info is None:
            return QueryResult(error=f"Connection not found: {conn_id}")
        provider_cls = get_provider(info.provider_type)
        return provider_cls.execute_query(conn, query, page_size=page_size, offset=offset)

    # ------------------------------------------------------------------
    # Vault helpers
    # ------------------------------------------------------------------

    def _store_sensitive(self, conn_id: str, params: dict[str, str]) -> None:
        """Store sensitive params in the vault as a credential ``dbconn:{id}``."""
        if not self._vault.is_locked() and params:
            # Store as credential with username=sensitive indicator, password=JSON
            import json

            self._vault.register_credential(
                f"dbconn:{conn_id}",
                "_db",
                json.dumps(params),
            )

    def _load_sensitive(self, conn_id: str) -> dict[str, str]:
        """Load sensitive params from the vault for *conn_id*."""
        if self._vault.is_locked():
            return {}
        try:
            cred = self._vault.get_credential(f"dbconn:{conn_id}")
            if cred is None:
                return {}
            import json

            return json.loads(cred[1])
        except (json.JSONDecodeError, Exception):
            return {}

    def _remove_sensitive(self, conn_id: str) -> None:
        """Remove sensitive params from the vault."""
        if not self._vault.is_locked():
            try:
                self._vault.delete_credential(f"dbconn:{conn_id}")
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Config defaults — registered at import time
# ---------------------------------------------------------------------------

from core.config import register_defaults  # noqa: E402

register_defaults(
    {
        "db": {
            "connections": [],
            "default_page_size": 200,
        }
    }
)