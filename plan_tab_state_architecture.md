# Plan: Neovim-Style Tab State Architecture

> **Status**: Planned  
> **Scope**: `ui/workspace/tabs.py`, all workspace tab content widgets  
> **Depends on**: Current query editor preservation work (completed)

## 1. Problem

Workspace tab widgets (terminals, query editors, future skill widgets) hold
in-memory state that must survive DOM recomposition (splits, closes). The
current approach extracts snapshots from widgets before the DOM rebuild and
injects them into fresh widgets afterward. This has three costs:

1. **Every new widget type requires edits to `tabs.py`** — isinstance chains in
   `save_state()` and `restore_state()` must be updated, and new snapshot
   fields must be added to `SavedTab`.

2. **Each widget needs boilerplate** — `detach_state()`, `_inherited_snapshot`,
   `_restore_from_snapshot()`, and widget-specific handling in the workspace.

3. **Terminal lifecycle is tangled with the widget** — the `_preserving` flag
   and orphan-emulator cleanup exist because the widget manages a process that
   should outlive the widget. This is a category error.

After two stateful widget types (terminal, query editor), `SavedTab` already
has `inherited_snapshot` and `editor_snapshot` as separate fields. A third
widget type means a third field, a third isinstance check, and a third
injection block. This doesn't scale.

## 2. Proposed Architecture

Borrow neovim's buffer/window model:

- **Buffer** → **TabState**: Pure data object that holds widget state. Survives
  recomposition. Owned by the tab, not the widget.
- **Window** → **TabWidget**: A renderer that reads from and writes to a
  TabState. Destroyed and recreated freely during recomposition.

The widget renders the state. The state outlives the widget. No extraction.
No injection. No snapshots.

## 3. Core Types

### 3.1 `TabState` — base class

```python
# ui/workspace/tabs.py

class TabState:
    """Base class for tab state that survives workspace recomposition.

    Subclass this for each widget type that has in-memory state.
    The TabState object is owned by the tab slot, not by the widget
    — it outlives any particular widget instance.

    Call dispose() when the tab is permanently closed to release
    external resources (PTY processes, database connections, etc.).
    """

    def dispose(self) -> None:
        """Release external resources. No-op in the base class.

        Called when the tab is permanently closed (not during
        recomposition).  Subclasses that own external resources
        (e.g. PTY processes) override this to clean them up.
        """
```

### 3.2 Widget contract

Any widget that renders a `TabState` follows one protocol:

```python
class MyWidget(Widget):
    def __init__(self, state: MyWidgetState):
        super().__init__()
        self.state = state       # shared reference — survives recomposition

    def on_mount(self) -> None:
        # READ from state → populate UI
        ...

    def on_some_user_action(self) -> None:
        # WRITE to state as user interacts
        ...

    def flush_state(self) -> None:
        """Sync current widget state back to self.state.

        Called by WorkspaceTabs.save_state() before recomposition.
        Widgets should write any unsynced UI values (e.g. TextArea.text)
        back to the state object here.
        """
```

Three methods, all optional in practice:
- `__init__` receives a `TabState`, stores it as `self.state`
- `flush_state()` syncs the widget back to state (called before widget death)
- `on_mount()` reads from state to populate the UI

The contract is duck-typed — no interface class needed. If a widget has
`flush_state()`, it will be called. If it doesn't, nothing happens.

### 3.3 Content factory signature change

Current:

```python
content_factory: Callable[[], Widget | None]  # () -> Widget
```

Proposed:

```python
content_factory: Callable[[TabState], Widget | None]  # (TabState) -> Widget
```

The factory receives the state object and returns a configured widget.

## 4. Concrete State Subclasses

### 4.1 `QueryEditorState`

```python
# ui/workspace/query_editor.py

@dataclass
class QueryEditorState(TabState):
    connection_id: str
    query_text: str = ""
    last_result: QueryResult | None = None
    current_query: str = ""
    current_offset: int = 0
    page_size: int = 200
```

The `QueryEditor` widget stores its `QueryResult` in the state object.
When `flush_state()` is called, it syncs the TextArea content. When a fresh
`QueryEditor` mounts, it reads from `state` to populate the UI.

### 4.2 `TerminalState`

```python
# ui/terminal/terminal.py

@dataclass
class TerminalState(TabState):
    command: str
    working_directory: str | None = None
    emulator: Any = None          # live PTY emulator
    screen: Any = None            # pyte Screen
    display: Any = None           # rendered display

    def dispose(self) -> None:
        """Stop the PTY process when the tab is permanently closed."""
        if self.emulator is not None:
            try:
                self.emulator.stop()
            except Exception:
                pass
            self.emulator = None
```

The emulator, screen, and display are plain Python objects stored in the
state. When `TerminalView.on_mount()` runs, it either starts a fresh
emulator or adopts the one in `state.emulator`. On `on_unmount()`, it
flushes references back to state — no process cleanup, no `_preserving` flag.

### 4.3 `FileEditorState`

