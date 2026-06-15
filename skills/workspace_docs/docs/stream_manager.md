# Stream Manager

**File:** `core/stream_manager.py`
**Depends on:** `core.providers.base.StreamChunk`, `core.database.DatabaseManager`, `core.agent.Agent`, `asyncio`

---

## Purpose

`StreamManager` owns the LLM streaming task and persists content to the database as it arrives. The chat display polls the DB via `refresh_from_sections()` instead of receiving chunk callbacks — this decouples the UI from the stream lifecycle and ensures content survives workspace recomposition.

When the workspace is recomposed (split/close), the old `ChatManager` is destroyed but the stream continues writing to the DB. The new `ChatManager` re-subscribes by `chat_id` and rebuilds from the latest rows.

On permanent tab close, `ChatTabState.dispose()` calls `cancel()`, which aborts the agent and cancels the background task.

---

## Architecture

```
ChatManager.start_stream()
    │
    ▼
StreamManager.start(agent, history, user_text, ...)
    │
    ├── Creates asyncio.Task → _run_stream()
    │
    ▼
_run_stream():
    │
    ├── async for chunk in agent.stream_chat(...)
    │   ├── _handle_chunk() → detect transitions, accumulate text
    │   ├── Periodic _write_text_sections() (every 0.25s)
    │   ├── Tool calls → finalize section → upsert_streaming_section()
    │   └── Tool results → update existing section rows
    │
    └── Final _write_all_sections() → finalize + flush everything
```

---

## Sequential Section Tracking

When the LLM produces multiple thinking→response transitions within a single turn (e.g. during tool-calling loops), each section gets its own unique `section_id` and DB row. This preserves order:

```
Thinking #1 → Response #1 → Tool Call #1 → Thinking #2 → Response #2
```

Transitions are detected in `_handle_chunk()` when a thinking chunk arrives while the current section is response (or vice versa), or when tool calls arrive. The `_ensure_section()` method:

- If the current section is the same type → continue accumulating
- If the current section is a different type → finalize it, start a new section
- Returns the `section_id` of the active section

Section IDs follow the format `{turn_id}-{content_type}-{counter}`, e.g. `t1-thinking-1`, `t1-response-2`.

---

## API

### `start(agent, history, user_text, *, tools, db, chat_id, turn_id, flush_interval) → str`

Start a streaming conversation. Returns a `stream_id` (UUID hex) for tracking.

| Parameter | Type | Description |
|---|---|---|
| `agent` | `Agent` | LLM agent to stream from |
| `history` | `list[dict]` | Conversation history |
| `user_text` | `str` | New user message |
| `tools` | `list[dict] \| None` | Available tools |
| `db` | `DatabaseManager \| None` | Database for persistence |
| `chat_id` | `str \| None` | Chat ID for DB rows |
| `turn_id` | `str \| None` | Turn ID for DB rows |
| `flush_interval` | `float` | Seconds between DB writes (default 0.25) |

### `cancel(stream_id) → None`

Abort the stream, cancel the background task, and call `agent.abort()`. Removes the stream from the manager.

### `has_stream(stream_id) → bool`

Whether the stream is still running.

### `get_stream_ids() → list[str]`

All active stream IDs.

### `get_usage(stream_id) → StreamChunk | None`

Returns the final chunk with usage data for a completed stream, or `None` if the stream is still running, was cancelled, or produced no usage data. Callers use this to update the context usage bar after streaming completes.

---

## DB Interaction

StreamManager writes to the `messages` table via `DatabaseManager`:

- `upsert_streaming_section(chat_id, turn_id, section_id, content_type, content)` — Insert or update a streaming section row. Used for response text, thinking text, and tool calls.
- Tool calls are stored as JSON: `{"name": "...", "arguments": {...}}`. When a tool result arrives, the row is updated to `{"name": "...", "arguments": {...}, "result": "..."}`.
- The `section_id` column (TEXT NOT NULL DEFAULT '') enables in-place updates during streaming.

Sections are flushed to the DB every `flush_interval` seconds (default 0.25s) during streaming, and unconditionally on stream completion or cancellation.

---

## Stream Lifecycle

### Normal completion
1. `_run_stream()` iterates `agent.stream_chat()` to completion
2. Final `_write_all_sections()` flushes all accumulated text
3. If no sections exist, an empty response row is created
4. Stream metadata is cleaned up

### Cancellation
1. `cancel()` removes the task and calls `agent.abort()`
2. The `CancelledError` handler in `_run_stream()` appends `*[aborted]*` to the last response section
3. All sections are flushed to DB

### Error
1. The `Exception` handler creates an error response section: `Error: {exc}`
2. All sections are flushed to DB
3. Stream metadata is cleaned up

---

## Design Decisions

1. **DB as source of truth** — The chat display polls the DB via `refresh_from_sections()` rather than receiving chunk callbacks. This decouples UI from stream lifecycle and ensures content survives widget destruction during recomposition.

2. **Sequential sections** — Earlier implementations merged all thinking into one row and all response into another. Sequential tracking preserves the natural order of the LLM's output.

3. **Periodic flush, not per-chunk** — Accumulated text is written to the DB every 250ms rather than on every chunk. This reduces DB writes while keeping latency low.

4. **Upsert, not insert** — Streaming sections are updated in-place via `upsert_streaming_section()`. This avoids duplicate rows for the same content.

5. **Usage captured after stream** — Token usage data is stored in `_usage` after the stream completes. Callers retrieve it via `get_usage()` to update the context usage bar.