"""Tests for db_connections, providers, and ConnectionManager."""

import json
import os
import sqlite3
import tempfile

import pytest

from core.config import Config, register_defaults, reset_registered_defaults, get_registered_defaults
from skills.database.core.db_connections import (
    ColumnInfo,
    ConnectionInfo,
    ConnectionManager,
    DBProvider,
    FormField,
    QueryResult,
    TableInfo,
    TriggerInfo,
    ViewInfo,
    get_provider,
    list_provider_types,
    register_provider,
    _providers,
)
from skills.database.core.providers.sqlite import SQLiteProvider
from core.vault import Vault


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_provider_registry():
    """Reset the provider registry around every test so SQLiteProvider
    re-registers cleanly."""
    saved = dict(_providers)
    _providers.clear()
    register_provider(SQLiteProvider)
    yield
    _providers.clear()
    _providers.update(saved)


@pytest.fixture
def config_file(tmp_path):
    """Return a path to a temporary config file."""
    return str(tmp_path / "config.json")


@pytest.fixture
def config(config_file):
    """Return a Config instance with registered defaults applied."""
    register_defaults({
        "db": {
            "connections": [],
            "default_page_size": 200,
        }
    })
    cfg = Config([config_file])
    cfg.defaults(get_registered_defaults())
    cfg.apply_defaults()
    reset_registered_defaults()
    return cfg


@pytest.fixture
def vault_file(tmp_path):
    """Return a path to a temporary vault file."""
    return str(tmp_path / "vault.enc")


@pytest.fixture
def vault(vault_file):
    """Return an unlocked Vault."""
    v = Vault(vault_file)
    v.initialize("testpass")
    return v


@pytest.fixture
def vault_mgr(vault_file, tmp_path):
    """Return a VaultManager with an unlocked master vault."""
    from core.vault import VaultManager
    vm = VaultManager(vault_file, str(tmp_path))
    vm.initialize_master("testpass")
    return vm


@pytest.fixture
def mgr(config, vault_mgr):
    """Return a ConnectionManager linked to config and vault."""
    return ConnectionManager(config, vault_mgr)


@pytest.fixture
def db_file(tmp_path):
    """Create a temporary SQLite database with test data."""
    path = str(tmp_path / "test.db")
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, email TEXT)"
    )
    conn.execute(
        "INSERT INTO users (id, name, email) VALUES (1, 'Alice', 'alice@example.com')"
    )
    conn.execute(
        "INSERT INTO users (id, name, email) VALUES (2, 'Bob', 'bob@example.com')"
    )
    conn.execute(
        "INSERT INTO users (id, name, email) VALUES (3, 'Charlie', 'charlie@example.com')"
    )
    conn.execute(
        "CREATE VIEW active_users AS SELECT id, name FROM users WHERE id > 0"
    )
    conn.execute(
        "CREATE TRIGGER update_ts AFTER UPDATE ON users BEGIN SELECT 1; END"
    )
    conn.commit()
    conn.close()
    return path


# ---------------------------------------------------------------------------
# FormField
# ---------------------------------------------------------------------------


class TestFormField:
    def test_defaults(self):
        f = FormField(name="path", label="File Path")
        assert f.name == "path"
        assert f.label == "File Path"
        assert f.type == "text"
        assert f.default == ""
        assert f.required is True
        assert f.sensitive is False

    def test_sensitive(self):
        f = FormField(name="password", label="Password", type="password", sensitive=True)
        assert f.sensitive is True
        assert f.type == "password"


# ---------------------------------------------------------------------------
# ConnectionInfo
# ---------------------------------------------------------------------------


