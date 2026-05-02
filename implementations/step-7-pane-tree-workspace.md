# Step 7 — Recursive Pane Tree + Splitting Workspace

**Branch:** `step-7-pane-tree-workspace` (merged to main)  
**Date:** 2026-05-01

---

## Overview

A recursively splitting workspace underpinning all other UI elements. Built in two layers: a pure data model (`core/pane_tree.py`) with zero Textual dependency, and a Textual widget (`ui/workspace/workspace.py`) that composes the tree into `Horizontal`/`Vertical` containers.

---

## Architecture

```
core/pane_tree.py          ← Pure data model (no Textual)
├── LeafPane               ← id + content
├── SplitPane              ← direction, ratio, children[2]
├── LeafRect               ← normalized bounding box (x, y, w, h)
├── create_leaf()          ← factory
├── split()                ← replace leaf with SplitPane
├── close()                ← remove pane, sibling inherits space
├── find_neighbor()        ← coordinate-based spatial neighbor
├── set_content()          ← swap widget in leaf
├── get_leaves()           ← all leaves in DFS order
├── get_layout()           ← all LeafRects (for spatial queries)
└── find_pane()            ← lookup by id

ui/workspace/
├── __init__.py            ← exports Workspace, PaneContainer
├── workspace.py           ← Workspace + PaneContainer widgets
└── workspace.css          ← borders, focus, empty pane styles
```

---

## Pane Tree Data Model

### Types

```python
@dataclass
class LeafPane:
    id: str
    content: Any = None

@dataclass
class SplitPane:
    id: str
    direction: Literal["h", "v"]    # h = children side-by-side, v = stacked
    ratio: float                     # 0.0-1.0, portion for first child
    children: tuple[Pane, Pane]

Pane = LeafPane | SplitPane

@dataclass
class LeafRect:
    leaf_id: str
    x: float    # normalized 0.0-1.0
    y: float
    w: float
    h: float
```

### Key Design Decisions

1. **SplitPane gets auto-generated uuid** — not the target's id. Prevents duplicate IDs when splitting recursively. The original leaf keeps its id as the first child.

2. **All operations return new trees** — no mutation of inputs. This makes testing and reasoning about state trivial.

3. **Coordinate-based neighbor finding** — `find_neighbor()` computes `LeafRect` bounding boxes via `get_layout()` and scores candidates by gap + overlap. Handles all tree configurations (including non-uniform layouts where panes span multiple columns/rows), unlike tree-traversal approaches that work only for perfect grids.

4. **Close on last pane** — returns a fresh empty `LeafPane` with a new uuid. The workspace renders this as a bordered empty area.

### Ratio Semantics

`split(root, target_id, direction, ratio, new_id)`:
- `ratio` is the fraction given to the **first** child (the original leaf)
- Valid range: `[0.0, 1.0]`
- `ratio = 0.5` → equal split
- `ratio = 0.3` → original gets 30%, new gets 70%

---

## Workspace Widget

### PaneContainer

A bordered wrapper around a leaf's content widget:

- Has `focused` reactive — CSS class `focused` toggles border color
- `on_click` posts `PaneFocus(pane_id)` message
- Content widgets are mounted inside via Textual's compose context-manager pattern

### Workspace

| Method | Signature | Description |
|---|---|---|
| `split_pane` | `async (direction, ratio=0.5)` | Split focused pane |
| `close_pane` | `async ()` | Close focused pane |
| `navigate` | `(direction)` | Move focus (posts `workspace.navigated` event) |
| `set_pane_content` | `async (pane_id, widget)` | Mount widget into leaf |
| `get_leaf_ids` | `() -> list[str]` | All leaf IDs in DFS order |

### Composition Strategy

Uses Textual's `compose()` with context managers:

```python
def _compose_tree(self, pane):
    if isinstance(pane, LeafPane):
        container = PaneContainer(pane.id)
        if pane.content is not None:
            with container:
                yield pane.content   # auto-yields container
        else:
            yield container
    else:
        layout = (Horizontal if pane.direction == "h" else Vertical)(id=f"split-{pane.id}")
        with layout:
            for child in pane.children:
                yield from self._compose_tree(child)
        # layout auto-yielded by `with`
```

Key gotcha: `with container: yield child` auto-yields the container. Do NOT add `yield container` after — that creates duplicate IDs and `MountError`.

