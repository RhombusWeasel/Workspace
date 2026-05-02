# Step 11: Database

**Branch:** `step-11-database`  
**Date:** 2026-05-02

---

## Overview

SQLite-backed persistence layer. Provides CRUD for chats, messages, agents,
todos, and input history. Includes a `BaseDBProvider` abstract class for
alternative backends (§ 6.2), but only `SQLiteProvider` is shipped.

---

## Implementation

### `core/database.py`

#### `BaseDBProvider` (abstract)

```python
class BaseDBProvider(ABC):
    def initialize(self, path: str) -> None: ...
    def execute(self, sql: str, params: tuple = ()) -> list[tuple]: ...
    def close(self) -> None: ...
```

#### `SQLiteProvider(BaseDBProvider)`

- Opens connection with `sqlite3.connect(path)`
- `row_factory = sqlite3.Row` for dict-like row access
- `PRAGMA journal_mode=WAL` for concurrent read safety
- `PRAGMA foreign_keys=ON`
- Creates all tables via `CREATE TABLE IF NOT EXISTS`
- Exposes `.conn` property for `INSERT ... RETURNING` / `lastrowid`

#### Table schemas

| Table | Columns | Notes |
|---|---|---|
| `chats` | `id TEXT PK, title TEXT, created_at TEXT, updated_at TEXT` | UUID hex IDs |
| `messages` | `id INTEGER PK AUTOINCREMENT, chat_id TEXT FK→chats, role TEXT, content TEXT, tool_calls TEXT, created_at TEXT` | `tool_calls` is JSON string; index on `(chat_id, id)` |
| `agents` | `id TEXT PK, name TEXT, description TEXT, system_prompt TEXT, model TEXT, created_at TEXT` | Seeded from bundled JSON |
| `todos` | `id INTEGER PK AUTOINCREMENT, title TEXT, description TEXT, status TEXT, created_at TEXT, updated_at TEXT` | Status: `pending`/`in_progress`/`done` |
| `input_history` | `id INTEGER PK AUTOINCREMENT, input TEXT UNIQUE, created_at TEXT` | Deduplicated; on duplicate, updates timestamp |

All timestamps are ISO 8601 UTC strings from `datetime.now(timezone.utc).isoformat()`.

#### `DatabaseManager` — public API

| Category | Methods |
|---|---|
| **Chat** | `create_chat(title="") → str`, `get_chat(id) → dict\|None`, `list_chats() → list[dict]`, `update_chat(id, title)`, `delete_chat(id)` |
| **Message** | `save_message(chat_id, role, content, tool_calls=None) → int`, `get_messages(chat_id) → list[dict]`, `delete_messages(chat_id)` |
| **Agent** | `create_agent(name, description, system_prompt, model="", agent_id=None) → str`, `get_agent(id) → dict\|None`, `list_agents() → list[dict]`, `delete_agent(id)`, `seed_agents(agents)` |
| **Todo** | `create_todo(title, description="") → int`, `get_todo(id) → dict\|None`, `list_todos(status=None) → list[dict]`, `update_todo(id, **kwargs)`, `delete_todo(id)` |
| **Input** | `add_input(text) → int`, `get_input_history(limit=50) → list[str]` |
| **Lifecycle** | `close()`, `_execute(sql, params)` — low-level escape hatch |

**Key behaviors:**

- **Chat delete cascades** — messages are deleted via FK `ON DELETE CASCADE` (SQLite requires `PRAGMA foreign_keys=ON`)
- **Tool calls are JSON** — serialized with `json.dumps()`, deserialized with `json.loads()`; `None` stays `None` in DB
- **Input history is deduplicated** — `input TEXT UNIQUE`; on duplicate, the timestamp is updated to move it to the top. Uses `sqlite3.IntegrityError` catch.
- **Seed agents by id** — checks `SELECT 1 FROM agents WHERE id = ?` before inserting; doesn't overwrite existing agents with the same id
- **Todo update uses kwargs** — only allows `title`, `description`, `status`; unknown kwargs are silently ignored
- **Agent IDs** — optionally overridable via `agent_id=` kwarg (defaults to `uuid4().hex`)

---

## Tests

### `tests/test_database.py` — 51 tests in 9 classes

| Class | Tests | Coverage |
|---|---|---|
| `TestInitialization` | 3 | File creation, table existence, idempotent re-open |
| `TestChatCRUD` | 10 | Create, get, list, update, delete, cascade, missing handling, ordering |
| `TestMessageCRUD` | 7 | Save, get, ordering, empty chat, unknown chat, delete, tool_calls |
| `TestAgentCRUD` | 10 | Create, get, list, delete, seed (insert + no-overwrite), missing handling, default model |
| `TestTodoCRUD` | 11 | Create, get, list with/without filter, update (single + multiple), delete, missing handling |
| `TestInputHistory` | 5 | Add, get, limit, empty, deduplication |
| `TestProvider` | 1 | Default provider is SQLiteProvider |
| `TestToolCallsSerialization` | 2 | None and empty list round-trip through JSON |

All tests use a `db` fixture that creates a fresh `DatabaseManager` backed by a
temp SQLite file (`tmp_path / "test.db"`) and calls `close()` on teardown.

---

## Design Decisions

1. **Dropped Cosmos, kept provider abstraction (§ 6.2).** The `BaseDBProvider`
   ABC remains so users can plug in other backends, but we only ship and test
   `SQLiteProvider`.

2. **`DatabaseManager` wraps a provider.** The public API delegates to a
   provider instance. Construction takes a path and optionally a custom provider.
   This keeps the extension point open without complicating the API.

3. **WAL mode enabled.** `PRAGMA journal_mode=WAL` allows reads concurrent with
   writes — important for a TUI where the app and background agents might both
   access the DB.

4. **`sqlite3.Row` row factory.** Returns dict-like rows that can be passed to
   `dict(r)` for clean output. Tests use `_execute()` which returns tuples
   directly for assertions; the public methods convert rows to dicts.

5. **Input history deduplication via UNIQUE.** Simpler than a SELECT-before-INSERT
   approach. The `IntegrityError` catch updates the timestamp so recently-used
   inputs stay at the top.

6. **Optional `agent_id` on create_agent.** Normally generated as a random UUID,
   but callers can supply an explicit ID for seeding or testing.

---

## Usage Pattern

```python
from core.database import DatabaseManager

# Bootstrap
db = DatabaseManager("/path/to/cody_data.db")

# Chat lifecycle
chat_id = db.create_chat("My Conversation")
db.save_message(chat_id, "user", "Hello!")
db.save_message(chat_id, "assistant", "Hi there!", tool_calls=[
    {"id": "1", "name": "read_file", "arguments": {"path": "/x"}}
])
messages = db.get_messages(chat_id)  # ordered by creation

# Agents (seeded from bundled JSON)
db.seed_agents([
    {"id": "coding-agent", "name": "Coder", "description": "...",
     "system_prompt": "You are a coder.", "model": "codellama"}
])
agents = db.list_agents()

# Queries (for sidebar, etc.)
chats = db.list_chats()           # most recently updated first
todos = db.list_todos("pending")  # filter by status
history = db.get_input_history(10)  # last 10 inputs

db.close()
```
