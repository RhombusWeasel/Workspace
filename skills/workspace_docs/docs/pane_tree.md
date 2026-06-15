# Pane Tree

**File:** `core/pane_tree.py`
**Depends on:** Nothing (pure data model)

---

## Purpose

The pane tree is a pure data model for Workspace's splitting layout. A `Pane` is either a `LeafPane` (holds a content widget) or a `SplitPane` (divides its space between two children). All operations return new trees — no mutation of inputs. Zero Textual dependency.

---

## Data Types

```python
Direction = Literal["h", "v"]     # "h" = side-by-side, "v" = stacked
NavDirection = Literal["left", "right", "up", "down"]

@dataclass
class LeafPane:
    id: str           # Unique identifier
    content: Any = None

@dataclass
class SplitPane:
    id: str
    direction: Direction
    ratio: float                      # 0.0–1.0, portion for first child
    children: tuple[Pane, Pane]

Pane = LeafPane | SplitPane
```

---

## API

### Factory

| Function | Signature | Description |
|---|---|---|
| `create_leaf` | `(id=None, content=None) → LeafPane` | Create a leaf pane (auto-generated ID if None) |

### Tree Operations

| Function | Signature | Description |
|---|---|---|
| `split` | `(root, target_id, direction, ratio, new_id, content=None) → Pane` | Split target leaf, creating a new sibling |
| `close` | `(root, target_id) → Pane` | Close a leaf, merging its parent into its sibling |
| `replace` | `(root, target_id, content) → Pane` | Replace a leaf's content |
| `navigate` | `(root, from_id, direction) → LeafPane \| None` | Find adjacent leaf in spatial direction |

### Query

| Function | Signature | Description |
|---|---|---|
| `find` | `(root, target_id) → Pane \| None` | Find a node by ID |
| `find_leaf` | `(root, target_id) → LeafPane \| None` | Find a leaf by ID |
| `get_leaves` | `(root) → list[LeafPane]` | All leaves in depth-first order |
| `path_to` | `(root, target_id) → list[Pane]` | Path from root to target |
| `has_id` | `(root, target_id) → bool` | Whether an ID exists in the tree |

### Serialisation

| Function | Signature | Description |
|---|---|---|
| `pane_tree_to_dict` | `(root) → dict` | Convert to JSON-safe dict |
| `pane_tree_from_dict` | `(data) → Pane` | Reconstruct from dict |

### Serialisation Format

```json
{
  "id": "abc123",
  "direction": "h",
  "ratio": 0.5,
  "children": [
    {"id": "main", "content": null},
    {"id": "split2", "direction": "v", "ratio": 0.6, "children": [...]}
  ]
}
```

Leaves are `{"id": "...", "content": null}`. Splits include `direction`, `ratio`, and `children`.

---

## Design Decisions

1. **Pure data, no Textual dependency** — The pane tree is used by both the workspace UI and session persistence. Keeping it pure Python makes testing and serialisation straightforward.

2. **Immutable operations** — `split`, `close`, and `replace` return new trees. The original is never mutated. This makes recomposition safe: save state → build new tree → apply.

3. **Spatial navigation** — `navigate()` understands horizontal/vertical splits and returns the correct adjacent leaf for vim-style hjkl navigation.

4. **JSON-serialisable** — `pane_tree_to_dict()` / `pane_tree_from_dict()` produce/consume plain dicts suitable for session persistence.