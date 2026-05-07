# File Browser + Workspace Tabs — Implementation Notes

## Step 20: File Browser, Workspace Tabs, and Merged TreeRow

### Files Created

| File | Purpose |
|------|---------|
| `utils/icons.py` | Nerd Font icon registry. File type icons (ext→icon), folder icons, action icons. Single source of truth for all icon strings. |
| `utils/__init__.py` | Package init |
| `ui/workspace/tabs.py` | `WorkspaceTabs` — custom tabbed container with closeable tabs in a title bar. Manages tabs via `open_tab()`, `close_tab()`, `switch_tab()`. Posts `TabSwitched` and `TabClosed` messages. |
| `ui/workspace/tabs.tcss` | CSS for WorkspaceTabs: tab bar height, tab items, content area |
| `ui/workspace/file_view.py` | `FileView` — read-only file viewer. Reads file on mount, renders content as Static text. Has `refresh_file()` for re-reading. Uses `_path_to_id()` for valid Textual DOM ids. |
| `ui/workspace/file_view.tcss` | CSS for FileView |
| `ui/workspace/file_open_handler.py` | Event handler for `files.open` CodyEvent. Creates/switches-to a WorkspaceTabs in the focused workspace pane and opens the file as a FileView tab. |
| `ui/sidebar/panels/file_browser.py` | `FileBrowserPanel` — sidebar panel registered as `files` tab. Lazy directory scanning, inline action buttons, file/dir CRUD operations. Posts `files.open` event on file open. |
| `ui/sidebar/panels/file_browser.tcss` | CSS for FileBrowserPanel |
| `tests/test_icons.py` | Icon registry tests |
| `tests/test_tree_merged.py` | Tests for merged TreeRow (buttons on any row) and lazy loading (NodeNeedsChildren) |
| `tests/test_workspace_tabs.py` | WorkspaceTabs tests: open, close, switch, edge cases |
| `tests/test_file_browser.py` | File browser panel tests: scan, lazy load, icons, ignore list |
| `tests/test_file_view.py` | FileView tests: display, missing file, refresh, unicode |

### Files Modified

| File | Change |
|------|--------|
| `ui/tree/tree_row.py` | **Major**: Merged ActionRow functionality into TreeRow. Added `ButtonPressed` message, `_RowLabel` inner widget for isolated click handling, inline buttons in compose, `loaded` field on TreeNode. `ActionRow` kept as compatibility alias. |
| `ui/tree/tree.py` | **Major**: Tree always creates TreeRow (no more ActionRow path). Added `NodeNeedsChildren` message. `expand_node()` checks `loaded` flag and posts `NodeNeedsChildren` for lazy nodes. `rebuild()` uses TreeRow for all rows. `_refresh_visibility()` updates branch toggles. |
| `ui/tree/tree_row.tcss` | Merged ActionRow CSS into TreeRow. Added styles for `.tree-row-inner`, `.tree-row-buttons`, `_RowLabel`. |
| `ui/tree/tree.tcss` | Removed `ActionRow.-hidden` selector (now just `TreeRow.-hidden`). Added `_RowLabel` styles. |
| `ui/sidebar/panels/vault_panel.py` | Changed import from `ActionRow` to `TreeRow`. Handler renamed from `on_action_row_button_pressed` to `on_tree_row_button_pressed`. |
| `ui/sidebar/panels/config_panel.py` | Same changes as vault_panel — ActionRow→TreeRow, handler rename. |
| `main.py` | Added import of `ui.workspace.file_open_handler` for `files.open` event registration. |
| `ui/workspace/__init__.py` | Added WorkspaceTabs and FileView exports. |
| `tests/test_tree.py` | Updated for merged TreeRow (removed ActionRow-specific CSS, updated `_label` access to use `label_text` property, updated `_visible_action_rows` helper). |
| `tests/test_sidebar.py` | Updated ActionRow references to TreeRow with button filter. |
| `tests/test_config_panel.py` | Updated ActionRow queries to TreeRow + `node.buttons` filter. |

### Architecture Decisions

1. **Merged TreeRow/ActionRow**: Any row can now have buttons. The `_RowLabel` inner widget handles click events for selection and toggle, while buttons handle their own clicks independently. This prevents accidental toggle when clicking action buttons on branch nodes.

2. **Lazy Loading**: `TreeNode.loaded` field (default `True`). When `loaded=False`, the tree treats the node as a branch (shows ▶) but posts `NodeNeedsChildren` on expand instead of expanding immediately. The panel handler loads children, sets `loaded=True`, then calls `tree.rebuild()` and `tree.expand_node()`.

3. **Click Isolation**: TreeRow uses a `_RowLabel` widget to handle select/toggle clicks separately from button clicks. This prevents the "click on button also toggles the directory" bug.

4. **WorkspaceTabs**: Custom tabbed container (not Textual's TabbedContent) to allow close buttons in tab headers and future extensibility. Tabs are managed dynamically with `open_tab`, `close_tab`, `switch_tab`.

5. **FileView**: Simple read-only viewer that loads file content on mount. Uses `_path_to_id()` from FileBrowserPanel to generate valid Textual DOM ids from file paths.

6. **Icon Registry**: Single `utils/icons.py` file with all Nerd Font icons. `get_file_icon(filename)` and `get_folder_icon(dirname)` for context-aware icons. Extension mapping handles `.py`, `.js`, `.md`, etc. Special filename mapping for `Dockerfile`, `Makefile`, etc.

### Event Flow for File Open

1. User clicks "Open" button on a file in FileBrowserPanel
2. FileBrowserPanel posts `CodyEvent("files.open", {"path": "/abs/path/to/file.py"})`
3. `main.py` dispatches the event via `on_cody_event` → `dispatch()`
4. `file_open_handler._on_files_open()` receives the event
5. Handler finds the focused PaneContainer, creates/finds WorkspaceTabs, calls `open_tab()`
6. WorkspaceTabs mounts FileView widget for the file

### Key Constraints

- Lazy loading only scans one directory level at a time. Deep directories require successive expansions.
- FileView is read-only. Editing is a future enhancement.
- WorkspaceTabs are created per-pane. Each split pane has its own tab set.
- `_path_to_id()` uses basename + SHA256 hash fragment to avoid ID collisions while keeping IDs readable and valid for Textual DOM.