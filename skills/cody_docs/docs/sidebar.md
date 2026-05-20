# Sidebar Registry

**File:** `ui/sidebar/registry.py`
**Depends on:** None (pure data)

---

## Purpose

The sidebar registry lets plugins and core modules register panels in
the left or right sidebar.  Panels are registered at import time via the
`@register_sidebar_tab()` decorator — the same self-registration pattern
used throughout Cody.

---

## Architecture

```
@register_sidebar_tab(name="vault", icon="", side="left", tooltip="Vault")
class VaultPanel(Widget):
    ...
        │
        ▼
_sidebar_tabs["vault"] = SidebarTab(name, icon, side, tooltip, widget_class)
        │
        ▼
Sidebar.compose() → get_sidebar_tabs(side="left") → mount each tab
```

---

## API

### `@register_sidebar_tab(name, icon, side="left", tooltip="")`

```python
from ui.sidebar.registry import register_sidebar_tab

@register_sidebar_tab(
    name="my_panel",
    icon="◉",
    side="left",
    tooltip="My Plugin Panel",
)
class MyPanel(Container):
    def compose(self):
        yield Static("My panel content")
```

| Parameter | Type | Default | Description |
|---|---|---|---|
| `name` | `str` | — | Unique tab name.  Must not already be registered. |
| `icon` | `str` | — | Nerd Font icon character for the tab button. |
| `side` | `str` | `"left"` | `"left"` or `"right"`. |
| `tooltip` | `str` | `""` | Tooltip text for the tab button. |

The decorated class must be a Textual `Widget` subclass.

### `get_sidebar_tabs(side=None) → list[SidebarTab]`

Return registered tabs, optionally filtered by side.  Tabs are returned
in registration order.

```python
left_tabs = get_sidebar_tabs(side="left")
right_tabs = get_sidebar_tabs(side="right")
all_tabs = get_sidebar_tabs()
```

### `reset_sidebar_tabs()`

Clear all registered tabs.  Use between tests.

---

## SidebarTab Data

```python
@dataclass
class SidebarTab:
    name: str           # Unique tab name
    icon: str           # Nerd Font icon
    side: str           # "left" or "right"
    tooltip: str        # Hover text
    widget_class: type  # The Widget subclass
```

---

## How Sidebar Tabs Are Discovered

The bootstrap loads sidebar panels from:

1. **Core panels** — every `.py` file in `ui/sidebar/panels/`
2. **Plugin panels** — any plugin that imports a module containing
   `@register_sidebar_tab` from its `__init__.py`

Core panel modules are imported during Phase 4a of bootstrap.  Plugin
panels are registered during Phase 7 when the plugin's `__init__.py`
is executed.

---

## Complete Example: Plugin Sidebar Panel

```python
# plugins/my_plugin/__init__.py
"""My Plugin — adds a sidebar panel."""
from textual.containers import Container
from textual.widgets import Static, Input, Button
from ui.sidebar.registry import register_sidebar_tab
from core.events import register_handler
from core.config import register_defaults
from context import AppContext

# Register config defaults
register_defaults({
    "my_plugin": {
        "greeting": "Hello",
    }
})

# Register the sidebar tab
@register_sidebar_tab(name="my_panel", icon="★", side="left", tooltip="My Plugin")
class MyPanel(Container):
    def compose(self):
        yield Static("My Plugin", id="title")
        yield Input(placeholder="Enter name...", id="name-input")
        yield Button("Greet", variant="primary", id="greet-btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        name = self.query_one("#name-input", Input).value or "stranger"
        self.app.notify(f"Hello, {name}!", title="My Plugin")
```

---

## Nerd Font Icons

Sidebar tab icons use Nerd Font characters.  Some commonly used icons:

| Icon | Unicode | Name |
|---|---|---|
|  | `\ueb97` | nf-md-key (vault) |
|  | `\uf013` | nf-fa-gear (config) |
|  | `\uf1c0` | nf-fa-database (db) |
|  | `\uf07b` | nf-fa-folder (files) |
| ★ | `★` | Star |
| ◉ | `◉` | Fisheye |

Use a Nerd Font patch set for your terminal to see these icons.

---

## Testing

```python
from ui.sidebar.registry import register_sidebar_tab, get_sidebar_tabs, reset_sidebar_tabs
from textual.widget import Widget

def test_sidebar_registration():
    reset_sidebar_tabs()

    @register_sidebar_tab(name="test", icon="★", side="left", tooltip="Test")
    class TestPanel(Widget):
        pass

    tabs = get_sidebar_tabs(side="left")
    assert len(tabs) == 1
    assert tabs[0].name == "test"
    assert tabs[0].widget_class is TestPanel
```

---

## Design Decisions

1. **Decorator self-registration** — Same pattern as `@register_handler()`,
  `@register_tool()`, and `@register_command()`.  Plugin authors just
  write decorators; no manual wiring needed.

2. **Side as a parameter** — Tabs specify which sidebar they go in.
  This avoids needing a separate "left sidebar" and "right sidebar"
  registry.

3. **Registration order preserved** — Tabs appear in the sidebar in
  the order they were registered.  Core panels register first, then
  plugin panels.