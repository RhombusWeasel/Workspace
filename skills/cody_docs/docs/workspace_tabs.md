# Workspace Tabs

**Files:** `ui/workspace/tabs.py`, `ui/workspace/workspace.py`
**Depends on:** `core/pane_tree.py`, Textual widgets

---

## Purpose

Workspace tabs provide a tabbed container within each workspace pane.
Each pane starts with a `WorkspaceTabs` widget that can host multiple
closeable, switchable tabs.  Tabs are opened by plugins (chat, terminal,
file editor) or by user actions (file browser, leader chords).

The critical feature is **state persistence across workspace
recomposition**: when the user splits or closes a pane, the DOM is
destroyed and rebuilt.  Tab state survives this cycle via the
`TabState` model — each tab owns a persistent state object that
outlives any widget instance.

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
`content_factory`.  State objects are carried through `SavedTab`
snapshots and handed to the new widget — no snapshot extraction or
deep-copy injection is needed.

---

## TabState — The Persistence Contract

`TabState` is the base class for all persistent tab state.  It is
**not** a widget — it's a plain Python object owned by the tab slot,
not by the widget instance.  It survives DOM destruction because it
lives in `WorkspaceTabs._tabs` and travels through `SavedTab` during
recomposition.

```python
class TabState:
    """Base class for tab state that survives workspace recomposition."""

    def dispose(self) -> None:
        """Release external resources. Called when the tab is permanently closed."""
```

Subclasses store whatever data the content widget needs to
reconstruct itself after recomposition.  There are three patterns,
depending on where the authoritative state lives:

### Pattern 1: State on disk (no flush needed)

When the content lives on disk and can be re-read on mount, the
`TabState` only needs an identifier (e.g. a file path).  The widget
re-reads from disk every time it mounts — **no `flush_state()` is
needed** because the source of truth is the filesystem.

**Example:** `FileEditorState`

```python
class FileEditorState(TabState):
    """Only the file path — content lives on disk."""

    def __init__(self, filepath: str):
        self.filepath = filepath


class FileEditor(Widget):
    def __init__(self, state: FileEditorState):
        super().__init__()
        self.state = state

    def on_mount(self) -> None:
        # Re-read from disk every time
        self._content = open(self.state.filepath).read()
```

### Pattern 2: Live state in TabState (no flush needed)

When the `TabState` **is** the authoritative source of truth, the
widget reads from and writes to it directly.  Since the state object
is shared between widget instances (it's the same object before and
after recomposition), no `flush_state()` is needed — mutations are
already visible to the next widget.

**Example:** `TerminalState`

```python
class TerminalState(TabState):
    """Owns the live PTY process, pyte screen, and rendered display."""

    def __init__(self, command=None, working_directory=None):
        self.command = command
        self.working_directory = working_directory
        self.emulator = None    # live PTY
        self.screen = None      # pyte character buffer
        self.display = None     # Rich Text rendered lines

    def dispose(self) -> None:
        if self.emulator is not None:
            self.emulator.stop()  # kill the PTY process


class TerminalView(Widget):
    def __init__(self, state: TerminalState):
        super().__init__()
        self.state = state

    def flush_state(self) -> None:
        """Sync widget references back to state before recomposition."""
        if self._pty is None:
            return
        if self._pty.emulator is not None:
            self.state.emulator = self._pty.emulator
        if hasattr(self._pty, "_screen") and self._pty._screen is not None:
            self.state.screen = self._pty._screen
        if hasattr(self._pty, "_display") and self._pty._display is not None:
            self.state.display = self._pty._display

    def on_mount(self) -> None:
        if self.state.emulator is not None:
            # Adopt the live emulator — keep the PTY process running
            self._pty.emulator = self.state.emulator
            # Restore screen and display so previous output is visible
            if self.state.screen is not None:
                self._pty._screen = self.state.screen
            if self.state.display is not None:
                self._pty._display = self.state.display
        else:
            # Fresh terminal — spawn a new shell
            self._pty.start()
```

Even though the `TerminalView` stores state internally (in `_pty`),
`flush_state()` copies references back to `TerminalState` so the
next widget can adopt them.  The emulator's PTY process keeps running
through the recomposition.

