# Step 15a — Tree Content Widgets + ChatPanel Restructure

**Branch:** `step-15a-tree-content-chatpanel`
**Date:** 2026-05-03

## Overview

Two changes were made:

1. **Tree now supports arbitrary Widget content on leaf nodes** — `TreeNode` gets a `content: Widget | None` field.  When set, `TreeRow.compose()` mounts the widget below the indent/toggle prefix instead of rendering plain text.

2. **ChatPanel restructured: each response is a branch** — Assistant responses become branch nodes with children (thinking, tools, markdown widget) rather than flat siblings.  Response text uses a `Markdown` widget for streaming.

## Files Changed

### `ui/tree/tree_row.py`

- `TreeNode` gained `content: Widget | None = None` field.
- `TreeRow` switched from `render()`-based to `compose()`-based:
  - Always yields a `Static` for the indent/toggle prefix.
  - If `node.content` is not `None`, yields the content widget as a second child.
  - Removed `_was_expanded` state (no longer needed).

### `ui/tree/tree.py`

- `_rebuild_rows()` rewritten from destroy-and-recreate to **diff-based**:
  - Rows for nodes still visible are kept in place (preserving content widgets).
  - Rows for newly visible nodes are created and mounted.
  - Rows for now-hidden nodes are removed.
  - This avoids the widget re-mounting problem where content widgets were destroyed by `row.remove()` and couldn't be re-composed.

### `ui/sidebar/panels/chat_panel.py`

- **Structure changed**: Each assistant `"assistant"` message is a **branch** node whose children contain:
  - A `Markdown` widget leaf for streaming response text
  - Thinking leaves (added via `add_thought()`)
  - Tool result leaves (added via `add_tool_result()`)
- User messages remain plain leaf nodes.
- `add_message()` for assistants: creates a `Markdown` widget, wraps it in a child `TreeNode` with `content=md`, and makes the response node a branch with this child.
- `update_response_text()`: calls `md.update(text)` on the last markdown widget for in-place streaming without tree rebuild.
- New helper: `_last_markdown: Markdown | None` tracks the current streaming widget.

**New tree structure:**
```
root (Conversation)
├── 👤 User: "Hello"              ← leaf
├── 💭 Response                   ← branch
│   ├── 💡 Thinking: "..."        ← leaf
│   ├── 🔧 Tool: calculate → 4    ← leaf
│   └── 📝 [Markdown widget]      ← leaf with streaming content
├── 👤 User: "What is 2+2?"       ← leaf
├── 💭 Response                   ← branch
│   └── 📝 [Markdown widget]
```

## Key Design Decisions

1. **Diff-based `_rebuild_rows`** was chosen over destroy-and-recreate because:
   - Content widgets stored on data model nodes get destroyed when their row is removed.
   - The diff approach keeps existing rows (and their content widgets) alive.
   - Only new/hidden nodes trigger row creation/removal.

2. **`compose()` over `render()`** was chosen because:
   - Textual widgets can only be mounted via `compose()`, not `render()`.
   - The indent prefix is still a `Static` for simplicity.
   - Content widgets (Markdown, etc.) are composed as second children.

3. **Markdown for streaming** over plain text because:
   - `Markdown.update()` supports incremental updates without rebuilding the tree.
   - Rich formatting for code blocks, lists, etc. in responses.

## Testing

- **33 tests** covering TreeRow content widgets and ChatPanel branch structure.
- All pass.  Full suite: 478 pass, 1 pre-existing failure (config leakage in Ollama provider test).
- Tests use `_settle()` helper with multiple `await pilot.pause()` calls to handle Textual's async DOM cleanup.

## Usage for Future Agents

### Adding content widgets to tree nodes

```python
from textual.widgets import Markdown, Label
from ui.tree.tree_row import TreeNode

# Simple label content
node = TreeNode("id", "Label", content=Label("Hello"))

# Streaming markdown
md = Markdown("Initial text")
node = TreeNode("id", "Response", content=md)
# Later: md.update("Updated text")
```

### Building chat-like tree structures

```python
# User message (leaf)
user_node = TreeNode("u1", "\uf007  User: Hello", data={"role": "user"})
root.children.append(user_node)

# Assistant response (branch with markdown)
md = Markdown("Response text")
md_child = TreeNode("md-1", "", content=md, data={"kind": "response"})
resp_node = TreeNode("r1", "\uf4ad  Response", children=[md_child],
                      data={"role": "assistant"})
root.children.append(resp_node)

tree.set_root(root)
```

### Streaming into existing Markdown

```python
# Store reference to the Markdown widget
self._last_markdown = md  # or retrieve via node.content

# Stream updates without rebuilding
self._last_markdown.update(accumulated_text)
```

## Caveats

- `Tree._rebuild_rows()` diff approach assumes nodes are appended (not inserted at arbitrary positions).  New rows are always mounted at the end, which matches depth-first traversal order.
- `set_root()` with a completely new root will remove ALL old rows and create ALL new rows.  For incremental updates, modify the root in-place and call `set_root(same_root)`.
- `ActionRow` does NOT support content widgets — it's button-only.