```python
# ui/workspace/file_editor.py

class FileEditorState(TabState):
    def __init__(self, filepath: str):
        self.filepath = filepath
```

Content lives on disk, so `FileEditorState` only needs the path. The widget
re-reads from disk on mount. No `flush_state()` needed.

## 5. How Recomposition Works

### 5.1 Before (current)

```
save_state():
  for each tab:
    if isinstance(content, TerminalView):     ← isinstance chain
      snapshot = content.detach_emulator()
    elif isinstance(content, QueryEditor):     ← isinstance chain
      snapshot = content.detach_state()
    elif isinstance(content, FileEditor):      ← isinstance chain
      factory = lambda fp=filepath: FileEditor(fp)
    saved_tabs.append(SavedTab(id, label, factory, snapshot))

recompose()  ← destroys all widgets

restore_state():
  for each saved tab:
    content = factory()                        ← creates bare widget
    if isinstance(content, TerminalView):       ← isinstance chain
      content._inherited_snapshot = snapshot   ← inject snapshot
    elif isinstance(content, QueryEditor):      ← isinstance chain
      content._inherited_snapshot = snapshot    ← inject snapshot
    widget.on_mount()                          ← widget reads from snapshot
```

### 5.2 After (proposed)

```
save_state():
  for each tab:
    if hasattr(content, 'flush_state'):       ← generic protocol check
      content.flush_state()                    ← widget writes to TabState
    saved_tabs.append(SavedTab(id, label, state, factory))
                                                ↑ TabState object, not snapshot

recompose()  ← destroys all widgets, TabState objects untouched

restore_state():
  for each saved tab:
    content = factory(state)                   ← factory receives TabState
                                                ↑ widget reads from TabState in on_mount()
```

No isinstance chains. No snapshot injection. No widget-specific code in
`tabs.py`. The factory creates a widget that already has the state reference.

### 5.3 Tab close (permanent)

```python
# In WorkspaceTabs.close_tab()

def close_tab(self, tab_id: str) -> None:
    info = self._tabs.pop(tab_id)
    if info.content is not None:
        try:
            info.content.remove()
        except Exception:
            pass
    if info.state is not None:
        info.state.dispose()           # ← releases PTY, DB connections, etc.
```

### 5.4 Orphan cleanup (pane closed, not just split)

```python
# In Workspace._cleanup_orphaned_states()

def _cleanup_orphaned_states(self, states, restored):
    for pane_id, state in states.items():
        if pane_id in restored:
            continue
        for tab in state.tabs:
            tab.state.dispose()      # ← generic, no terminal-specific code
```

The base `TabState.dispose()` is a no-op. `TerminalState.dispose()` stops the
PTY. `QueryEditorState.dispose()` is a no-op (connections are pooled in
`ConnectionManager`).

## 6. Changes By File

### 6.1 `ui/workspace/tabs.py` — Major refactor

| Change | Detail |
|---|---|
| Add `TabState` base class | With `dispose()` no-op method |
| `TabInfo` gains `state` field | `state: TabState \| None = None` |
| `TabInfo.content_factory` signature | `Callable[[TabState], Widget \| None]` — receives state |
| `SavedTab` simplified | Replace `inherited_snapshot` + `editor_snapshot` with `state: TabState` |
| `save_state()` simplified | Call `flush_state()` if present, carry `state` object directly |
| `restore_state()` simplified | `factory(state)` — no isinstance chains |
| `open_tab()` | Add `state` parameter |
| Remove all `from ui.terminal.terminal import TerminalView` etc. | No widget-specific imports needed |

### 6.2 `ui/workspace/query_editor.py`

| Change | Detail |
|---|---|
| Add `QueryEditorState` dataclass | With `connection_id`, `query_text`, `last_result`, pagination fields |
| `QueryEditor.__init__` | Accept `QueryEditorState` instead of `connection_id` + `prefill` |
| Add `flush_state()` | Sync `TextArea.text` → `state.query_text`, save `_last_result` etc. |
| Remove `QueryEditorSnapshot` | Replaced by `QueryEditorState` |
| Remove `detach_state()` | No longer needed — `flush_state()` writes directly to state |
| Remove `_inherited_snapshot` | No longer needed — widget reads from `self.state` in `on_mount` |
| Remove `_prefill` field | Replaced by `state.query_text` |

### 6.3 `ui/terminal/terminal.py`