class TestConnectionInfo:
    def test_to_dict_roundtrip(self):
        info = ConnectionInfo(
            id="abc123",
            name="test-db",
            provider_type="sqlite",
            params={"path": "/tmp/test.db"},
            created_at="2024-01-01T00:00:00",
            updated_at="2024-01-01T00:00:00",
        )
        d = info.to_dict()
        assert d["id"] == "abc123"
        assert d["name"] == "test-db"
        assert d["provider_type"] == "sqlite"
        assert d["params"] == {"path": "/tmp/test.db"}

    def test_from_dict(self):
        d = {
            "id": "def456",
            "name": "my-db",
            "provider_type": "sqlite",
            "params": {"path": "/data/app.db"},
            "created_at": "",
            "updated_at": "",
        }
        info = ConnectionInfo.from_dict(d)
        assert info.id == "def456"
        assert info.name == "my-db"
        assert info.params == {"path": "/data/app.db"}

    def test_from_dict_defaults(self):
        info = ConnectionInfo.from_dict({})
        assert info.id == ""
        assert info.provider_type == "sqlite"
        assert info.params == {}


# ---------------------------------------------------------------------------
# SQLiteProvider
# ---------------------------------------------------------------------------


class TestSQLiteProvider:
    def test_provider_type(self):
        assert SQLiteProvider.provider_type() == "sqlite"

    def test_form_fields(self):
        fields = SQLiteProvider.form_fields()
        assert len(fields) == 1
        assert fields[0].name == "path"
        assert fields[0].type == "file"

    def test_display_label(self):
        label = SQLiteProvider.display_label({"path": "/data/my.db"})
        assert label == "my.db"

    def test_display_label_empty(self):
        label = SQLiteProvider.display_label({})
        assert label == "SQLite"

    def test_connect_and_disconnect(self, db_file):
        conn = SQLiteProvider.connect({"path": db_file})
        assert conn is not None
        # Should be a real sqlite3 connection
        cur = conn.execute("SELECT 1")
        assert cur.fetchone()[0] == 1
        SQLiteProvider.disconnect(conn)

    def test_list_tables(self, db_file):
        conn = SQLiteProvider.connect({"path": db_file})
        try:
            tables = SQLiteProvider.list_tables(conn)
            names = [t.name for t in tables]
            assert "users" in names
            # sqlite_master tables should be filtered
            assert "sqlite_sequence" not in names
        finally:
            SQLiteProvider.disconnect(conn)

    def test_list_views(self, db_file):
        conn = SQLiteProvider.connect({"path": db_file})
        try:
            views = SQLiteProvider.list_views(conn)
            names = [v.name for v in views]
            assert "active_users" in names
        finally:
            SQLiteProvider.disconnect(conn)

    def test_list_triggers(self, db_file):
        conn = SQLiteProvider.connect({"path": db_file})
        try:
            triggers = SQLiteProvider.list_triggers(conn)
            names = [t.name for t in triggers]
            assert "update_ts" in names
        finally:
            SQLiteProvider.disconnect(conn)

    def test_describe_table(self, db_file):
        conn = SQLiteProvider.connect({"path": db_file})
        try:
            columns = SQLiteProvider.describe_table(conn, "users")
            col_names = [c.name for c in columns]
            assert "id" in col_names
            assert "name" in col_names
            assert "email" in col_names
            # Check primary key
            id_col = next(c for c in columns if c.name == "id")
            assert id_col.primary_key is True
        finally:
            SQLiteProvider.disconnect(conn)

    def test_execute_select(self, db_file):
        conn = SQLiteProvider.connect({"path": db_file})
        try:
            result = SQLiteProvider.execute_query(conn, "SELECT * FROM users")
            assert result.error is None
            assert "id" in result.columns
            assert "name" in result.columns
            assert "email" in result.columns
            assert len(result.rows) == 3
            assert result.rows_affected is None
        finally:
            SQLiteProvider.disconnect(conn)

    def test_execute_select_with_limit(self, db_file):
        conn = SQLiteProvider.connect({"path": db_file})
        try:
            result = SQLiteProvider.execute_query(
                conn, "SELECT * FROM users", page_size=2, offset=0
            )
            assert result.error is None
            assert len(result.rows) == 2
            assert result.has_more is True  # There's a 3rd row
            assert result.total_count == 3
        finally:
            SQLiteProvider.disconnect(conn)

    def test_execute_select_pagination(self, db_file):
        conn = SQLiteProvider.connect({"path": db_file})
        try:
            # Second page (offset=2, page_size=2)
            result = SQLiteProvider.execute_query(
                conn, "SELECT * FROM users", page_size=2, offset=2
            )
            assert result.error is None
            assert len(result.rows) == 1  # Only 1 row on the second page
            assert result.has_more is False
        finally:
            SQLiteProvider.disconnect(conn)

    def test_execute_insert(self, db_file):
        conn = SQLiteProvider.connect({"path": db_file})
        try:
            result = SQLiteProvider.execute_query(
                conn,
                "INSERT INTO users (id, name, email) VALUES (4, 'Dave', 'dave@example.com')",
            )
            assert result.error is None
            assert result.rows_affected == 1
        finally:
            SQLiteProvider.disconnect(conn)

    def test_execute_error(self, db_file):
        conn = SQLiteProvider.connect({"path": db_file})
        try:
            result = SQLiteProvider.execute_query(
                conn, "SELECT * FROM nonexistent_table"
            )
            assert result.error is not None
            assert "no such table" in result.error.lower()
        finally:
            SQLiteProvider.disconnect(conn)