### Pattern 3: In-memory state with flush (rebuild display on restore)

When the widget has in-memory state that isn't naturally shared
(e.g. conversation history that the widget accumulates), the
`TabState` stores snapshots that the widget **flushes** before
recomposition and **restores** after.  The widget also needs to
**rebuild its visual display** from the flushed data.

**Example:** `ChatTabState`

```python
class ChatTabState(TabState):
    """Owns conversation state for the AI chat."""

    def __init__(self, ctx=None):
        super().__init__()
        self._ctx = ctx
        self._history = []     # LLM conversation history
        self._sections = []    # flat section list
        self._agent = None     # LLM agent
        self._tools = None    # tool list
        self._db = None        # database reference
        self._chat_id = None   # database chat ID

    def dispose(self) -> None:
        self._db = None
        self._chat_id = None


class ChatManager(Widget):
    def __init__(self):
        super().__init__()
        self._state = None     # reference to ChatTabState
        self._history = []
        self._sections = []
        self._agent = None
        self._tools = None
        self._db = None
        self._chat_id = None

    def set_state(self, state) -> None:
        """Adopt conversation data from ChatTabState."""
        self._state = state
        self._history = state._history
        self._sections = state._sections
        self._agent = state._agent
        self._tools = state._tools
        self._db = state._db
        self._chat_id = state._chat_id

    def flush_state(self) -> None:
        """Copy widget state back to ChatTabState."""
        if self._state is not None:
            self._state._history = self._history
            self._state._sections = self._sections
            self._state._agent = self._agent
            self._state._tools = self._tools
            self._state._db = self._db
            self._state._chat_id = self._chat_id

    def on_mount(self) -> None:
        # If state was restored, rebuild the visual display
        if self._state is not None and self._sections:
            self.run_worker(self._rebuild_display_from_sections())

    async def _rebuild_display_from_sections(self) -> None:
        """Replay persisted sections into ChatDisplay to restore visuals."""
        ...
```

### Choosing a pattern

| Pattern | When to use | flush_state()? | Rebuild display? |
|---|---|---|---|
| **1: Disk** | Content comes from the filesystem | No | No (re-read) |
| **2: Live state** | TabState holds live objects (PTY, connection) | Yes — sync refs back | No (adopt existing) |
| **3: In-memory + flush** | Widget accumulates state in its own fields | Yes — copy to TabState | Yes — replay from saved data |

---

## How to Add a Workspace Tab

### Step 1: Define your TabState subclass

Create a `TabState` subclass that holds all data the widget needs to
reconstruct itself after recomposition.  Choose a pattern from the
table above.

```python
# plugins/my_plugin/my_tab.py
from ui.workspace.tabs import TabState


class MyTabState(TabState):
    """Persistent state for my workspace tab."""

    def __init__(self, my_param: str):
        self.my_param = my_param
        # Add mutable fields for Pattern 3:
        # self._data = []

    def dispose(self) -> None:
        """Release external resources when permanently closed."""
        # Close connections, stop processes, etc.
```

### Step 2: Create the content widget

The widget receives its ``TabState`` and uses it to set up its state.
For Pattern 2 or 3, implement ``flush_state()``.  For Pattern 3, also
implement ``set_state()`` to restore data into the widget's own fields
after recomposition.

```python
# plugins/my_plugin/my_widget.py
from textual.widget import Widget
from plugins.my_plugin.my_tab import MyTabState


class MyWidget(Widget):
    """Widget that renders inside a workspace tab."""

    def __init__(self, state: MyTabState):
        super().__init__()
        self.state = state
        self._data = state._data if hasattr(state, '_data') else []

    def flush_state(self) -> None:
        """Sync widget state back to TabState before recomposition."""
        # Only needed for Pattern 3
        if hasattr(self.state, '_data'):
            self.state._data = self._data

    def on_mount(self) -> None:
        """Set up the widget after mounting."""
        # For Pattern 1: re-read from disk
        # For Pattern 2: adopt live objects from state
        # For Pattern 3: rebuild display from state data
        ...
```

### Step 3: Define the content factory

