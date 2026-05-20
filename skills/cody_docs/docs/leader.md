# Leader Chords

**File:** `core/leader.py`
**Depends on:** None (pure data, zero Textual dependency)

---

## Purpose

The leader registry defines a tree of keyboard chords triggered by
`Ctrl+Space`.  Users chain key presses to navigate submenus and reach
actions — like Vim's leader key or Spacemacs.  Plugins register chords
at import time; the UI overlay reads the tree to display options and
dispatches actions when a leaf is reached.

---

## Architecture

```
Ctrl+Space
    │
    ▼
LeaderOverlay reads leader.get_root()
    │
    ├── w  →  "Workspace" (submenu)
    │    ├── s  →  "Split" (submenu)
    │    │   ├── h  →  "Split H"  (action → event "leader.workspace.split_h")
    │    │   └── v  →  "Split V"  (action → event "leader.workspace.split_v")
    │    ├── c  →  "Close"  (action → event "leader.workspace.close")
    │    └── t  →  "Toggle" (submenu)
    │        ├── l  →  "Toggle Left" (action)
    │        └── r  →  "Toggle Right" (action)
    ├── a  →  "Chat" (action → event "chat.open")
    └── t  →  "Terminal" (submenu)
         └── o  →  "Open"  (action → event "terminal.open")
```

- Each node is a `LeaderNode` — either a submenu (has children) or a
  leaf action (has a handler or event_type).
- The overlay posts a `CodyEvent` when an action is reached (via
  `event_type`), or calls a `handler` callable directly.

---

## API

### Convenience Functions (module-level singleton)

The module exposes a `LeaderRegistry` singleton named `leader`.  Convenience
functions operate on it:

#### `register_action(keys, label, handler=None, labels=None, event_type=None)`

Register a leaf action at the given key path:

```python
from core.leader import register_action, register_submenu

register_submenu(["m"], "My Plugin")
register_action(
    ["m", "o"],
    "Open",
    event_type="my_plugin.open",
)
```

| Parameter | Type | Description |
|---|---|---|
| `keys` | `list[str]` | Sequence of single-char keys (e.g. `["w", "s", "h"]`). |
| `label` | `str` | Display string for the leaf node. |
| `handler` | `Callable \| None` | Called when the chord completes.  Mutually exclusive with `event_type`. |
| `labels` | `dict[str, str] \| None` | Human-readable labels for intermediate auto-created nodes. |
| `event_type` | `str \| None` | If set, posts a `CodyEvent` with this type instead of calling `handler`. |

#### `register_submenu(keys, label)`

Ensure a labelled submenu node exists at `keys`:

```python
register_submenu(["m"], "My Plugin")
```

If the node already exists (created as an intermediate during an earlier
`register_action`), its label is updated and `is_submenu` is set.
Raises `ValueError` if the node is already a leaf action.

#### `find_node(keys) → LeaderNode | None`

Walk `keys` from the root and return the resulting node, or `None`.

#### `reset_leader()`

Clear all chords.  Use between tests.

### Direct Registry API

```python
from core.leader import leader

root = leader.get_root()
node = leader.find_node(["w", "s", "h"])
leader.register_action(["x", "y"], "Test", event_type="test.event")
leader.reset()
```

---

## LeaderNode

```python
@dataclass
class LeaderNode:
    label: str = ""           # Display string (empty for auto-created intermediates)
    children: dict[str, LeaderNode] = {}  # Single-char key → child node
    handler: Callable | None = None        # Called when leaf is reached
    is_submenu: bool = False               # True if explicitly registered as submenu
    event_type: str | None = None          # If set, posts CodyEvent instead of calling handler
```

---

## Event-Driven vs Handler-Driven Actions

There are two ways a leaf action can dispatch:

1. **Event-driven** (preferred): Set `event_type` on the action.  When the
   user completes the chord, the leader overlay posts
   `CodyEvent(event_type)`.  A `@register_handler` somewhere in the codebase
   handles it.

   ```python
   register_action(["w", "s", "h"], "Split H",
                   event_type="leader.workspace.split_h")
   ```

   ```python
   @register_handler("leader.workspace.split_h")
   def _on_split_h(data, ctx):
       ...
   ```

2. **Handler-driven**: Pass a `handler` callable directly.  Called when the
   chord completes.  Use for simple actions that don't need the full
   event system.

   ```python
   register_action(["q"], "Quit", handler=lambda: os._exit(0))
   ```

**Prefer event-driven** for plugin actions — it decouples the leader
chord definition from the handler logic.

---

## Conflict Detection

The registry detects conflicts at registration time:

- Registering an action where a submenu already exists → `ValueError`
- Registering a submenu where an action already exists → `ValueError`
- Registering an action at a path that already has an action → `ValueError`

These are raised immediately during plugin loading, so conflicts are
caught at startup rather than at runtime.

---

## Registering Chords from a Plugin

Chords are typically registered from the plugin's `__init__.py` at load
time:

```python
# plugins/my_plugin/__init__.py
"""My Plugin."""

from core.leader import register_submenu, register_action

# Define the submenu and actions
register_submenu(["m"], "My Plugin")
register_action(
    ["m", "o"],
    "Open",
    event_type="my_plugin.open",
    labels={"m": "My Plugin"},
)
register_action(
    ["m", "c"],
    "Configure",
    event_type="my_plugin.configure",
)
```

The `labels` dict provides display text for intermediate nodes that
were auto-created during the path traversal.  Without it, they show
blank in the overlay.

---

## Terminal Passthrough

When the embedded terminal has focus, it captures all key events.
Key bindings registered with `register_terminal_passthrough()` bypass
the terminal and reach the app's key handling.  If your plugin adds
key bindings (via Textual's `BINDINGS`), register the same keys:

```python
from core.terminal_passthrough import register_terminal_passthrough

# These keys will pass through the terminal widget to the app
register_terminal_passthrough({"ctrl+shift+a", "ctrl+shift+m"})
```

---

## Integration with the Leader Overlay

The `LeaderOverlay` widget (`ui/widgets/leader_overlay.py`) reads the
registry tree and displays available chords as the user presses keys.
It calls `leader.find_node(pressed_keys)` after each keypress:

- If the node has children → display them as options
- If the node is a leaf → dispatch the action (post event or call handler)
- If no node matches → dismiss the overlay

---

## Testing

```python
from core.leader import register_action, register_submenu, find_node, reset_leader

def test_leader_registry():
    reset_leader()

    register_submenu(["t"], "Test")
    register_action(["t", "a"], "Action A", event_type="test.a")

    node = find_node(["t"])
    assert node is not None
    assert node.is_submenu
    assert node.label == "Test"

    leaf = find_node(["t", "a"])
    assert leaf is not None
    assert leaf.event_type == "test.a"
    assert leaf.handler is None
```

---

## Design Decisions

1. **Module-level singleton** — Same decorator self-registration pattern
   as tools, events, and commands.  Plugins register chords at import time.

2. **Event-driven by default** — Leaf actions post `CodyEvent` rather than
   calling handlers directly.  This decouples the chord definition from
   the handler, letting handlers live in plugin modules.

3. **Conflict detection at registration time** — Overlapping chords fail
   fast and loud during startup, not silently at runtime.

4. **Pure data model** — `LeaderNode` and `LeaderRegistry` have zero
   Textual dependency.  The overlay widget is a separate UI concern.

5. **Intermediate nodes auto-created** — You don't need to register every
   intermediate submenu; `register_action(["w", "s", "h"], ...)` creates
   the intermediate nodes for `w` and `s` automatically.  Use
   `register_submenu()` to give them display labels.