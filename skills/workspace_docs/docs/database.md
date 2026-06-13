# Database Manager

**File:** `core/database.py`
**Depends on:** `sqlite3`, `abc`

---

## Purpose

SQLite-backed persistence for chats, messages, agents, todos, and input
history.  The `DatabaseManager` provides a high-level CRUD API on top of
a pluggable `BaseDBProvider` — currently only `SQLiteProvider` exists, but
the abstraction allows alternative backends.

---

## Schema

```sql
-- Conversations
CREATE TABLE chats (
    id         TEXT PRIMARY KEY,
    title      TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Message sections (flat, ordered by auto-increment id)
CREATE TABLE messages (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id      TEXT NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
    turn_id      TEXT NOT NULL,
    content_type TEXT NOT NULL,  -- "user", "thinking", "tool_call", "response", "system"
    content      TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL
);

-- Custom agents (LLM personalities)
CREATE TABLE agents (
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

-- Todo tracking
CREATE TABLE todos (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'pending',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

-- Input history for autocomplete
CREATE TABLE input_history (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    input      TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);
```

---

## DatabaseManager API

### Constructor

```python
db = DatabaseManager(db_path="/path/to/workspace_data.db")
```

### Chat CRUD

| Method | Signature | Description |
|---|---|---|
| `create_chat` | `(title="") → str` | Create a new chat, return its ID |
| `get_chat` | `(chat_id) → dict \| None` | Get a chat by ID |
| `list_chats` | `() → list[dict]` | All chats, newest first |
| `update_chat` | `(chat_id, title)` | Update the chat title |
| `delete_chat` | `(chat_id)` | Delete a chat and its messages |

### Message Sections

| Method | Signature | Description |
|---|---|---|
| `save_section` | `(chat_id, turn_id, content_type, content) → int` | Insert a section row |
| `load_sections` | `(chat_id) → list[dict]` | All sections for a chat, ordered by `id` |
| `reconstruct_history` | `(chat_id) → list[dict]` | Build LLM-consumable message list from flat sections |
| `delete_messages` | `(chat_id)` | Delete all sections for a chat |

#### Content types

| Type | Role | Description |
|---|---|---|
| `"user"` | User input | Human's message text |
| `"thinking"` | Chain-of-thought | Reasoning from DeepSeek-R1, Qwen, etc. |
| `"tool_call"` | Tool invocation | JSON `{"name": ..., "arguments": ...}` |
| `"response"` | Assistant text | LLM output |
| `"system"` | System message | System prompt turns |

#### `reconstruct_history()`

This method walks flat sections and builds the structured message list
that `Agent.stream_chat()` expects:

- User sections → `{"role": "user", "content": ...}`
- Assistant sections (thinking, tool_call, response) merged into one
  `{"role": "assistant", ...}` dict per turn
- System sections → `{"role": "system", "content": ...}`
- Tool-call content is JSON-decoded into `tool_calls` lists

### Agent CRUD

> **Deprecated**: Agent CRUD methods on `DatabaseManager` are deprecated and
> delegate to `AgentManager`.  Use `ctx.agents.create_agent()` etc. in new
> code.  These methods will emit `DeprecationWarning` and may be removed in a
> future version.

| Method | Signature | Description |
|---|---|---|
| `create_agent` | `(name, description, system_prompt, model="") → str` | **Deprecated** — Create agent, return ID |
| `get_agent` | `(agent_id) → dict \| None` | **Deprecated** — Get an agent by ID |
| `list_agents` | `() → list[dict]` | **Deprecated** — All agents, sorted by name |
| `delete_agent` | `(agent_id)` | **Deprecated** — Delete an agent |
| `seed_agents` | `(agents_list)` | **Deprecated** — Insert agents if they don't already exist |

### Todo CRUD

| Method | Signature | Description |
|---|---|---|
| `create_todo` | `(title, description="") → int` | Create a todo |
| `get_todo` | `(todo_id) → dict \| None` | Get a todo |
| `list_todos` | `(status=None) → list[dict]` | All todos, optionally filtered by status |
| `update_todo` | `(todo_id, **kwargs)` | Update title, description, or status |
| `delete_todo` | `(todo_id)` | Delete a todo |

### Delete Sections from Turn

| Method | Signature | Description |
|---|---|---|
| `delete_sections_from_turn` | `(chat_id, turn_id)` | Delete all sections for a specific turn |

Used by the "revert to checkpoint" feature to wipe DB entries from a
conversation point forward.

### Input History

| Method | Signature | Description |
|---|---|---|
| `add_input` | `(text) → int` | Add or update an input record |
| `get_input_history` | `(limit=50) → list[str]` | Recent inputs, newest first |

### Lifecycle

| Method | Signature | Description |
|---|---|---|
| `close` | `()` | Close the database connection |

---

## Using DatabaseManager in a Plugin

Access via `ctx.database` (AppContext):

```python
@register_handler("chat.save")
def _on_chat_save(data: dict, ctx: AppContext) -> None:
    db = ctx.database
    chat_id = db.create_chat(title=data.get("title", "New Chat"))
    db.save_section(chat_id, turn_id="t1", content_type="user", content="Hello")
    db.save_section(chat_id, turn_id="t1", content_type="response", content="Hi!")
```

---

## Design Decisions

1. **Flat section schema** — Messages are stored as flat rows (one per
  section) rather than nested JSON.  This makes querying and pagination
  easy and avoids JSON parsing overhead.

2. **BaseDBProvider abstraction** — Allows swapping out SQLite for an
  alternative backend without changing the public API.  Currently only
  `SQLiteProvider` exists.

3. **WAL mode** — SQLite WAL journal mode for better concurrent read
  performance.

4. **`reconstruct_history()` as a read method** — History reconstruction
  is a query-time operation, not a storage-time operation.  This keeps
  the write path simple.