# ---------------------------------------------------------------------------
# Provider registry
# ---------------------------------------------------------------------------


class TestProviderRegistry:
    def test_sqlite_registered(self):
        assert get_provider("sqlite") is SQLiteProvider

    def test_list_provider_types(self):
        types = list_provider_types()
        assert "sqlite" in types

    def test_unknown_provider(self):
        assert get_provider("unknown") is None

    def test_register_custom_provider(self):
        class DummyProvider(DBProvider):
            @classmethod
            def provider_type(cls):
                return "dummy"

            @classmethod
            def display_label(cls, params):
                return "dummy"

            @classmethod
            def form_fields(cls):
                return []

            @classmethod
            def connect(cls, params):
                return None

            @classmethod
            def disconnect(cls, conn):
                pass

            @classmethod
            def list_tables(cls, conn):
                return []

            @classmethod
            def list_views(cls, conn):
                return []

            @classmethod
            def list_triggers(cls, conn):
                return []

            @classmethod
            def describe_table(cls, conn, name):
                return []

            @classmethod
            def execute_query(cls, conn, query, params=(), page_size=200, offset=0):
                return QueryResult()

        register_provider(DummyProvider)
        assert get_provider("dummy") is DummyProvider
        assert "dummy" in list_provider_types()


# ---------------------------------------------------------------------------
# ConnectionManager — CRUD
# ---------------------------------------------------------------------------


class TestConnectionManagerCRUD:
    def test_list_connections_empty(self, mgr):
        assert mgr.list_connections() == []

    def test_add_connection(self, mgr, db_file):
        info = mgr.add_connection(
            name="test-db",
            provider_type="sqlite",
            params={"path": db_file},
        )
        assert info.id
        assert info.name == "test-db"
        assert info.provider_type == "sqlite"
        assert info.params == {"path": db_file}

    def test_add_connection_persists(self, mgr, db_file):
        mgr.add_connection(name="test-db", params={"path": db_file})
        # Re-read from config
        connections = mgr.list_connections()
        assert len(connections) == 1
        assert connections[0].name == "test-db"

    def test_get_connection(self, mgr, db_file):
        info = mgr.add_connection(name="test-db", params={"path": db_file})
        retrieved = mgr.get_connection(info.id)
        assert retrieved is not None
        assert retrieved.name == "test-db"

    def test_get_connection_not_found(self, mgr):
        assert mgr.get_connection("nonexistent") is None

    def test_add_multiple_connections(self, mgr, db_file):
        mgr.add_connection(name="db1", params={"path": db_file})
        mgr.add_connection(name="db2", params={"path": db_file})
        connections = mgr.list_connections()
        assert len(connections) == 2

    def test_update_connection(self, mgr, db_file):
        info = mgr.add_connection(name="test-db", params={"path": db_file})
        updated = mgr.update_connection(info.id, name="renamed-db")
        assert updated is not None
        assert updated.name == "renamed-db"

    def test_update_connection_not_found(self, mgr):
        result = mgr.update_connection("nonexistent", name="x")
        assert result is None

    def test_delete_connection(self, mgr, db_file):
        info = mgr.add_connection(name="test-db", params={"path": db_file})
        assert mgr.delete_connection(info.id) is True
        assert mgr.list_connections() == []

    def test_delete_connection_not_found(self, mgr):
        assert mgr.delete_connection("nonexistent") is False


