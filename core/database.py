"""Database — SQLite-backed persistence for chats, messages, agents, todos, and
input history.

Includes a ``BaseDBProvider`` abstract class so alternative backends can
be plugged in (see § 6.2), but only ``SQLiteProvider`` is shipped.
"""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any


# ---------------------------------------------------------------------------
# Provider interface
# ---------------------------------------------------------------------------


class BaseDBProvider(ABC):
    """Interface for database backends."""

    @abstractmethod
    def initialize(self, path: str) -> None:
        """Create / open the database and ensure all tables exist."""
        ...

    @abstractmethod
    def execute(self, sql: str, params: tuple = ()) -> list[tuple]:
        """Run a raw query and return all rows."""
        ...

    @abstractmethod
    def close(self) -> None:
        """Release resources."""
        ...


# ---------------------------------------------------------------------------
# SQLite provider
# ---------------------------------------------------------------------------


class SQLiteProvider(BaseDBProvider):
    """SQLite backend — the only bundled provider."""

    def __init__(self) -> None:
        self._conn: sqlite3.Connection | None = None

    # ------------------------------------------------------------------
    # BaseDBProvider
    # ------------------------------------------------------------------

    def initialize(self, path: str) -> None:
        self._conn = sqlite3.connect(path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._create_tables()

    def execute(self, sql: str, params: tuple = ()) -> list[tuple]:
        assert self._conn is not None
        cur = self._conn.execute(sql, params)
        return cur.fetchall()

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _create_tables(self) -> None:
        assert self._conn is not None
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS chats (
                id        TEXT PRIMARY KEY,
                title     TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS messages (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id    TEXT NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
                role       TEXT NOT NULL,
                content    TEXT NOT NULL DEFAULT '',
                thinking   TEXT NOT NULL DEFAULT '',
                tool_calls TEXT,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_messages_chat
                ON messages(chat_id, id);

            CREATE TABLE IF NOT EXISTS agents (
                id            TEXT PRIMARY KEY,
                name          TEXT NOT NULL,
                description   TEXT NOT NULL DEFAULT '',
                system_prompt TEXT NOT NULL DEFAULT '',
                model         TEXT NOT NULL DEFAULT '',
                created_at    TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS todos (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                title       TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                status      TEXT NOT NULL DEFAULT 'pending',
                created_at  TEXT NOT NULL,
                updated_at  TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS input_history (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                input      TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL
            );
            """
        )

    @property
    def conn(self) -> sqlite3.Connection:
        assert self._conn is not None
        return self._conn


# ---------------------------------------------------------------------------
# DatabaseManager — public API
# ---------------------------------------------------------------------------


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class DatabaseManager:
    """High-level persistence API backed by a ``BaseDBProvider``.

    Created with a file path; uses ``SQLiteProvider`` internally.
    """

    def __init__(self, db_path: str, provider: BaseDBProvider | None = None):
        self._provider = provider or SQLiteProvider()
        self._provider.initialize(db_path)

    # ------------------------------------------------------------------
    # Low-level escape hatch (used by tests to inspect tables)
    # ------------------------------------------------------------------

    def _execute(self, sql: str, params: tuple = ()) -> list[tuple]:
        return self._provider.execute(sql, params)

    # ------------------------------------------------------------------
    # Chat CRUD
    # ------------------------------------------------------------------

    def create_chat(self, title: str = "") -> str:
        chat_id = uuid.uuid4().hex
        now = _now()
        self._provider.execute(
            "INSERT INTO chats (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (chat_id, title, now, now),
        )
        return chat_id

    def get_chat(self, chat_id: str) -> dict[str, Any] | None:
        rows = self._provider.execute(
            "SELECT id, title, created_at, updated_at FROM chats WHERE id = ?",
            (chat_id,),
        )
        return dict(rows[0]) if rows else None

    def list_chats(self) -> list[dict[str, Any]]:
        rows = self._provider.execute(
            "SELECT id, title, created_at, updated_at FROM chats ORDER BY updated_at DESC"
        )
        return [dict(r) for r in rows]

    def update_chat(self, chat_id: str, title: str) -> None:
        self._provider.execute(
            "UPDATE chats SET title = ?, updated_at = ? WHERE id = ?",
            (title, _now(), chat_id),
        )

    def delete_chat(self, chat_id: str) -> None:
        self._provider.execute("DELETE FROM chats WHERE id = ?", (chat_id,))

    # ------------------------------------------------------------------
    # Message CRUD
    # ------------------------------------------------------------------

    def save_message(
        self,
        chat_id: str,
        role: str,
        content: str,
        tool_calls: list[dict[str, Any]] | None = None,
        thinking: str = "",
    ) -> int:
        tc_json = json.dumps(tool_calls) if tool_calls is not None else None
        cur = self._provider.conn.execute(
            "INSERT INTO messages (chat_id, role, content, thinking, tool_calls, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (chat_id, role, content, thinking, tc_json, _now()),
        )
        return cur.lastrowid

    def get_messages(self, chat_id: str) -> list[dict[str, Any]]:
        rows = self._provider.execute(
            "SELECT id, chat_id, role, content, thinking, tool_calls, created_at "
            "FROM messages WHERE chat_id = ? ORDER BY id ASC",
            (chat_id,),
        )
        result: list[dict[str, Any]] = []
        for r in rows:
            d = dict(r)
            tc = d.get("tool_calls")
            d["tool_calls"] = json.loads(tc) if tc is not None else None
            result.append(d)
        return result

    def delete_messages(self, chat_id: str) -> None:
        self._provider.execute(
            "DELETE FROM messages WHERE chat_id = ?", (chat_id,)
        )

    # ------------------------------------------------------------------
    # Agent CRUD
    # ------------------------------------------------------------------

    def create_agent(
        self,
        name: str,
        description: str,
        system_prompt: str,
        model: str = "",
        agent_id: str | None = None,
    ) -> str:
        agent_id = agent_id or uuid.uuid4().hex
        self._provider.execute(
            "INSERT INTO agents (id, name, description, system_prompt, model, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (agent_id, name, description, system_prompt, model, _now()),
        )
        return agent_id

    def get_agent(self, agent_id: str) -> dict[str, Any] | None:
        rows = self._provider.execute(
            "SELECT id, name, description, system_prompt, model, created_at "
            "FROM agents WHERE id = ?",
            (agent_id,),
        )
        return dict(rows[0]) if rows else None

    def list_agents(self) -> list[dict[str, Any]]:
        rows = self._provider.execute(
            "SELECT id, name, description, system_prompt, model, created_at "
            "FROM agents ORDER BY name ASC"
        )
        return [dict(r) for r in rows]

    def delete_agent(self, agent_id: str) -> None:
        self._provider.execute("DELETE FROM agents WHERE id = ?", (agent_id,))

    def seed_agents(self, agents: list[dict[str, Any]]) -> None:
        """Insert *agents* if they don't already exist (matched by ``id``)."""
        for a in agents:
            existing = self._provider.execute(
                "SELECT 1 FROM agents WHERE id = ?", (a["id"],)
            )
            if not existing:
                self._provider.execute(
                    "INSERT INTO agents (id, name, description, system_prompt, model, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        a["id"],
                        a["name"],
                        a.get("description", ""),
                        a.get("system_prompt", ""),
                        a.get("model", ""),
                        _now(),
                    ),
                )

    # ------------------------------------------------------------------
    # Todo CRUD
    # ------------------------------------------------------------------

    def create_todo(self, title: str, description: str = "") -> int:
        now = _now()
        cur = self._provider.conn.execute(
            "INSERT INTO todos (title, description, status, created_at, updated_at) "
            "VALUES (?, ?, 'pending', ?, ?)",
            (title, description, now, now),
        )
        return cur.lastrowid

    def get_todo(self, todo_id: int) -> dict[str, Any] | None:
        rows = self._provider.execute(
            "SELECT id, title, description, status, created_at, updated_at "
            "FROM todos WHERE id = ?",
            (todo_id,),
        )
        return dict(rows[0]) if rows else None

    def list_todos(self, status: str | None = None) -> list[dict[str, Any]]:
        if status:
            rows = self._provider.execute(
                "SELECT id, title, description, status, created_at, updated_at "
                "FROM todos WHERE status = ? ORDER BY created_at DESC",
                (status,),
            )
        else:
            rows = self._provider.execute(
                "SELECT id, title, description, status, created_at, updated_at "
                "FROM todos ORDER BY created_at DESC"
            )
        return [dict(r) for r in rows]

    def update_todo(self, todo_id: int, **kwargs: Any) -> None:
        allowed = {"title", "description", "status"}
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            return
        updates["updated_at"] = _now()
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [todo_id]
        self._provider.execute(
            f"UPDATE todos SET {set_clause} WHERE id = ?", tuple(values)
        )

    def delete_todo(self, todo_id: int) -> None:
        self._provider.execute("DELETE FROM todos WHERE id = ?", (todo_id,))

    # ------------------------------------------------------------------
    # Input history
    # ------------------------------------------------------------------

    def add_input(self, text: str) -> int:
        try:
            cur = self._provider.conn.execute(
                "INSERT INTO input_history (input, created_at) VALUES (?, ?)",
                (text, _now()),
            )
            return cur.lastrowid
        except sqlite3.IntegrityError:
            # Duplicate — update timestamp instead
            self._provider.execute(
                "UPDATE input_history SET created_at = ? WHERE input = ?",
                (_now(), text),
            )
            rows = self._provider.execute(
                "SELECT id FROM input_history WHERE input = ?", (text,)
            )
            return rows[0][0] if rows else 0

    def get_input_history(self, limit: int = 50) -> list[str]:
        rows = self._provider.execute(
            "SELECT input FROM input_history ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        return [r[0] for r in rows]

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        self._provider.close()
