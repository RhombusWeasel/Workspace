# Step 15c — Tree CSS Hide/Show

## Overview

Replaced the expand/collapse mechanism in `ui/tree/tree.py` from DOM-based
row removal/re-creation to CSS class toggling.  All rows are mounted once
and stay in the DOM; visibility is controlled by a `-hidden` CSS class.

## Motivation

Previously, `_rebuild_rows()` removed hidden rows and mounted newly-visible
ones, which destroyed and recreated content widgets like `Markdown`.  This
required the `PersistentMarkdown` hack to preserve streaming content across
collapse/expand cycles.

## Changes

### `ui/tree/tree.py`

**Mount lifecycle:**
- `on_mount()` — mounts ALL rows (via `_mount_all_rows()`), then calls
  `_refresh_visibility()` to hide non-visible ones.
- `_mount_all_rows()` — walks the entire tree (ignoring expand state) via
  `_get_all_nodes_depth()`, mounts a `TreeRow` or `ActionRow` for every node,
  sorts into depth-first order.
- `_refresh_visibility()` — walks visible nodes via `_get_visible_nodes()`
  (respecting expand state), then toggles the `-hidden` CSS class on each row.

**Expand/collapse (no DOM remounts):**
- `expand_node()` / `collapse_node()` / `toggle_node()` / `expand_all()` —
  update `_expanded` set, then call `_refresh_visibility()`.  No row
  removal or mounting.

**Structural changes (hybrid rebuild):**
- `rebuild()` — for when the data model changes (children added/removed):
  1. Rebuilds `_node_map` from root
  2. Removes rows for nodes no longer in the map
  3. Mounts rows for new nodes
  4. Re-sorts all children into depth-first order
  5. Calls `_refresh_visibility()`
  - Existing rows (and their content widgets) are preserved.

- `set_root()` — full reset:
  1. Orphans content widgets (sets `node.content = None`) so they don't get
     destroyed during row removal
  2. Removes all rows
  3. Calls `_mount_all_rows()` + `_refresh_visibility()`

**Helpers:**
- `_get_all_nodes_depth()` — walks entire tree (ignoring expand state)
- `_get_visible_nodes()` — walks tree respecting `_expanded` (existing logic)
- `_orphan_content_widgets()` — detaches content widgets from node refs
- `_remove_all_rows()` — removes all rows via `list()` snapshot

### `ui/tree/tree.tcss`

Added:
```css
TreeRow.-hidden, ActionRow.-hidden {
    display: none;
}
```

Test apps must also include this rule (or inherit from the app's CSS).

### `ui/chat/chat_display.py`

- **`PersistentMarkdown` removed entirely** — no longer needed since content
  widgets survive collapse/expand.
- `begin_assistant_turn()` now auto-expands section branches (thinking, tools,
  response) after rebuilding, so their Markdown children are visible.
- `update_section()` has a guard: if `md.update(text)` leaves `_markdown`
  empty (race with mount lifecycle), it sets `_markdown` directly.  This
  handles the case where the widget isn't fully initialized when update
  is called.

### `ui/chat/chat_manager.py`

- `_handle_submit()` calls `self.refresh(layout=True)` + `await asyncio.sleep(0)`
  after `begin_assistant_turn()` to ensure the event loop processes mount
  messages before streaming starts.

### `tests/test_tree.py`

- Test app CSS now includes `TreeRow.-hidden, ActionRow.-hidden { display: none; }`
- `_visible_rows()` helper filters by `not has_class("-hidden")`
- `_visible_action_rows()` same for ActionRow
- All expand/collapse assertions use visible row count, not total row count
- New tests: `test_content_widget_survives_collapse_and_reexpand`,
  `test_nested_expand_and_collapse`, `test_rebuild_preserves_existing_rows`,
  `test_select_hidden_node_still_works`
- `test_rebuild_after_adding_child` verifies content widget survives rebuild
- `test_set_root_remounts_all_rows` verifies full reset behavior

## Race condition

There is a timing dependency: `Markdown.update()` must be called AFTER the
widget is fully mounted and has `self.app` set.  The tree mounts rows
synchronously, but Textual's mount lifecycle completes on the next event
loop iteration.  The guard in `update_section()` handles this by directly
setting `_markdown` when the update silently fails on a not-yet-ready widget.

## Migration notes

Any code that queries `tree.query(TreeRow)` to count visible items must
now filter by `not has_class("-hidden")` or use `_visible_rows()`.  The
total row count now equals the total number of nodes, not visible nodes.