Tree changes call `await self.recompose()` which re-runs `compose()`.

### Bindings

```python
from textual.binding import Binding

BINDINGS = [
    Binding("ctrl+left",  "navigate_left",  "← Pane",   show=True),
    Binding("ctrl+right", "navigate_right", "→ Pane",   show=True),
    Binding("ctrl+up",    "navigate_up",    "↑ Pane",   show=True),
    Binding("ctrl+down",  "navigate_down",  "↓ Pane",   show=True),
    Binding("ctrl+h",     "split_horizontal", "Split H", show=True),
    Binding("ctrl+v",     "split_vertical",   "Split V", show=True),
    Binding("ctrl+x",     "close_pane",       "Close Pane", show=True),
]
```

Must use `Binding(...)` objects with `show=True` (NOT plain tuples) for widget-level bindings to appear in the Footer.

### Vim Convention for Splits

The user-facing action names follow vim/tmux convention:

- `split_horizontal` → **horizontal divider** → top/bottom panes → `split_pane("v")`
- `split_vertical` → **vertical divider** → left/right panes → `split_pane("h")`

This is the inverse of the internal pane_tree direction names, which describe child arrangement (not divider orientation).

### Event Integration

All leader actions post `CodyEvent` messages:

| Action | Event |
|---|---|
| `action_split_horizontal` | `workspace.split {direction: "h"}` |
| `action_split_vertical` | `workspace.split {direction: "v"}` |
| `action_close_pane` | `workspace.closed {pane_id}` |
| `navigate` | `workspace.navigated {pane_id}` |

Handlers registered via `@register_handler("workspace.split")` etc. can react without the workspace knowing about them.

---

## Tests

### `tests/test_pane_tree.py` — 59 tests

| Class | Tests | Covers |
|---|---|---|
| `TestCreateLeaf` | 3 | factory, default content, explicit content |
| `TestSplit` | 12 | h/v directions, recursive, content preservation, ratio edge cases (0, 1), error cases (invalid dir, ratio out of range, target not found, duplicate id) |
| `TestClose` | 6 | promote sibling, last pane→empty, deeply nested, 3-way collapse, not found |
| `TestFindNeighbor` | 17 | simple h/v splits, edge cases (no neighbor), cross-split navigation, 2×2 grid, non-uniform layouts, invalid direction, target not found |
| `TestSetContent` | 5 | update leaf, nested update, don't mutate others, not found, same object for root |
| `TestGetLeaves` | 4 | single, multiple, deep, visual order |
| `TestGetLayout` | 6 | full workspace, h-split coords, v-split coords, 2×2 grid coords, DFS order, LeafRect type |
| `TestFindPane` | 4 | root, nested, missing, wrong id |
| `TestImmutability` | 2 | split, close don't mutate input |

### `tests/test_workspace.py` — 27 tests

Uses `WorkspaceTestApp` (minimal Textual App) with `run_test()` async context manager and `pilot.pause()` for DOM sync.

| Class | Tests | Covers |
|---|---|---|
| `TestWorkspaceInitialState` | 3 | 1 pane, focused_id, focus style |
| `TestSplit` | 6 | h/v split, preserves content, new empty pane, focus stays, recursive |
| `TestClose` | 4 | reduces count, last→empty, focus moves, nested collapse |
| `TestNavigate` | 6 | h/v nav, no-op at edge, focus styles update, event posted |
| `TestClickFocus` | 1 | PaneFocus message changes focused_id |
| `TestSetContent` | 3 | mounts widget, replaces previous, invalid id silent |
| `TestLeaderActions` | 4 | split h/v, close, navigate via action methods |
| `TestGetLeafIds` | 1 | returns all leaf IDs |

---

## Files

| File | Status |
|---|---|
| `core/pane_tree.py` | New |
| `ui/workspace/__init__.py` | New |
| `ui/workspace/workspace.py` | New |
| `ui/workspace/workspace.css` | New |
| `tests/test_pane_tree.py` | New |
| `tests/test_workspace.py` | New |
| `main.py` | Modified (test app + delegation) |
| `pyproject.toml` | Modified (`asyncio_mode = "auto"`) |
| `design_document.md` | Modified (Step 7 inserted, renumbered) |
| `.gitignore` | Modified (added `.agents/`) |
