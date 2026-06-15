# Session Persistence

**File:** `core/session.py`
**Depends on:** `core.pane_tree` (Pane, get_leaves, pane_tree_to_dict, pane_tree_from_dict), `context.AppContext`

---

## Purpose

`SessionManager` saves and restores workspace state across app restarts. The session captures:

- Pane tree layout (splits, leaf IDs)
- Open tabs in each leaf (type, label, persistent state)
- Which pane has focus
- Sidebar visibility (left and right)

Session file: `{working_directory}/.agents/session.json`

---

## Architecture

```
SessionManager
    │
    ├── save(workspace, left_sidebar_hidden, right_sidebar_hidden)
    │   ├── pane_tree_to_dict(workspace.tree)        ← serialize pane tree
    │   ├── workspace._save_pane_tab_states()          ← collect tab state
    │   ├── _serialise_saved_tabs()                    ← TabTypeHandler.serialise()
    │   └── _write(data)                               ← write JSON to disk
    │
    └── restore(workspace, left_sidebar, right_sidebar)
        ├── _read()                                     ← read JSON from disk
        ├── pane_tree_from_dict(tree_dict)              ← rebuild pane tree
        ├── TabTypeHandler.deserialise()                ← rebuild TabState objects
        ├── workspace.recompose()                      ← rebuild DOM
        └── tabs_widget.open_tab() for each tab        ← restore content
```

---

## TabTypeHandler Registry

Each tab type (chat, terminal, file_editor, welcome, query_editor) registers a handler that knows how to serialise and deserialise its `TabState` to/from a plain dict.

```python
@dataclass
class TabTypeHandler:
    tab_type: str                                              # e.g. "chat", "terminal"
    serialise: Callable[[TabState], dict]                      # TabState → JSON-safe dict
    deserialise: Callable[[dict, AppContext], TabState]        # dict + ctx → TabState
    content_factory: Callable[[TabState], Widget | None]       # TabState → widget
    make_label: Callable[[TabState], str] | None = None        # TabState → tab label
```

### Registration

```python
from core.session import register_tab_type, TabTypeHandler

register_tab_type(TabTypeHandler(
    tab_type="my_tab",
    serialise=lambda state: {"my_param": state.my_param},
    deserialise=lambda data, ctx: MyTabState(my_param=data["my_param"]),
    content_factory=_create_my_content,
    make_label=lambda state: f"My Tab: {state.my_param}",
))
```

### Built-in tab types

| Tab type | Module | State class |
|---|---|---|
| `chat` | `skills/chat/chat_tab.py` | `ChatTabState` |
| `terminal` | `skills/terminal/terminal_state.py` | `TerminalState` |
| `file_editor` | `ui/workspace/file_editor.py` | `FileEditorState` |
| `welcome` | `ui/workspace/welcome_view.py` | `WelcomeTabState` |
| `query_editor` | `skills/database/query_editor_tab.py` | `QueryEditorState` |

---

## SessionManager API

### Constructor

```python
mgr = SessionManager(session_path, ctx)
```

| Parameter | Type | Description |
|---|---|---|
| `session_path` | `str` | Path to session JSON file (typically `{wd}/.agents/session.json`) |
| `ctx` | `AppContext` | App context for DB lookups during restore |

### `has_session → bool`

Whether a session file exists on disk.

### `save(workspace, left_sidebar_hidden, right_sidebar_hidden) → None`

Capture current workspace state and write to disk. Uses `workspace._save_pane_tab_states()` to collect tab state from each pane.

### `restore(workspace, left_sidebar, right_sidebar) → bool`

Restore workspace state from disk. Returns `True` on success, `False` if no session file exists or restoration failed.

Restoration is two-phase:
1. **Phase 1:** Set the tree and focused ID, then `recompose()` the DOM
2. **Phase 2:** After recomposition, populate each leaf's `WorkspaceTabs` with restored tabs

Tabs are opened in batch mode (`begin_batch()` / `end_batch()`) so only the active tab's content is mounted.

---

## Session File Format

```json
{
  "version": 1,
  "focused_pane_id": "main",
  "sidebar": {
    "left_hidden": false,
    "right_hidden": true
  },
  "pane_tree": {
    "id": "abc123",
    "direction": "h",
    "ratio": 0.5,
    "children": [
      {"id": "main", "content": null},
      {"id": "def456", "content": null}
    ]
  },
  "tabs_by_pane": {
    "main": [
      {
        "tab_type": "chat",
        "tab_data": {"chat_id": "uuid", "agent_id": "uuid"},
        "label": "Chat",
        "tab_id": "chat"
      }
    ],
    "def456": [
      {
        "tab_type": "terminal",
        "tab_data": {"command": null, "working_directory": "/path"},
        "label": "Terminal",
        "tab_id": "term-1"
      }
    ]
  }
}
```

---

## Graceful Degradation

- If a chat ID referenced in session data no longer exists in the DB, the `deserialise` method returns `None` and the tab is skipped
- If a file path no longer exists, the tab is skipped
- If a tab type has no registered handler, a warning is logged and the tab is skipped
- If the session file version doesn't match `SESSION_VERSION`, a `ValueError` is raised and the session is not restored

---

## Design Decisions

1. **TabTypeHandler registry over hardcoded types** — Each skill owns its own (de)serialisation logic. `session.py` has no knowledge of specific tab types.

2. **Two-phase restore** — The DOM must be rebuilt before tabs can be populated. Recomposition happens in Phase 1, tab restoration in Phase 2 via `run_worker()`.

3. **Batch tab opening** — Without batching, each `open_tab()` triggers `_refresh()` which mounts content asynchronously. If the next `open_tab()` runs before the mount completes, both content widgets end up visible. `begin_batch()` / `end_batch()` prevents this.

4. **Class name → tab type mapping** — `SessionManager._find_handler()` converts `ChatTabState` → `"chat"`, `TerminalState` → `"terminal"`, etc. by stripping suffixes and converting CamelCase to snake_case. This convention keeps serialisation simple.

5. **Save uses `_save_pane_tab_states()`** — Rather than walking the DOM directly, session save uses the workspace's existing tab state collection, which reliably captures state during shutdown.