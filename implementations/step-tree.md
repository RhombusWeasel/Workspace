# Tree Widgets — GenericTree & TreeRow

**Branch:** `step-tree`  
**Date:** 2026-05-02

---

## Overview

Reusable tree widget for hierarchical data display. Two components:

- **`TreeNode`** — pure data model (id, label, children, data)
- **`TreeRow`** — renders a single visible row with indent, expand indicator
- **`Tree`** — container managing expand/collapse, selection, keyboard nav
- **`NodeSelected` / `NodeToggled`** — Textual messages for events

---

## Implementation

### `ui/tree/tree_row.py`

#### `TreeNode` dataclass

```python
@dataclass
class TreeNode:
    id: str
    label: str
    children: list[TreeNode] = field(default_factory=list)
    data: Any = None
```

Pure data — no rendering logic. `id` must be unique within the tree (used
for expand state tracking).

#### `TreeRow(Widget)`

| Attribute | Type | Purpose |
|---|---|---|
| `node` | `TreeNode` | The data node this row represents |
| `depth` | `int` | Indent level (0 = root) |
| `is_branch` | `bool` | Whether it has children and shows expand icon |
| `is_selected` | `reactive[bool]` | Visual selection highlight |

**Rendering:**
- Indent: `"  " * depth` spaces
- Toggle: `"▶ "` for collapsed branch, `"  "` for leaf
- Label: the node's label text
- Selected: `reverse` style on entire line

**Messages:**
- `TreeRow.Selected(node)` — posted on click (leaf nodes only)
- `TreeRow.Toggled(node)` — posted on click (branch nodes only)

**CSS** is embedded in `DEFAULT_CSS` for portability.

### `ui/tree/tree.py`

#### Messages

- `NodeSelected(node_id, node)` — when a node is selected
- `NodeToggled(node_id, node, expanded)` — when expanded/collapsed

#### `Tree(VerticalScroll, can_focus=True)`

| Method | Description |
|---|---|
| `select_node(id)` | Set selected node, post `NodeSelected` |
| `expand_node(id)` | Reveal children, post `NodeToggled` |
| `collapse_node(id)` | Hide children, post `NodeToggled` |
| `toggle_node(id)` | Flip expand state |
| `expand_all()` | Expand entire tree |
| `is_expanded(id)` | Check expand state |

**Internal mechanics:**
- `_expanded: set[str]` — tracks which node ids are expanded (root always expanded)
- `_node_map: dict[str, TreeNode]` — flat lookup by id
- `_get_visible_nodes()` — DFS walk respecting expand state, returns `[(node, depth)]`
- `_rebuild_rows()` — clears and recreates all `TreeRow` widgets from visible nodes
- `_update_selection()` — syncs `is_selected` on all rows

**Message routing:**
- `on_tree_row_selected(msg)` → `select_node(msg.node.id)`
- `on_tree_row_toggled(msg)` → `toggle_node(msg.node.id)`

---

## Tests

### `tests/test_tree.py` — 15 tests in 5 classes

| Class | Tests | Coverage |
|---|---|---|
| `TestTreeNode` | 2 | Attributes, children |
| `TestTreeRow` | 3 | Label render, expand indicator, depth indent |
| `TestTreeRendering` | 4 | Initial visible nodes, expand, collapse, expand_all |
| `TestTreeNavigation` | 4 | select_node, focus style, unknown id ignored, toggle |
| `TestTreeEvents` | 2 | Selection state update, toggle side effects |

All tests use `TreeTestApp` with Textual's `run_test()` pilot. The app
uses `self.tree_widget` internally because Textual's `App.tree` is a
built-in property for the DOM tree.

---

## Design Decisions

1. **`TreeNode` is a dataclass, not a widget.** Keeps the data model
   separate from rendering. Consumers build `TreeNode` trees from their
   data (DB rows, filesystem, vault entries) and pass the root to `Tree`.

2. **TreeRow extends `Widget`, not `Static`.** Gives full control over
   rendering with Rich `Text` objects. Selection uses `reverse` style
   for clean highlight without CSS dependencies.

3. **Tree extends `VerticalScroll`.** Built-in scrolling for large trees.
   `can_focus=True` for keyboard navigation (up/down arrows scroll
   naturally).

4. **Full rebuild on expand/collapse.** Rather than showing/hiding
   individual rows (complex with Textual's DOM), we clear and recreate
   all visible rows. Fast enough for typical tree sizes.

5. **DFS walk for visibility.** `_get_visible_nodes()` does a depth-first
   traversal, skipping children of collapsed nodes. This produces the
   correct visual order (parent → children) for rendering.

---

## Usage Pattern

```python
from ui.tree.tree_row import TreeNode
from ui.tree.tree import Tree, NodeSelected, NodeToggled

# Build data
root = TreeNode("root", "My Files", children=[
    TreeNode("src", "src/", children=[
        TreeNode("main", "main.py"),
        TreeNode("utils", "utils.py"),
    ]),
    TreeNode("readme", "README.md"),
])

# Mount
tree = Tree(root)
await app.mount(tree)

# Listen for events
def on_node_selected(self, msg: NodeSelected):
    print(f"Selected: {msg.node_id}")

def on_node_toggled(self, msg: NodeToggled):
    print(f"Toggled: {msg.node_id} → {'open' if msg.expanded else 'closed'}")

# Programmatic control
tree.expand_all()
tree.select_node("src")
```