# ---------------------------------------------------------------------------
# ConnectionManager — Connect / Disconnect
# ---------------------------------------------------------------------------


class TestConnectionManagerConnect:
    def test_connect_and_disconnect(self, mgr, db_file):
        info = mgr.add_connection(name="test-db", params={"path": db_file})
        conn = mgr.connect(info.id)
        assert conn is not None
        # Should be able to query
        cur = conn.execute("SELECT 1")
        assert cur.fetchone()[0] == 1

        mgr.disconnect(info.id)
        # After disconnect, should not be in cache

    def test_connect_caches(self, mgr, db_file):
        info = mgr.add_connection(name="test-db", params={"path": db_file})
        conn1 = mgr.connect(info.id)
        conn2 = mgr.connect(info.id)
        # Same object (cached)
        assert conn1 is conn2

    def test_connect_unknown_id(self, mgr):
        with pytest.raises(ValueError, match="not found"):
            mgr.connect("nonexistent")

    def test_disconnect_all(self, mgr, db_file):
        mgr.add_connection(name="db1", params={"path": db_file})
        info2 = mgr.add_connection(name="db2", params={"path": db_file})
        mgr.connect(info2.id)
        mgr.disconnect_all()


# ---------------------------------------------------------------------------
# ConnectionManager — Browse / Execute
# ---------------------------------------------------------------------------


class TestConnectionManagerBrowse:
    def test_browse(self, mgr, db_file):
        info = mgr.add_connection(name="test-db", params={"path": db_file})
        schema = mgr.browse(info.id)
        assert "tables" in schema
        assert "views" in schema
        assert "triggers" in schema
        table_names = [t.name for t in schema["tables"]]
        assert "users" in table_names

    def test_browse_populates_columns(self, mgr, db_file):
        info = mgr.add_connection(name="test-db", params={"path": db_file})
        schema = mgr.browse(info.id)
        users = next(t for t in schema["tables"] if t.name == "users")
        assert len(users.columns) > 0
        col_names = [c.name for c in users.columns]
        assert "id" in col_names
        assert "name" in col_names

    def test_execute_select(self, mgr, db_file):
        info = mgr.add_connection(name="test-db", params={"path": db_file})
        result = mgr.execute(info.id, "SELECT * FROM users")
        assert result.error is None
        assert len(result.rows) == 3

    def test_execute_insert(self, mgr, db_file):
        info = mgr.add_connection(name="test-db", params={"path": db_file})
        result = mgr.execute(
            info.id,
            "INSERT INTO users (id, name, email) VALUES (99, 'Test', 'test@test.com')",
        )
        assert result.error is None
        assert result.rows_affected == 1


# ---------------------------------------------------------------------------
# ConnectionManager — Sensitive params (vault)
# ---------------------------------------------------------------------------