The content factory is a **callable** that receives a ``TabState`` and
returns a new widget instance (or ``None``).  ``WorkspaceTabs`` calls it
during ``restore_state()`` to create the fresh widget after recomposition.
The factory may return ``None``; if it does, the tab's previous content
widget is reused without recreation.

```python
# plugins/my_plugin/my_tab.py (continued)

def _create_my_content(state: TabState) -> MyWidget:
    """Content factory — creates MyWidget from TabState."""
    if isinstance(state, MyTabState):
        return MyWidget(state)
    return MyWidget(MyTabState(default_param))
```

### Step 4: Open the tab programmatically

When your plugin needs to open a tab (e.g. in response to an event
or leader chord), find the focused pane's `WorkspaceTabs` and call
`open_tab()`.

```python
# plugins/my_plugin/my_handler.py
from core.events import register_handler
from context import AppContext
from plugins.my_plugin.my_tab import MyTabState, _create_my_content


@register_handler("my_plugin.open")
def _on_my_open(data: dict, ctx: AppContext) -> None:
    """Open a my-plugin tab in the focused workspace pane."""
    app = ctx.app
    if app is None:
        return

    from ui.workspace.workspace import Workspace, PaneContainer
    from ui.workspace.tabs import WorkspaceTabs

    try:
        workspace = app.query_one(Workspace)
    except Exception:
        return

    focused_id = workspace.focused_id
    try:
        container = app.query_one(f"#pane-{focused_id}", PaneContainer)
    except Exception:
        return

    # Find or create WorkspaceTabs in the pane
    try:
        tabs = container.query_one(WorkspaceTabs)
    except Exception:
        tabs = WorkspaceTabs()
        async def _do() -> None:
            await container.mount(tabs)
            _open_my_tab(tabs, data)
        app.run_worker(_do())
        return

    _open_my_tab(tabs, data)


def _open_my_tab(tabs: WorkspaceTabs, data: dict) -> None:
    """Open the tab, switching to it if it already exists."""
    tab_id = "my-tab"  # unique ID for this tab type

    if tab_id in tabs._tabs:
        tabs.switch_tab(tab_id)
        return

    state = MyTabState(my_param=data.get("param", "default"))
    tabs.open_tab(
        tab_id,
        "My Plugin",
        state=state,
        content_factory=_create_my_content,
    )
```

### Step 5: Register leader chords (optional)

If your tab should be openable via a keyboard chord, register it
with the leader registry.

```python
# plugins/my_plugin/__init__.py
from core.leader import register_submenu, register_action
from plugins.my_plugin.my_handler import _on_my_open  # noqa: F401

def register_my_leader_chords() -> None:
    register_submenu(["m"], "My Plugin")
    register_action(
        ["m", "o"],
        "Open",
        event_type="my_plugin.open",
    )

register_my_leader_chords()
```

### Step 6: Add CSS (optional)

Create a `.tcss` file in your plugin directory for widget styling.
Textual CSS is collected automatically from plugin directories.

---

## The flush_state / save_state / restore_state Cycle

Understanding this cycle is essential for any tab that holds
in-memory state (Pattern 2 or 3).

### Before recomposition: save_state()

When the workspace is about to recompose (split/close),
`Workspace._recompose_preserving_content()` calls `_save_pane_tab_states()`,
which iterates every pane's `WorkspaceTabs` and calls `save_state()`:

```python
def save_state(self) -> SavedTabState:
    for tab_id, info in self._tabs.items():
        # Ask the widget to flush its state back to TabState
        if info.content is not None and hasattr(info.content, "flush_state"):
            info.content.flush_state()
        # TabState and content_factory are carried directly
```

**Your widget's `flush_state()` is called here.**  It should copy all
in-memory state from the widget to the `TabState` object.

### During recomposition: DOM destruction

`await self.recompose()` destroys the old DOM tree.  All widget
instances are removed.  The `TabState` objects survive because they
live in `SavedTab` snapshots, not in the DOM.

### After recomposition: restore_state()

New `WorkspaceTabs` instances are created by `compose()`.  Then
`restore_state()` is called with the saved state:

```python
def restore_state(self, state: SavedTabState) -> None:
    for saved in state.tabs:
        # Create fresh content from the factory
        content = saved.content_factory(saved.state)
        # The fresh widget reads from the TabState in on_mount()
```

**Your content factory is called here.**  It should create a fresh
widget that reads from the `TabState`.

### After recomposition: cleanup

Tabs whose pane was **closed** (not just split) are not restored.
Their `TabState.dispose()` is called to release external resources
(kill processes, close connections, etc.).

---

## TabState Rules

1. **TabState must outlive the widget.**  The state object is not a
   widget — it's a plain Python object.  Never store DOM references
   or Textual widget instances in TabState.

2. **flush_state() must copy, not move.**  After `flush_state()`
   returns, the widget may still be briefly alive.  Copy references
   rather than clearing them from the widget.

3. **dispose() must release external resources.**  When a pane is
   closed, `dispose()` is called on orphaned tab states.  Kill PTY
   processes, close database connections, etc.

4. **Content factories must be callable.**  They receive a `TabState`
   and return a widget.  They should not perform async operations —
   only construct the widget.  Async setup (e.g. rebuilding a
   display) should happen in `on_mount()` via `run_worker()`.

5. **Tab IDs must be unique within a pane.**  Opening a tab with an
   existing ID switches to it rather than creating a duplicate.  Use
   a stable ID for singleton tabs (e.g. `"chat"`) and unique IDs for
   multi-instance tabs (e.g. `"term-1"`, `"term-2"`).

6. **Mutable list fields: use .clear() not reassignment.**  If your
   widget has a list that's also referenced by `TabState` (via
   `set_state()`), use `self._history.clear()` instead of
   `self._history = []`.  Reassignment breaks the shared reference.
   Alternatively, call `flush_state()` immediately after reassignment
   to sync the new list back to TabState.

7. **Async display rebuilds must yield to the event loop.**  If your
   `on_mount()` rebuilds visual content (e.g. replaying sections into
   a Markdown tree), use `run_worker()` with `await asyncio.sleep(0)`
   between section creation and content updates.  Textual widgets need
   one event loop tick to mount their DOM children before `await
   md.update()` can render into them.

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

Opens a new tab or switches to an existing one.  If `tab_id` already
exists, the existing tab is activated (no content replacement).

One of `content` or `content_factory` should be provided:
- **`content`**: a pre-built widget (use only for simple, stateless tabs)
- **`content_factory`**: a callable that creates the widget from state
  (required for state-persistent tabs that survive recomposition)

### close_tab()

```python
tabs.close_tab(tab_id: str) -> None
```

Closes the tab, removes its content from the DOM, and calls
`state.dispose()`.  If the closed tab was active, switches to a
neighboring tab.

### switch_tab()

```python
tabs.switch_tab(tab_id: str) -> None
```

Activates a tab without closing others.  Posts `TabSwitched` message.

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

## Example: Complete Minimal Tab Plugin

This example shows a complete workspace-tab-backed plugin using
Pattern 1 (state on disk).  It opens a text file viewer in a
workspace tab.

```python
# plugins/viewer/__init__.py
"""Viewer plugin — opens text files in workspace tabs."""
from plugins.viewer.viewer_tab import register_viewer_chords  # noqa: F401
register_viewer_chords()
```

