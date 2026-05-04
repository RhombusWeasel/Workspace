# Step 15b — Decouple ChatPanel into ui/chat/

## Overview

Split the monolithic `ui/sidebar/panels/chat_panel.py` (320 lines) into three
focused, reusable components under a new `ui/chat/` package.  The sidebar
`ChatPanel` becomes a thin wrapper, and the same `ChatManager` can be embedded
directly in workspace panes without the sidebar tie-in.

## File structure

```
ui/chat/
├── __init__.py           # empty package marker
├── chat_input.py         # ChatInput widget — wraps Input, posts ChatSubmitted
├── chat_display.py       # ChatDisplay widget — wraps Tree, streaming API
└── chat_manager.py       # ChatManager widget — composes input+display, orchestrator

ui/sidebar/panels/
└── chat_panel.py         # Thin sidebar tab wrapper (35 lines, was 320)

tests/
├── test_chat_input.py    # 5 tests — input structure, submission, clear, focus
├── test_chat_display.py  # 21 tests — tree, user msgs, assistant turns, sections
├── test_chat_manager.py  # 11 tests — composition, streaming, persistence
└── test_chat_panel.py    # 6 tests — wrapper integration, streaming, persistence
```

## Component responsibilities

### ChatInput (`ui/chat/chat_input.py`)

- Wraps a Textual `Input` widget with placeholder "Type a message…"
- Intercepts `Input.Submitted` and reposts as `ChatInput.ChatSubmitted(text)` for
  non-empty, non-whitespace submissions
- Public API: `focus()`, `clear()`

### ChatDisplay (`ui/chat/chat_display.py`)

- Wraps a `Tree` widget with root node "Conversation"
- Manages turn lifecycle:
  - `add_user_message(text)` — creates user leaf node, returns node ID
  - `begin_assistant_turn()` — creates assistant branch with three section branches
    (thinking, tools, response), each containing a `PersistentMarkdown` leaf
  - `update_section(section, text)` — replaces Markdown content for a section.
    Marks the section active so `finalize_turn()` preserves it.
  - `finalize_turn()` — removes empty section children, rebuilds tree, clears
    internal state (`_section_md`, `_active_sections`)
- `PersistentMarkdown` — subclass of `Markdown` that restores content on remount
  (survives tree branch collapse/expand). Does NOT call `super().on_mount()` since
  `Markdown` doesn't define that handler.

Internal state per turn:
- `_section_md: dict[str, Markdown]` — maps section name → Markdown widget
- `_active_sections: set[str]` — sections that received content
- `_active_asst_id: str | None` — current assistant node ID

### ChatManager (`ui/chat/chat_manager.py`)

- Widget that composes `ChatDisplay` + `ChatInput` in a `Vertical` container
- Auto-focuses input on mount
- Listens for `ChatInput.ChatSubmitted` via `on_chat_input_chat_submitted`
- Kicks off `_handle_submit(text)` as a worker
- Manages: `_history` (message list), `_db` / `_chat_id` (persistence),
  `_agent` (LLM), `_tools`
- Setup: `set_agent()`, `set_tools()`, `wire_from_context(ctx)` — the latter
  wires DB and auto-creates an `OllamaProvider`-based `Agent` if none was set
- Streaming loop in `_handle_submit()`:
  1. Adds user message to display + history
  2. Calls `begin_assistant_turn()` on display
  3. Streams chunks from `agent.stream_chat()`, routing to display sections:
     - `chunk.thinking` → `update_section("thinking", ...)`
     - `chunk.tool_calls` → `update_section("tools", ...)` (also blanks thinking)
     - `chunk.content` → `update_section("response", ...)`
  4. On exception: shows error in response section
  5. Post-turn: appends assistant to history, saves to DB, finalizes display
- `_save_turn()` — persists user + assistant messages to DB. Silently swallows
  errors (fire-and-forget persistence)

### ChatPanel (`ui/sidebar/panels/chat_panel.py`)

- Registered as sidebar tab: `name="chat"`, `icon="\uf4ad"`, `side="right"`
- Composes a single `ChatManager`
- On mount: wires the manager from `self.app.context` if available
- 35 lines total — just the sidebar glue

## Message flow

```
User types → Input.Submitted
  → ChatInput.on_input_submitted() strips text, posts ChatSubmitted
    → ChatManager.on_chat_input_chat_submitted() clears input, starts worker
      → _handle_submit() runs agent streaming loop
        → ChatDisplay.update_section() updates Markdown widgets
      → _save_turn() persists to DB
      → ChatDisplay.finalize_turn() cleans up empty sections
      → ChatInput.focus() returns focus to input
```

## Testing approach

All tests use Textual's `pilot` with `run_test()`.  Fake agents are used
everywhere — no real LLM calls.

Key patterns:
- **ChatDisplay tests** — use a minimal `ChatDisplayTestApp` that composes
  `ChatDisplay` directly.  Call display methods and query the `Tree._node_map`
  to verify structure.
- **ChatManager tests** — use `ChatManagerTestApp`.  Simulate user input by
  posting `Input.Submitted` on the inner `ChatInput`'s `Input`, then wait
  for the streaming worker via `_settle(pilot, n=15)`.
- **Persistence tests** — use `ChatManagerDBTestApp` which sets `AppContext`
  with a temp-database and calls `wire_from_context()` in `on_mount`.
- **Fake chunk objects** — created with `type('C', (), {...})()` to mimic
  `StreamChunk` without importing it.

## Design decisions

1. **Option A (direct orchestration)** over message bus — ChatManager holds
   references to its children and calls methods directly.  No need for
   message-passing indirection between co-located components.

2. **`update_section()` replaces, doesn't accumulate** — The display is a
   dumb view.  Accumulation happens in the manager's streaming loop.  This
   keeps the display simple and testable in isolation.

3. **`PersistentMarkdown` in chat_display.py** — It's a display concern.
   The manager never needs to know about tree re-mount quirks.

4. **Manager owns `_wire_agent()`** — The auto-wiring with `OllamaProvider`
   is a bootstrapping convenience.  Callers can always use `set_agent()` with
   a custom agent instead.

5. **Fire-and-forget persistence** — `_save_turn()` catches all exceptions.
   Chat should never break because the DB is unavailable.

## Reuse in workspace panes

The `ChatManager` widget has no sidebar dependency.  To embed it in a
workspace pane:

```python
workspace.set_content(pane_id, ChatManager())
# Then wire from context:
ctx = self.app.context
manager = self.query_one(ChatManager)
manager.wire_from_context(ctx)
```
