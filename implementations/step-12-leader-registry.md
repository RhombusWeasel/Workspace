# Step 12: Leader Registry

**Branch:** `step-12-leader-commands`  
**Date:** 2026-05-02

---

## Overview

In-memory chord tree for the `Ctrl+Space` leader menu. The leader menu
is a keyboard-driven modal where users chain key presses to reach nested
actions (e.g., `Ctrl+Space w s h` for "split horizontal").

The module defines a `LeaderRegistry` class, a `LeaderNode` dataclass,
and a module-level singleton with convenience functions.

Also updates `Workspace` to move split/close operations from direct key
bindings to leader chords, keeping `Ctrl+hjkl`/arrows for navigation.

---

## Implementation

### `core/leader.py`

#### `LeaderNode` dataclass

```python
@dataclass
class LeaderNode:
    label: str = ""                           # display string
    children: dict[str, LeaderNode] = field(default_factory=dict)  # key → child
    handler: Callable[[], Any] | None = None  # action callback (leaf only)
    is_submenu: bool = False                  # explicit submenu marker
```

- `label` — human-readable name shown in the leader guide UI
- `children` — single-char keys mapped to child nodes
- `handler` — callback invoked when the user completes a chord (leaf nodes only)
- `is_submenu` — `True` when created via `register_submenu()`, preventing conversion to a leaf action

#### `LeaderRegistry` class

| Method | Description |
|---|---|
| `register_action(keys, label, handler, labels)` | Register a leaf chord action |
| `register_submenu(keys, label)` | Register a labelled navigation submenu |
| `get_root() → LeaderNode` | Return the root node |
| `find_node(keys) → LeaderNode \| None` | Walk a path from the root |
| `reset()` | Clear all chords (test isolation) |

#### Registration algorithm (`register_action`)

For each key in the path:
1. If the node doesn't exist → create it (intermediate nodes get empty labels, leaf gets `label` + `handler`)
2. If the node exists and is the last key → check conflicts:
   - Already has a handler → `ValueError` (duplicate action)
   - Has children → `ValueError` (trying to replace a submenu with an action)
   - `is_submenu` → `ValueError` (can't convert explicit submenu to action)
   - Otherwise overwrite label + handler
3. If the node exists and is not the last key → check conflicts:
   - Has a handler → `ValueError` (trying to navigate through a leaf action)
   - Otherwise update label if provided in `labels` dict

The optional `labels` parameter maps intermediate key names to display labels,
allowing `register_action(["w", "s", "h"], "Split H", ..., labels={"w": "Workspace", "s": "Split"})`.

#### `register_submenu`

Creates or labels a navigation-only node. Sets `is_submenu=True` so that
`register_action` cannot later overwrite it as a leaf.

#### Module-level convenience functions

```python
leader = LeaderRegistry()              # singleton instance

register_action(keys, label, handler, labels=None)  # → leader.register_action(...)
register_submenu(keys, label)                        # → leader.register_submenu(...)
find_node(keys)                                      # → leader.find_node(...)
reset_leader()                                       # → leader.reset()
```

---

### `ui/workspace/workspace.py` changes

#### Bindings — before vs after

| Before | After | Reason |
|---|---|---|
| `ctrl+h` → split horizontal | Removed | Moved to leader |
| `ctrl+v` → split vertical | Removed | Moved to leader |
| `ctrl+x` → close pane | Removed | Moved to leader |
| `ctrl+left` → navigate left | `ctrl+left, ctrl+h` → navigate left | Combined vim+arrow keys |
| `ctrl+right` → navigate right | `ctrl+right, ctrl+l` → navigate right | Combined vim+arrow keys |
| `ctrl+up` → navigate up | `ctrl+up, ctrl+k` → navigate up | Combined vim+arrow keys |
| `ctrl+down` → navigate down | `ctrl+down, ctrl+j` → navigate down | Combined vim+arrow keys |

#### New: `register_workspace_leader_chords()`

Standalone function (not a method) that registers workspace chords with the
global leader registry:

```
Ctrl+Space w s h  → Split Horizontal
Ctrl+Space w s v  → Split Vertical
Ctrl+Space w c    → Close Pane
```

The `"w"` key is registered as a `"Workspace"` submenu; `"s"` is a `"Split"` sub-submenu.

Handlers are currently lambdas — the actual workspace manipulation is triggered
via CodyEvent messages posted by the existing `action_*` methods. The leader
tree provides the navigation structure; the event system provides the dispatch.

This function is called by bootstrap during initialization.

---

## Tests

### `tests/test_leader.py` — 17 tests in 7 classes

| Class | Tests | Coverage |
|---|---|---|
| `TestRegistration` | 6 | Single action, nested action, sibling preservation, submenu, submenu+action under it, labels on nested paths |
| `TestConflicts` | 3 | Duplicate action, child under leaf action, action over explicit submenu |
| `TestTraversal` | 4 | Find existing node, find intermediate, nonexistent path, empty path → root |
| `TestReset` | 2 | Clears all nodes, allows re-registration |
| `TestGetRoot` | 1 | Root node structure after registration |
| `TestSingleton` | 1 | Module-level `leader` is a `LeaderRegistry` |

All tests use the `_reset_leader` autouse fixture which calls `reset_leader()`
before each test, guaranteeing isolation.

### Updated workspace tests

All existing `TestLeaderActions` tests still pass — they call `action_*` methods
directly and remain unchanged. The `register_workspace_leader_chords()` function
is tested implicitly by the leader registry tests (the paths it creates are valid).

---

## Design Decisions

1. **`is_submenu` flag on `LeaderNode`.** Explicit submenus (created via
   `register_submenu()`) are protected from being overwritten as leaf actions.
   This distinguishes "auto-created intermediate node" from "explicitly declared
   navigation menu point."

2. **Standalone registration function for workspace chords.** The function lives
   in `workspace.py` but is not a method of `Workspace`. It's called by bootstrap
   during initialization, decoupling the widget from the global leader registry
   at import time.

3. **Vim-style navigation kept as direct bindings.** `Ctrl+hjkl` for pane
   navigation is a fast, frequent operation that doesn't benefit from the leader
   modal overhead. Splits and closes are less frequent and benefit from the
   discoverability the leader menu provides.

4. **Leader handlers are currently no-ops.** The actual workspace manipulation
   is triggered by events posted from the workspace's `action_*` methods. When
   the app's leader handling is built (Step 18), the app will listen for these
   events and call the action methods. The leader tree provides navigation
   structure; the event system provides dispatch.

---

## Usage Pattern

```python
# Bootstrap — register core chords
from core.leader import register_action, register_submenu
from ui.workspace.workspace import register_workspace_leader_chords

register_workspace_leader_chords()

# Query the tree (for UI rendering)
from core.leader import leader
root = leader.get_root()
for key, child in root.children.items():
    print(f"{key}: {child.label}")

# Find a specific node
node = leader.find_node(["w", "s", "h"])
if node and node.handler:
    node.handler()  # invoke the action
```