| Change | Detail |
|---|---|
| Add `TerminalState` dataclass | With `command`, `working_directory`, `emulator`, `screen`, `display` |
| `TerminalView.__init__` | Accept `TerminalState` instead of `command` + `working_directory` |
| Remove `_preserving` flag | Process lifecycle managed by `TerminalState.dispose()` |
| Remove `_inherited_snapshot` field | Widget reads from `self.state` in `on_mount` |
| `on_mount()` | Adopt `state.emulator` if present, otherwise start fresh |
| `on_unmount()` | Flush to `state`, no process cleanup (widget doesn't own process) |
| Remove `detach_emulator()` | No longer needed — state always has the emulator |

### 6.4 `ui/workspace/file_editor.py`

| Change | Detail |
|---|---|
| `FileEditor.__init__` | Accept `FileEditorState` instead of `filepath` |
| Add `FileEditorState` class | Simple wrapper with `filepath` |

### 6.5 `ui/workspace/workspace.py`

| Change | Detail |
|---|---|
| Remove `_mark_terminals_preserving()` | No longer needed |
| Replace `_cleanup_orphaned_terminals()` | With `_cleanup_orphaned_states()` that calls `tab.state.dispose()` |
| Update `_save_pane_tab_states()` | Uses new `save_state()` |
| Update `_restore_pane_tab_states()` | Uses new `restore_state()` |

### 6.6 `ui/sidebar/panels/db_panel.py`

| Change | Detail |
|---|---|
| `_on_db_open_query()` handler | Create `QueryEditorState`, pass to factory |

### 6.7 `ui/workspace/file_edit_handler.py`

| Change | Detail |
|---|---|
| `_on_files_edit()` handler | Create `FileEditorState`, pass to factory |

### 6.8 `ui/terminal/terminal_handler.py`

| Change | Detail |
|---|---|
| Handler | Create `TerminalState`, pass to factory |

### 6.9 `main.py`

| Change | Detail |
|---|---|
| Welcome tab factory | Update to pass state if applicable |

## 7. Migration Strategy

The refactoring can be done incrementally — one widget type at a time —
because the `TabState` model coexists with the old snapshot model during
transition.

### Step 1: Introduce `TabState` base class and update `TabInfo` / `SavedTab`

- Add `TabState` to `tabs.py` with `dispose()` no-op
- Add `state: TabState | None` field to `TabInfo`
- Add `state: TabState` field to `SavedTab`
- Update `open_tab()` to accept `state` parameter
- Keep old snapshot fields for backward compat during migration
- **All existing code continues to work unchanged**

### Step 2: Migrate `QueryEditor`

- Create `QueryEditorState` dataclass
- Update `QueryEditor.__init__` to accept `QueryEditorState`
- Add `flush_state()` method
- Remove `QueryEditorSnapshot`, `detach_state()`, `_inherited_snapshot`
- Update `_on_db_open_query()` handler to create state + factory
- Update `save_state()` / `restore_state()` to use state-based path for QueryEditor
- **Verify: query editor survives workspace split**

### Step 3: Migrate `TerminalView`

- Create `TerminalState` dataclass with `dispose()` that stops emulator
- Update `TerminalView.__init__` to accept `TerminalState`
- Remove `_preserving`, `_inherited_snapshot`, `TerminalSnapshot`
- Update `on_mount` / `on_unmount` to read/write `self.state`
- Update `terminal_handler.py` to create `TerminalState`
- Remove `_mark_terminals_preserving()` from workspace
- Replace `_cleanup_orphaned_terminals()` with generic `_cleanup_orphaned_states()`
- **Verify: terminal survives workspace split, PTY process survives,
  closed pane kills the PTY**

### Step 4: Migrate `FileEditor`

- Create `FileEditorState` (just `filepath`)
- Update `FileEditor.__init__` to accept `FileEditorState`
- Update `file_edit_handler.py` to create state + factory
- **Verify: file editor survives workspace split**

### Step 5: Remove legacy snapshot fields

- Remove `inherited_snapshot` and `editor_snapshot` from `SavedTab`
- Remove old isinstance chains from `save_state()` / `restore_state()`
- Remove `detach_state()` / `_inherited_snapshot` from all widgets
- Remove `TerminalSnapshot`, `QueryEditorSnapshot` classes
- **Verify all workspace tab types survive recomposition**

### Step 6: Documentation and skill author guide

- Add "Creating Workspace Tabs" guide to docs
- Document `TabState`, `flush_state()`, and the `(TabState) -> Widget` factory
  pattern for skill authors

## 8. Testing

Each migration step should be verified with:

1. **Unit test** for the new `TabState` subclass (data roundtrip, `dispose()`)
2. **Integration test** for workspace split/close with each widget type
3. **Regression test** for workspace split with mixed tab types
   (terminal + query editor + file editor in different panes)

## 9. Benefits Summary

| Concern | Current (snapshots) | Proposed (state model) |
|---|---|---|
| Adding a new widget type | Edit tabs.py (isinstance chains + SavedTab fields) + widget boilerplate | Subclass TabState + add flush_state() to widget. tabs.py untouched. |
| Terminal process lifecycle | `_preserving` flag + orphan cleanup in workspace | `TerminalState.dispose()` — process lives in state |
| Snapshot class count | Grows with each widget type | Zero — TabState replaces all |
| `SavedTab` fields | One snapshot field per widget type | One `state: TabState` field |
| Widget-specific code in tabs.py | Yes (grows with each type) | None |
| Skill author friction | High (5+ touch points across codebase) | Low (3 steps, no framework edits) |