```python
# plugins/viewer/viewer_tab.py
from ui.workspace.tabs import TabState, WorkspaceTabs
from core.events import register_handler
from core.leader import register_submenu, register_action
from context import AppContext
from textual.widget import Widget
from textual.widgets import Static


# --- TabState (Pattern 1: disk) ---


class ViewerTabState(TabState):
    """State for a viewer tab — just the file path."""

    def __init__(self, filepath: str):
        self.filepath = filepath

    def dispose(self) -> None:
        pass  # no external resources


# --- Content widget ---


class ViewerWidget(Widget):
    """Read-only text viewer."""

    def __init__(self, state: ViewerTabState):
        super().__init__()
        self.state = state

    def compose(self):
        # Re-read from disk every mount (Pattern 1)
        try:
            content = open(self.state.filepath).read()
        except Exception:
            content = f"(error reading {self.state.filepath})"
        yield Static(content)


# --- Content factory ---


def _create_viewer(state: TabState) -> ViewerWidget:
    if isinstance(state, ViewerTabState):
        return ViewerWidget(state)
    raise ValueError("Expected ViewerTabState")


# --- Event handler ---


@register_handler("viewer.open")
def _on_viewer_open(data: dict, ctx: AppContext) -> None:
    filepath = data.get("path", "")
    if not filepath:
        return
    app = ctx.app
    if app is None:
        return

    from ui.workspace.workspace import Workspace, PaneContainer

    try:
        workspace = app.query_one(Workspace)
    except Exception:
        return

    try:
        container = app.query_one(
            f"#pane-{workspace.focused_id}", PaneContainer
        )
    except Exception:
        return

    try:
        tabs = container.query_one(WorkspaceTabs)
    except Exception:
        tabs = WorkspaceTicks()

        async def _do() -> None:
            await container.mount(tabs)
            _open_tab(tabs, filepath)

        app.run_worker(_do())
        return

    _open_tab(tabs, filepath)


def _open_tab(tabs: WorkspaceTabs, filepath: str) -> None:
    import os
    tab_id = f"viewer-{os.path.basename(filepath)}"
    state = ViewerTabState(filepath)
    label = os.path.basename(filepath)
    tabs.open_tab(tab_id, label, state=state, content_factory=_create_viewer)


# --- Leader chord ---


def register_viewer_chords() -> None:
    register_submenu(["v"], "Viewer")
    register_action(
        ["v", "o"],
        "Open",
        event_type="viewer.open",
    )
```

---

## Testing Workspace Tab Persistence

Test that your tab's state survives a workspace recomposition by
simulating the save → recompose → restore cycle:

```python
import pytest
from textual.app import App, ComposeResult
from ui.workspace.tabs import WorkspaceTabs, TabState


class TabsTestApp(App):
    CSS = "WorkspaceTabs { height: 100%; width: 100%; }"

    def compose(self) -> ComposeResult:
        self.tabs = WorkspaceTabs()
        yield self.tabs


async def test_my_tab_survives_recomposition():
    async with TabsTestApp().run_test() as pilot:
        tabs = pilot.app.tabs
        await pilot.pause()

        # Open a tab with state
        state = MyTabState(my_param="hello")
        tabs.open_tab("my-tab", "My Tab", state=state,
                       content_factory=_create_my_content)
        await pilot.pause()

        # Modify state through the widget
        widget = tabs._tabs["my-tab"].content
        widget.add_data("world")
        await pilot.pause()

        # Simulate recomposition: save → restore
        saved = tabs.save_state()
        tabs.restore_state(saved)
        await pilot.pause()

        # Verify state survived
        assert "my-tab" in tabs._tabs
        new_widget = tabs._tabs["my-tab"].content
        assert new_widget is not widget  # new widget instance
        assert new_widget.state is state  # same TabState object
        assert new_widget.state._data == ["world"]  # data survived
```

---

## Design Decisions

1. **TabState is not a widget** — State objects must survive DOM
   destruction.  Storing widget references in TabState would create
   dangling pointers after recomposition.

2. **flush_state() is opt-in** — Only widgets with in-memory state
   (Pattern 3) need `flush_state()`.  Disk-backed widgets (Pattern 1)
   and live-state widgets (Pattern 2) either don't need it or already
   keep state in sync.

3. **content_factory over content** — Pre-built widgets break on
   recomposition (Textual can't remount removed widgets).  Factories
   create fresh instances that read from the persistent state.

4. **dispose() for cleanup, not __del__** — Python's `__del__` is
   unreliable for resource cleanup.  `dispose()` is called explicitly
   by the workspace when a pane is closed, guaranteeing PTY processes
   and connections are released.

5. **Visibility toggling, not DOM mount/unmount** — Switching tabs
   uses `.display` to show/hide content widgets, not `.remove()` /
   `.mount()`.  This prevents terminal PTY processes from being
   killed on tab switch.

6. **SavedTab carries state objects directly** — No deep copy or
   serialisation.  `TabState` objects are carried by reference through
   `SavedTab`.  This works because they're plain Python objects, not
   Textual widgets.  The same state object is passed to the content
   factory after recomposition.