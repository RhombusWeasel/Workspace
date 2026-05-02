# Sidebar System — Tabbed Panels with Registration

**Branch:** `step-sidebar`  
**Date:** 2026-05-02

---

## Overview

Sidebar system with decorator-based panel registration, Nerd Font icons,
animated show/hide via leader chords, and a vault panel as the first
built-in tab.

---

## Implementation

### `ui/sidebar/registry.py` — `@register_sidebar_tab()`

```python
@register_sidebar_tab(name="vault", icon="\ueb97", side="right")
class VaultPanel(Container):
    ...
```

| Parameter | Purpose |
|---|---|
| `name` | Unique identifier |
| `icon` | Nerd Font character for the tab button |
| `side` | `"left"` or `"right"` (default `"left"`) |

**Public API:**
- `get_sidebar_tabs(side=None)` → `list[SidebarTab]` — filtered by side
- `reset_sidebar_tabs()` → clear for tests

Duplicates raise `ValueError`. Module-level `_sidebar_tabs` dict — same
singleton pattern as tools and commands.

### `ui/sidebar/sidebar.py` — `Sidebar` + `SidebarContainer`

#### `Sidebar(Container)`

Renders registered tabs for one side as a `TabbedContent` widget with
`TabPane` for each. Tab buttons use the icon character (Nerd Font).

Width: 25%. Tabs at top. Active tab's widget is mounted lazily.

#### `SidebarContainer(Container)`

Wraps a `Sidebar` with animated show/hide:

- Starts hidden (`width: 0`, `overflow: hidden`)
- `toggle()` → adds/removes `hidden` class
- CSS transition: `width 200ms ease-in-out`
- `is_hidden`, `show()`, `hide()` convenience methods

### `ui/sidebar/panels/vault_panel.py` — `VaultPanel`

Right-side panel showing vault contents in a `Tree` widget.

```
├─ \uf023  Credentials
│   ├─ \uf007  ollama  (user1)
│   └─ \uf007  openai  (user2)
└─ \uf278  Notes
    └─ \uf278  reminder
```

- Credentials and notes are grouped under expandable parent nodes
- Uses `Tree.set_root()` for data refresh
- Calls `set_vault(vault)` to bind a vault instance
- Auto-expands all nodes on mount

### Leader chords

```
Ctrl+Space w t l  →  Toggle Left Sidebar
Ctrl+Space w t r  →  Toggle Right Sidebar
```

Added under the existing `"w"` Workspace → `"t"` Toggle submenu.

### Workspace layout (main.py)

```
Horizontal
├─ SidebarContainer("left")   ← width: 0 when hidden
├─ Workspace                  ← fills remaining space (1fr)
└─ SidebarContainer("right")  ← width: 0 when hidden
```

Leader toggle events are handled by `CodyApp.on_cody_event()` which
delegates to the appropriate `SidebarContainer.toggle()`.

---

## Tests

### `tests/test_sidebar.py` — 9 tests in 3 classes

| Class | Tests | Coverage |
|---|---|---|
| `TestSidebarRegistry` | 5 | Register, multi-tab, sides, duplicate rejection, reset |
| `TestSidebar` | 3 | Tab buttons rendered, active pane visible, visibility/hide |
| `TestVaultPanel` | 1 | Renders vault credentials and notes in tree |

Tests use `SidebarTestApp` and `VaultTestApp` with Textual `run_test()` pilot.
Registries are reset via autouse fixture.

---

## Design Decisions

1. **Icons for tab labels.** Nerd Font characters (`\ueb97` for vault,
   `\uf07c` for folders, `\uf007` for users) provide compact visual
   identity without text labels. The parameter is called `icon` to
   avoid future confusion with text labels.

2. **25% width, CSS-only.** Width controlled by CSS classes; transitions
   handle the animation. No JavaScript-style animation loops.

3. **Vault panel is self-updating.** Calls `set_vault()` explicitly;
   doesn't poll or watch for changes. UI-driven refresh matches the
   manual-scan pattern used for skills (§ 6.4).

4. **Sidebars start hidden.** Keeps the default view clean — workspace
   gets maximum space. Users open sidebars on demand via leader chords.

5. **Decorator pattern matching tools/commands.** `@register_sidebar_tab()`
   follows the same self-registration-at-import pattern. Skill authors
   can add sidebar panels by dropping a file with the decorator.

---

## Usage Pattern

```python
# Register a sidebar panel (in a skill or core module)
from ui.sidebar.registry import register_sidebar_tab

@register_sidebar_tab(name="files", icon="\uf07c", side="left")
class FileTreePanel(Container):
    def compose(self):
        yield Tree(build_file_tree())

# Toggle via leader: Ctrl+Space w t l / w t r
# Or programmatically:
app.left_container.toggle()
app.right_container.show()
```
