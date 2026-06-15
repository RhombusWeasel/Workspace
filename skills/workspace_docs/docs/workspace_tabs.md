# Workspace Tabs

**Files:** `ui/workspace/tabs.py`, `ui/workspace/workspace.py`
**Depends on:** `core/pane_tree.py`, `core/session.py`, Textual widgets

---

## Purpose

Workspace tabs provide a tabbed container within each workspace pane.
Each pane starts with a `WorkspaceTabs` widget that can host multiple
closeable, switchable tabs. Tabs are opened by skills (chat, terminal,
file editor) or by user actions (file browser, leader chords).

The critical feature is **state persistence across workspace
recomposition**: when the user splits or closes a pane, the DOM is
destroyed and rebuilt. Tab state survives this cycle via the
`TabState` model — each tab owns a persistent state object that
outlives any widget instance.

Tabs also persist across app restarts via **session persistence**
(`SessionManager` and `TabTypeHandler`). See the [Session Persistence](#session-persistence) section below.

---

## Architecture

```
Workspace
  └── PaneContainer
       └── WorkspaceTabs
            ├── Tab bar (label + × close buttons)
            └── Content area (one visible widget at a time)
                 ├── ChatTabState → ChatManager
                 ├── TerminalState → TerminalView
                 └── FileEditorState → FileEditor
```

When the workspace splits or a pane closes, `_recompose_preserving_content()`
runs this cycle:

```
1. save_state()      ← calls flush_state() on each content widget
2. recompose()       ← Textual destroys and rebuilds the DOM
3. restore_state()   ← content_factory(state) creates fresh widgets
4. cleanup_orphans() ← dispose() on tabs whose pane was closed
```

Each content widget is **recreated from its `TabState`** by the
`content_factory`. State objects are carried through `SavedTab`
snapshots and handed to the new widget — no snapshot extraction or
deep-copy injection is needed.

---

## TabState — The Persistence Contract

`TabState` is the base class for all persistent tab state. It is
**not** a widget — it's a plain Python object owned by the tab slot,
not by the widget instance.

```python
class TabState:
    """Base class for tab state that survives workspace recomposition."""

    def dispose(self) -> None:
        """Release external resources. Called when the tab is permanently closed."""
```

### Pattern 1: State on disk (no flush needed)

Content lives on disk and can be re-read on mount. The `TabState` only needs an identifier. No `flush_state()` needed.

```python
class FileEditorState(TabState):
    def __init__(self, filepath: str):
        self.filepath = filepath

class FileEditor(Widget):
    def __init__(self, state: FileEditorState):
        super().__init__()
        self.state = state

    def on_mount(self) -> None:
        self._content = open(self.state.filepath).read()
```

### Pattern 2: Live state in TabState (flush to sync)

The `TabState` **is** the authoritative source of truth. `flush_state()` copies references from the widget back to `TabState` before recomposition.

```python
class TerminalState(TabState):
    def __init__(self, command=None, working_directory=None):
        self.command = command
        self.working_directory = working_directory
        self.emulator = None    # live PTY
        self.screen = None      # pyte character buffer
        self.display = None     # Rich Text rendered lines

    def dispose(self) -> None:
        if self.emulator is not None:
            self.emulator.stop()

class TerminalView(Widget):
    def flush_state(self) -> None:
        if self._pty is None:
            return
        if self._pty.emulator is not None:
            self.state.emulator = self._pty.emulator
        if hasattr(self._pty, "_screen") and self._pty._screen is not None:
            self.state.screen = self._pty._screen
        if hasattr(self._pty, "_display") and self._pty._display is not None:
            self.state.display = self._pty._display
```

### Pattern 3: In-memory state with flush and rebuild

Widget accumulates state in its own fields. `flush_state()` copies to `TabState`. On restore, the widget rebuilds its display from the saved data.

```python
class ChatTabState(TabState):
    def __init__(self, ctx=None):
        super().__init__()
        self._ctx = ctx
        self._history = []
        self._sections = []
        self._agent = None
        self._chat_id = None

    def dispose(self) -> None:
        self._db = None
        self._chat_id = None

class ChatManager(Widget):
    def flush_state(self) -> None:
        if self._state is not None:
            self._state._history = self._history
            self._state._sections = self._sections

    def on_mount(self) -> None:
        if self._state is not None and self._sections:
            self.run_worker(self._rebuild_display_from_sections())
```

### Choosing a pattern

| Pattern | When to use | flush_state()? | Rebuild display? |
|---|---|---|---|
| **1: Disk** | Content comes from the filesystem | No | No (re-read) |
| **2: Live state** | TabState holds live objects (PTY, connection) | Yes — sync refs back | No (adopt existing) |
| **3: In-memory + flush** | Widget accumulates state in its own fields | Yes — copy to TabState | Yes — replay from saved data |

---

## How to Add a Workspace Tab

### Step 1: Define TabState subclass

```python
from ui.workspace.tabs import TabState

class MyTabState(TabState):
    def __init__(self, my_param: str):
        self.my_param = my_param

    def dispose(self) -> None:
        pass  # release external resources here
```

### Step 2: Create the content widget

```python
from textual.widget import Widget

class MyWidget(Widget):
    def __init__(self, state: MyTabState):
        super().__init__()
        self.state = state

    def flush_state(self) -> None:
        # Only needed for Pattern 2/3
        pass

    def on_mount(self) -> None:
        # Pattern 1: re-read from disk
        # Pattern 2: adopt live objects from state
        # Pattern 3: rebuild display from state data
        ...
```

### Step 3: Define the content factory

```python
def _create_my_content(state: TabState) -> MyWidget:
    if isinstance(state, MyTabState):
        return MyWidget(state)
    return MyWidget(MyTabState(default_param))
```

### Step 4: Register a session handler (for persistence across restarts)

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

### Step 5: Open the tab programmatically

```python
from core.events import register_handler
from context import AppContext

@register_handler("my_skill.open")
def _on_my_open(data: dict, ctx: AppContext) -> None:
    app = ctx.app
    if app is None:
        return

    from ui.workspace.workspace import Workspace, PaneContainer
    from ui.workspace.tabs import WorkspaceTabs

    try:
        workspace = app.query_one(Workspace)
    except Exception:
        return

    try:
        container = app.query_one(f"#pane-{workspace.focused_id}", PaneContainer)
    except Exception:
        return

    try:
        tabs = container.query_one(WorkspaceTabs)
    except Exception:
        return

    state = MyTabState(my_param=data.get("param", "default"))
    tabs.open_tab("my-tab", "My Skill", state=state, content_factory=_create_my_content)
```

---

## The flush_state / save_state / restore_state Cycle

### Before recomposition: save_state()

`Workspace._recompose_preserving_content()` calls `_save_pane_tab_states()`,
which iterates every pane's `WorkspaceTabs` and calls `save_state()`:

```python
def save_state(self) -> SavedTabState:
    for tab_id, info in self._tabs.items():
        if info.content is not None and hasattr(info.content, "flush_state"):
            info.content.flush_state()
        # TabState and content_factory are carried directly
```

### During recomposition: DOM destruction

`await self.recompose()` destroys the old DOM tree. All widget instances are removed. `TabState` objects survive in `SavedTab` snapshots.

### After recomposition: restore_state()

New `WorkspaceTabs` instances are created. `restore_state()` is called:

```python
def restore_state(self, state: SavedTabState) -> None:
    for saved in state.tabs:
        content = saved.content_factory(saved.state)
        # The fresh widget reads from the TabState in on_mount()
```

### After recomposition: cleanup

Tabs whose pane was **closed** (not just split) are not restored.
Their `TabState.dispose()` is called to release external resources.

---

## Session Persistence

`SessionManager` (from `core/session.py`) saves and restores workspace
state across app restarts. Each tab type registers a `TabTypeHandler`
that knows how to serialise and deserialise its `TabState` to/from a
plain dict. The session file is at `{working_directory}/.agents/session.json`.

### TabTypeHandler

```python
@dataclass
class TabTypeHandler:
    tab_type: str
    serialise: Callable[[TabState], dict]
    deserialise: Callable[[dict, AppContext], TabState]
    content_factory: Callable[[TabState], Widget | None]
    make_label: Callable[[TabState], str] | None = None
```

Registration happens at module import time. See [session.md](session.md) for full details.

### Save/Restore cycle

1. **Save**: Captures pane tree, focused pane, tab state per leaf, and sidebar visibility. Uses `workspace._save_pane_tab_states()` and `TabTypeHandler.serialise()`.
2. **Restore**: Reads session JSON, rebuilds pane tree, deserialises each tab via `TabTypeHandler.deserialise()`, opens tabs in batch mode.
3. **Graceful degradation**: If a chat ID no longer exists or a file path is gone, `deserialise()` returns `None` and the tab is skipped.

---

## TabState Rules

1. **TabState must outlive the widget.** Never store DOM references or Textual widget instances in TabState.
2. **flush_state() must copy, not move.** The widget may still be briefly alive after `flush_state()` returns.
3. **dispose() must release external resources.** Kill PTY processes, close connections, etc.
4. **Content factories must be callable.** They receive a `TabState` and return a widget. Async setup should happen in `on_mount()` via `run_worker()`.
5. **Tab IDs must be unique within a pane.** Use stable IDs for singletons (e.g. `"chat"`) and unique IDs for multi-instance tabs (e.g. `"term-1"`).
6. **Mutable list fields: use .clear() not reassignment.** If a list is shared between widget and TabState, use `self._history.clear()` instead of `self._history = []`.
7. **Async display rebuilds must yield to the event loop.** Use `run_worker()` with `await asyncio.sleep(0)` between section creation and content updates.

---

## Reference: WorkspaceTabs API

### open_tab()

```python
tabs.open_tab(
    tab_id: str,           # unique ID within this pane
    label: str,           # tab bar label
    *,
    state: TabState,       # persistent state object
    content: Widget | None = None,    # pre-built widget (rare)
    content_factory: Callable[[TabState], Widget | None] | None = None,
)
```

Opens a new tab or switches to an existing one. If `tab_id` already exists, the existing tab is activated.

### close_tab()

```python
tabs.close_tab(tab_id: str) -> None
```

Closes the tab, removes content from the DOM, calls `state.dispose()`.

### switch_tab()

```python
tabs.switch_tab(tab_id: str) -> None
```

Activates a tab without closing others. Posts `TabSwitched` message.

### Properties

| Property | Type | Description |
|---|---|---|
| `tab_count` | `int` | Number of open tabs |
| `active_tab_id` | `str \| None` | ID of the currently active tab |

### Messages

| Message | When |
|---|---|
| `TabSwitched(tab_id)` | Active tab changed |
| `TabClosed(tab_id)` | Tab was closed |

---

## Design Decisions

1. **TabState is not a widget** — State objects must survive DOM destruction. Storing widget references creates dangling pointers.
2. **flush_state() is opt-in** — Only Pattern 2/3 widgets need it. Disk-backed widgets don't.
3. **content_factory over content** — Pre-built widgets break on recomposition. Factories create fresh instances that read from persistent state.
4. **dispose() for cleanup, not __del__** — Python's `__del__` is unreliable. `dispose()` is called explicitly.
5. **Visibility toggling, not DOM mount/unmount** — Switching tabs uses `.display` to show/hide content, preventing PTY process kills.
6. **SavedTab carries state objects directly** — No deep copy or serialisation for recomposition. The same state object is passed to the content factory.
7. **Session persistence uses TabTypeHandler** — Each skill owns its own (de)serialisation logic. session.py has no knowledge of specific tab types.