class TestConnectionManagerSensitive:
    def test_sensitive_params_stored_in_vault(self, mgr, vault_mgr):
        info = mgr.add_connection(
            name="secure-db",
            params={"path": "/tmp/test.db"},
            sensitive_params={"password": "s3cret"},
        )
        # Sensitive params should be retrievable through the connection
        sensitive = mgr._load_sensitive(info.id)
        assert sensitive == {"password": "s3cret"}

    def test_sensitive_params_merged_on_connect(self, mgr, db_file, vault_mgr):
        info = mgr.add_connection(
            name="secure-db",
            params={"path": db_file},
            sensitive_params={"password": "s3cret"},
        )
        # The merge happens inside connect(); we just verify it doesn't crash
        # (SQLite doesn't use the password, but the merge should still work)
        conn = mgr.connect(info.id)
        assert conn is not None

    def test_delete_removes_vault_entry(self, mgr, db_file, vault_mgr):
        info = mgr.add_connection(
            name="secure-db",
            params={"path": db_file},
            sensitive_params={"password": "s3cret"},
        )
        mgr.delete_connection(info.id)
        sensitive = mgr._load_sensitive(info.id)
        assert sensitive == {}  # Should be gone from vault


# ---------------------------------------------------------------------------
# Config defaults
# ---------------------------------------------------------------------------


class TestConfigDefaults:
    def test_db_defaults_registered(self, config_file):
        """Verify that db.connections and db.default_page_size defaults are
        applied when a config is created."""
        from core.config import register_defaults as rd, get_registered_defaults as grd, reset_registered_defaults as rrd

        rrd()
        # Re-register the db defaults (they were cleared above)
        rd({"db": {"connections": [], "default_page_size": 200}})
        defaults = grd()
        assert "db" in defaults
        assert "connections" in defaults["db"]
        assert "default_page_size" in defaults["db"]
        assert defaults["db"]["default_page_size"] == 200
        rrd()

    def test_config_reads_connections(self, config, config_file):
        """Verify that ConnectionsManager can read/write config."""
        connections = config.get("db.connections", [])
        assert isinstance(connections, list)
        assert len(connections) == 0

        config.set("db.connections", [{"id": "x", "name": "test"}])
        config.save()

        config2 = Config([config_file])
        result = config2.get("db.connections")
        assert len(result) == 1
        assert result[0]["name"] == "test"


# ---------------------------------------------------------------------------
# QueryEditorState — roundtrip
# ---------------------------------------------------------------------------


class TestQueryEditorState:
    def test_state_roundtrip(self):
        """Verify that a QueryEditorState captures and restores all
        editor state fields."""
        from skills.database.query_editor import QueryEditorState
        from skills.database.core.db_connections import QueryResult

        result = QueryResult(
            columns=["id", "name"],
            rows=[(1, "Alice"), (2, "Bob")],
            total_count=2,
            has_more=False,
        )

        state = QueryEditorState(
            connection_id="abc123",
            query_text="SELECT * FROM users WHERE id > 0;",
            last_result=result,
            current_query="SELECT * FROM users WHERE id > 0;",
            current_offset=0,
            page_size=100,
        )

        assert state.connection_id == "abc123"
        assert state.query_text == "SELECT * FROM users WHERE id > 0;"
        assert state.last_result is not None
        assert state.last_result.columns == ["id", "name"]
        assert len(state.last_result.rows) == 2
        assert state.current_query == "SELECT * FROM users WHERE id > 0;"
        assert state.current_offset == 0
        assert state.page_size == 100

    def test_state_default_values(self):
        """Verify that optional fields default correctly."""
        from skills.database.query_editor import QueryEditorState

        state = QueryEditorState(
            connection_id="test",
        )

        assert state.query_text == ""
        assert state.last_result is None
        assert state.current_query == ""
        assert state.current_offset == 0
        assert state.page_size == 200

    def test_state_with_pagination(self):
        """Verify that pagination state roundtrips correctly."""
        from skills.database.query_editor import QueryEditorState
        from skills.database.core.db_connections import QueryResult

        result = QueryResult(
            columns=["id"],
            rows=[(i,) for i in range(200)],
            total_count=500,
            has_more=True,
        )

        state = QueryEditorState(
            connection_id="conn1",
            query_text="SELECT * FROM big_table;",
            last_result=result,
            current_query="SELECT * FROM big_table;",
            current_offset=200,
            page_size=200,
        )

        assert state.current_offset == 200
        assert state.last_result.has_more is True
        assert state.last_result.total_count == 500