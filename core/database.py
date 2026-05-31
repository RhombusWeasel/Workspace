"""Database — SQLite-backed persistence for chats, messages, agent definitions, todos, and
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

    def _migrate_agents_table(self) -> None:
        """Rename the old agents table if it has the legacy schema.

        The old agents table (id, name, description, system_prompt, model, created_at)
        is detected by checking if the ``system_prompt`` column exists.  If so,
        the table is renamed to ``agents_legacy`` so that the new ``agents`` table
        DDL (with the new schema) can succeed.

        Data migration from ``agents_legacy`` and ``prompts`` into the new
        ``agents`` table is handled by :class:`~core.agent_registry.AgentManager`
        after database initialization.
        """
        assert self._conn is not None
        # Check if agents table exists with old schema.
        try:
            # Get column names for the agents table.
            cursor = self._conn.execute("PRAGMA table_info(agents)")
            columns = {row[1] for row in cursor.fetchall()}  # row[1] = column name
        except Exception:
            return

        if "system_prompt" in columns:
            # Old schema detected — rename to agents_legacy.
            try:
                self._conn.execute("DROP TABLE IF EXISTS agents_legacy")
                self._conn.execute("ALTER TABLE agents RENAME TO agents_legacy")
                self._conn.commit()
            except Exception:
                pass

    def _create_tables(self) -> None:
        assert self._conn is not None

        # --- Schema migration for the agents table ---
        # The old agents table had columns: id, name, description, system_prompt, model, created_at.
        # The new agents table has additional columns.  If the old schema is detected,
        # rename it so the new table can be created.
        self._migrate_agents_table()

        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS chats (
                id        TEXT PRIMARY KEY,
                title     TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS messages (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id      TEXT NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
                turn_id      TEXT NOT NULL,
                content_type TEXT NOT NULL,
                content      TEXT NOT NULL DEFAULT '',
                created_at   TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_messages_chat
                ON messages(chat_id, id);

            CREATE TABLE IF NOT EXISTS agents (
                id                  TEXT PRIMARY KEY,
                name                TEXT NOT NULL,
                description         TEXT NOT NULL DEFAULT '',
                template            TEXT NOT NULL,
                model               TEXT NOT NULL DEFAULT '',
                provider            TEXT NOT NULL DEFAULT '',
                scope               TEXT NOT NULL DEFAULT 'global',
                tools               TEXT NOT NULL DEFAULT '',
                skills              TEXT NOT NULL DEFAULT '',
                temperature         TEXT NOT NULL DEFAULT '',
                max_tool_iterations TEXT NOT NULL DEFAULT '',
                created_at          TEXT NOT NULL,
                updated_at          TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_agents_scope ON agents(scope);

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
    # Message CRUD (flat schema)
    # ------------------------------------------------------------------

    def save_section(
        self,
        chat_id: str,
        turn_id: str,
        content_type: str,
        content: str,
    ) -> int:
        """Insert a single message section row.

        Each section of a conversation turn (user text, thinking,
        tool_call, response, system) is stored as its own row.
        Rows are ordered by auto-incrementing ``id``.

        Parameters
        ----------
        chat_id:
            Conversation this section belongs to.
        turn_id:
            Groups sections into one exchange (user → assistant).
        content_type:
            One of ``"user"``, ``"thinking"``, ``"tool_call"``,
            ``"response"``, ``"system"``.
        content:
            Text for this section.  For ``tool_call`` rows this is a
            JSON-encoded dict ``{"name": ..., "arguments": ...}``.
        """
        cur = self._provider.conn.execute(
            "INSERT INTO messages (chat_id, turn_id, content_type, content, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (chat_id, turn_id, content_type, content, _now()),
        )
        return cur.lastrowid

    def load_sections(self, chat_id: str) -> list[dict[str, Any]]:
        """Return all message sections for *chat_id* ordered by ``id``.

        Each dict has keys ``id``, ``chat_id``, ``turn_id``,
        ``content_type``, ``content``, ``created_at``.
        """
        rows = self._provider.execute(
            "SELECT id, chat_id, turn_id, content_type, content, created_at "
            "FROM messages WHERE chat_id = ? ORDER BY id ASC",
            (chat_id,),
        )
        return [dict(r) for r in rows]

    def reconstruct_history(self, chat_id: str) -> list[dict[str, Any]]:
        """Reconstruct LLM-consumable message list from flat sections.

        Walks sections in ``id`` order, groups by ``turn_id``, and
        builds the structured dicts that ``agent.stream_chat()``
        expects:

        * User sections → ``{"role": "user", "content": ...}``
        * Assistant sections (thinking / tool_call / response) are
          merged into one ``{"role": "assistant", ...}`` dict per turn.
        * System sections → ``{"role": "system", "content": ...}``

        Tool-call content is decoded from JSON.  Multiple thinking
        or response sections within the same turn are concatenated.
        """
        sections = self.load_sections(chat_id)
        history: list[dict[str, Any]] = []

        # Bucket sections by turn_id, preserving order of first appearance.
        turn_order: list[str] = []
        turns: dict[str, list[dict[str, Any]]] = {}
        for sec in sections:
            tid = sec["turn_id"]
            if tid not in turns:
                turn_order.append(tid)
                turns[tid] = []
            turns[tid].append(sec)

        for tid in turn_order:
            turn_sections = turns[tid]
            # Check if this turn contains assistant content.
            has_assistant = any(
                s["content_type"] in ("thinking", "tool_call", "response")
                for s in turn_sections
            )

            for s in turn_sections:
                ct = s["content_type"]

                if ct == "user":
                    history.append({"role": "user", "content": s["content"]})

                elif ct == "system":
                    history.append({"role": "system", "content": s["content"]})

                elif ct == "thinking":
                    # Find or create the assistant message for this turn.
                    asst = self._ensure_assistant(history, tid)
                    asst["thinking"] = (asst.get("thinking") or "") + s["content"]

                elif ct == "tool_call":
                    asst = self._ensure_assistant(history, tid)
                    tc_list = asst.setdefault("tool_calls", [])
                    try:
                        tc_list.append(json.loads(s["content"]))
                    except (json.JSONDecodeError, TypeError):
                        pass  # Skip malformed entries

                elif ct == "response":
                    asst = self._ensure_assistant(history, tid)
                    # Accumulate response text (may span multiple sections).
                    asst["content"] = (asst.get("content") or "") + s["content"]

        return history

    @staticmethod
    def _ensure_assistant(
        history: list[dict[str, Any]], turn_id: str
    ) -> dict[str, Any]:
        """Find or create the assistant message dict for *turn_id*.

        The assistant dict is always the last entry in *history* when
        it exists (because user always precedes assistant).
        """
        if history and history[-1].get("role") == "assistant" and history[-1].get("_turn_id") == turn_id:
            return history[-1]
        asst: dict[str, Any] = {"role": "assistant", "_turn_id": turn_id}
        history.append(asst)
        return asst

    def delete_messages(self, chat_id: str) -> None:
        self._provider.execute(
            "DELETE FROM messages WHERE chat_id = ?", (chat_id,)
        )

    # ------------------------------------------------------------------
    # Agent CRUD (deprecated — use AgentManager from core.agent_registry)
    # ------------------------------------------------------------------

    # The old agents table had columns: id, name, description, system_prompt, model, created_at.
    # The new agents table has: id, name, description, template, model, provider, scope,
    # tools, skills, temperature, max_tool_iterations, created_at, updated_at.
    # These deprecated methods map the old API to the new table for backward compat.

    def create_agent(
        self,
        name: str,
        description: str,
        system_prompt: str,
        model: str = "",
        agent_id: str | None = None,
    ) -> str:
        import warnings
        warnings.warn(
            "DatabaseManager.create_agent() is deprecated — use AgentManager.create_agent()",
            DeprecationWarning,
            stacklevel=2,
        )
        agent_id = agent_id or uuid.uuid4().hex
        now = _now()
        self._provider.execute(
            "INSERT INTO agents "
            "(id, name, description, template, model, provider, scope, "
            "tools, skills, temperature, max_tool_iterations, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (agent_id, name, description, system_prompt, model, "", "global",
             "", "", "", "", now, now),
        )
        return agent_id

    def get_agent(self, agent_id: str) -> dict[str, Any] | None:
        import warnings
        warnings.warn(
            "DatabaseManager.get_agent() is deprecated — use AgentManager.get_agent()",
            DeprecationWarning,
            stacklevel=2,
        )
        rows = self._provider.execute(
            "SELECT id, name, description, template, model, provider, scope, "
            "tools, skills, temperature, max_tool_iterations, created_at, updated_at "
            "FROM agents WHERE id = ?",
            (agent_id,),
        )
        return dict(rows[0]) if rows else None

    def list_agents(self) -> list[dict[str, Any]]:
        import warnings
        warnings.warn(
            "DatabaseManager.list_agents() is deprecated — use AgentManager.list_agents()",
            DeprecationWarning,
            stacklevel=2,
        )
        rows = self._provider.execute(
            "SELECT id, name, description, template, model, provider, scope, "
            "tools, skills, temperature, max_tool_iterations, created_at, updated_at "
            "FROM agents ORDER BY name ASC"
        )
        return [dict(r) for r in rows]

    def delete_agent(self, agent_id: str) -> None:
        import warnings
        warnings.warn(
            "DatabaseManager.delete_agent() is deprecated — use AgentManager.delete_agent()",
            DeprecationWarning,
            stacklevel=2,
        )
        self._provider.execute("DELETE FROM agents WHERE id = ?", (agent_id,))

    def seed_agents(self, agents_data: list[dict[str, Any]]) -> None:
        """Insert agents if they don't already exist (matched by ``id``).

        Deprecated — AgentManager handles seeding internally.
        """
        import warnings
        warnings.warn(
            "DatabaseManager.seed_agents() is deprecated — seeding is handled by AgentManager",
            DeprecationWarning,
            stacklevel=2,
        )
        for a in agents_data:
            existing = self._provider.execute(
                "SELECT 1 FROM agents WHERE id = ?", (a["id"],)
            )
            if not existing:
                now = _now()
                self._provider.execute(
                    "INSERT INTO agents "
                    "(id, name, description, template, model, provider, scope, "
                    "tools, skills, temperature, max_tool_iterations, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        a["id"],
                        a["name"],
                        a.get("description", ""),
                        a.get("system_prompt", ""),
                        a.get("model", ""),
                        "", "global", "", "", "", "",
                        now, now,
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
