# Creating a Plugin — Complete Guide

This guide walks through everything you need to create a new Cody plugin,
from understanding the architecture to writing, testing, and installing
your plugin.

---

## Table of Contents

1. [What Plugins Can Do](#what-plugins-can-do)
2. [Plugin Anatomy](#plugin-anatomy)
3. [Choosing a Location](#choosing-a-location)
4. [Step 1: Create SKILL.md](#step-1-create-skillmd)
5. [Step 2: Create \_\_init\_\_.py](#step-2-create-__init__py)
6. [Step 3: Register Components](#step-3-register-components)
7. [Step 4: Add CSS](#step-4-add-css)
8. [Step 5: Test and Install](#step-5-test-and-install)
9. [Complete Examples](#complete-examples)
10. [Advanced Patterns](#advanced-patterns)
11. [Troubleshooting](#troubleshooting)

---

## What Plugins Can Do

Plugins can register any combination of:

| Component | How to Register | What It Does |
|---|---|---|
| Sidebar panel | `@register_sidebar_tab()` | Adds a panel to the left or right sidebar |
| Event handler | `@register_handler()` | Responds to `CodyEvent` messages |
| LLM tool | `@register_tool()` | Exposes a function the LLM can invoke |
| Slash command | `@register_command()` | Adds a `/command` the user can type |
| Leader chord | `register_action()` / `register_submenu()` | Adds keyboard shortcuts to `Ctrl+Space` menu |
| Config defaults | `register_defaults()` | Provides default values for config keys |
| Plugin services | `PLUGIN_SERVICES` dict | Provides services to other parts of the app |
| CSS | `.tcss` file in plugin dir | Styles the plugin's widgets |

---

## Plugin Anatomy

A minimal plugin directory:

```
my_plugin/
├── SKILL.md              # Required — manifest with name + description
└── __init__.py            # Required — entry point for registrations
```

A full-featured plugin:

```
my_plugin/
├── SKILL.md              # Manifest (name, description, optional requirements)
├── __init__.py            # Entry point — imports modules with @register_*
├── core/                  # Plugin internals
│   ├── __init__.py
│   └── connections.py
├── handlers.py            # Event handlers (@register_handler)
├── tools.py               # Agent-callable tools (@register_tool)
├── cmd/                   # Slash commands (auto-discovered)
│   └── mycommand.py
├── my_plugin.tcss         # Plugin CSS (auto-collected)
└── services.py            # PLUGIN_SERVICES factory
```

---

## Choosing a Location

| Tier | Path | Scope | Override behavior |
|---|---|---|---|
| **Bundled** | `{cody_dir}/plugins/my_plugin/` | Ships with Cody | Overridden by user or project |
| **User-global** | `~/.agents/plugins/my_plugin/` | Available in all projects | Overrides bundled, overridden by project |
| **Project-local** | `{project}/.agents/plugins/my_plugin/` | Current project only | Highest precedence |

For most plugins, use **user-global** (`~/.agents/plugins/`).  Use
**project-local** for project-specific tools.

---

## Step 1: Create SKILL.md

The manifest uses YAML frontmatter:

```markdown
---
name: my_plugin
description: Short description shown in the skill catalog
requirements:
  - requests>=2.28
  - psycopg2-binary>=2.9
---

# My Plugin

Longer markdown documentation about what the plugin does.
This body is available via the `activate_skill` tool if the LLM asks.
```

| Field | Required | Description |
|---|---|---|
| `name` | **Yes** | Unique plugin name (letters, numbers, hyphens, underscores) |
| `description` | **Yes** | Short description (shown in catalog and plugin list) |
| `requirements` | No | YAML list of pip-format package specifiers |

If `requirements` is declared, `uv pip install` (or `pip install`) is run
when installing via `/plugin install`.  For manually-created plugins,
install dependencies yourself:

```bash
uv pip install requests>=2.28
```

Or use **lazy imports** so the module can load even if the package isn't
installed yet:

```python
@register_handler("my_plugin.fetch")
def _on_fetch(data, ctx):
    import requests  # imported only when the handler is called
    ...
```

---

## Step 2: Create \_\_init\_\_.py

The `__init__.py` is the entry point.  It must import all modules that
contain `@register_*` decorators — otherwise the decorators never execute:

```python
# plugins/my_plugin/__init__.py
"""My Plugin — does something useful."""

# Side-effect imports trigger decorator registrations.
from plugins.my_plugin.handlers import register_handlers  # noqa: F401
from plugins.my_plugin.services import PLUGIN_SERVICES      # noqa: F401

# Direct registrations can also go here:
from core.leader import register_submenu, register_action

register_submenu(["m"], "My Plugin")
register_action(["m", "o"], "Open", event_type="my_plugin.open")

# Declare services for other components
PLUGIN_SERVICES = {
    "my_service": create_my_service,
}

__all__ = ["PLUGIN_SERVICES"]
```

**The golden rule:** If a module has a `@register_handler`, `@register_tool`,
`@register_sidebar_tab`, or `@register_command` decorator, it must be
imported (directly or transitively) by `__init__.py`.

---

## Step 3: Register Components

### Sidebar Panel

```python
from ui.sidebar.registry import register_sidebar_tab

@register_sidebar_tab(name="my_panel", icon="★", side="left", tooltip="My Plugin")
class MyPanel(Container):
    def compose(self):
        yield Static("My panel content")
```

See [Sidebar Registry](sidebar.md) for full details.

### Event Handler

```python
from core.events import register_handler
from context import AppContext

@register_handler("my_plugin.greet")
def _on_greet(data: dict, ctx: AppContext) -> None:
    app = ctx.app
    if app is None:
        return
    name = data.get("name", "stranger")
    app.notify(f"Hello, {name}!", title="My Plugin")
```

See [Events](events.md) for full details.

### LLM Tool

```python
from core.tools import register_tool

@register_tool(
    name="my_lookup",
    tags=["my_plugin"],
    description="Look up information in my service.",
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query.",
            },
        },
        "required": ["query"],
    },
)
async def my_lookup(query: str, ctx: AppContext | None = None) -> str:
    # Tools can be async or sync
    # If ctx is in the signature, it's auto-injected
    return f"Result for: {query}"
```

See [Tools](tools.md) for full details.

### Slash Command

Place in your plugin's `cmd/` directory for auto-discovery, or import
from `__init__.py`:

```python
# plugins/my_plugin/cmd/greet.py
from core.commands import register_command

@register_command(name="greet", description="Show a greeting")
async def greet(app, args: str) -> str:
    name = args.strip() or "stranger"
    app.notify(f"Hello, {name}!", title="Greeting")
    return f"Greeted {name}."
```

See [Commands](commands.md) for full details.

### Leader Chord

```python
from core.leader import register_submenu, register_action

register_submenu(["m"], "My Plugin")
register_action(
    ["m", "o"], "Open", event_type="my_plugin.open",
    labels={"m": "My Plugin"},
)
```

See [Leader Chords](leader.md) for full details.

### Config Defaults

```python
from core.config import register_defaults

register_defaults({
    "my_plugin": {
        "max_items": 100,
        "auto_refresh": True,
        "greeting": "Hello",
    }
})
```

These are applied at bootstrap time.  User config values always win over
defaults.  See [Config](config.md) for full details.

### Workspace Tab

```python
from ui.workspace.tabs import TabState, WorkspaceTabs
from core.events import register_handler
from context import AppContext

class MyTabState(TabState):
    def __init__(self, my_param: str):
        self.my_param = my_param

    def dispose(self) -> None:
        pass  # release external resources here

class MyWidget(Widget):
    def __init__(self, state: MyTabState):
        super().__init__()
        self.state = state

def _create_my_content(state: TabState) -> MyWidget:
    return MyWidget(state)

@register_handler("my_plugin.open_tab")
def _on_open_tab(data: dict, ctx: AppContext) -> None:
    app = ctx.app
    if app is None:
        return

    from ui.workspace.workspace import Workspace, PaneContainer
    from ui.workspace.tabs import WorkspaceTabs

    try:
        workspace = app.query_one(Workspace)
    except Exception:
        return

    try:
        container = app.query_one(
            f"#pane-{workspace.focused_id}", PaneContainer
        )
    except Exception:
        return

    try:
        tabs = container.query_one(WorkspaceTabs)
    except Exception:
        return

    state = MyTabState(my_param=data.get("param", "default"))
    tabs.open_tab(
        "my-tab", "My Plugin", state=state,
        content_factory=_create_my_content,
    )
```

See [Workspace Tabs](workspace_tabs.md) for persistence patterns and full details.

### Plugin Services

```python
# plugins/my_plugin/services.py
from core.config import Config
from core.vault import VaultManager

def create_my_service(config: Config, vault: VaultManager):
    return MyService(config, vault)

# plugins/my_plugin/__init__.py
from plugins.my_plugin.services import create_my_service

PLUGIN_SERVICES = {
    "my_service": create_my_service,
}
```

Bootstrap calls each factory with `(config, vault)` and injects the
result into `AppContext`.  Other components access it via `ctx.my_service`.

---

## Step 4: Add CSS

Create a `.tcss` file in the plugin directory.  It's auto-collected by
`collect_plugin_tcss()`:

```css
/* my_plugin.tcss */
MyPanel {
    height: 100%;
    background: $surface;
    padding: 1 2;
}

MyPanel Static {
    color: $text;
}
```

Textual CSS supports variables, nesting, and layout.  See the
[Textual CSS reference](https://textual.textualize.io/css/) for details.

---

## Step 5: Test and Install

### Manual testing

1. Place the plugin in `~/.agents/plugins/my_plugin/`
2. Restart Cody
3. Check stderr for any import errors
4. Test your registered components

### Installing from a git repo

```bash
/plugin install https://github.com/you/cody-my-plugin
```

This clones the repo, installs dependencies, writes `.plugin.json`, and
updates config.

### Updating

```bash
/plugin update my_plugin
/plugin update my_plugin --version v1.2.0
/plugin update --all
```

### Removing

```bash
/plugin remove my_plugin
/plugin remove my_plugin --local    # project-local only
```

### Listing

```bash
/plugin list
```

---

## Complete Examples

### Example 1: Minimal Plugin (sidebar panel + handler)

```
~/.agents/plugins/greeter/
├── SKILL.md
└── __init__.py
```

```markdown
<!-- SKILL.md -->
---
name: greeter
description: A greeting sidebar panel
---

# Greeter

Shows a greeting in the sidebar.
```

```python
# __init__.py
"""Greeter plugin."""
from textual.containers import Container
from textual.widgets import Static
from ui.sidebar.registry import register_sidebar_tab
from core.events import register_handler
from core.config import register_defaults
from context import AppContext

register_defaults({"greeter": {"name": "World"}})

@register_sidebar_tab(name="greeter", icon="★", side="left", tooltip="Greeter")
class GreeterPanel(Container):
    def on_mount(self) -> None:
        ctx = self.app.context
        name = ctx.config.get("greeter.name", "World")
        self.mount(Static(f"Hello, {name}!"))

@register_handler("greeter.update")
def _on_update(data: dict, ctx: AppContext) -> None:
    name = data.get("name", "World")
    ctx.config.set("greeter.name", name)
    ctx.config.save()
    if ctx.app:
        ctx.app.notify(f"Name updated to {name}", title="Greeter")
```

### Example 2: Tool Plugin with Confirmation

```
~/.agents/plugins/deployer/
├── SKILL.md
├── __init__.py
├── tools.py
└── deployer.tcss
```

```markdown
<!-- SKILL.md -->
---
name: deployer
description: Deploy the project with LLM orchestration
requirements:
  - fabric>=2.7
---

# Deployer

LLM-callable tools for deploying the project to staging/production.
```

```python
# __init__.py
"""Deployer plugin."""
from plugins.deployer.tools import register_deployer_tools  # noqa: F401
register_deployer_tools()
```

```python
# tools.py
from core.tools import register_tool
from core.leader import register_submenu, register_action
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from context import AppContext


def register_deployer_tools() -> None:
    # Leader chords are registered here to keep everything in one place
    register_submenu(["d"], "Deploy")
    register_action(["d", "s"], "Deploy Staging", event_type="deployer.to_staging")
    register_action(["d", "p"], "Deploy Production", event_type="deployer.to_production")


@register_tool(
    name="deploy",
    tags=["deployer"],
    description="Deploy the project to the specified environment.",
    parameters={
        "type": "object",
        "properties": {
            "environment": {
                "type": "string",
                "description": "Target: 'staging' or 'production'.",
            },
            "confirm": {
                "type": "boolean",
                "description": "Whether to ask for user confirmation first.",
            },
        },
        "required": ["environment"],
    },
)
async def deploy(environment: str, confirm: bool = True, ctx: AppContext | None = None) -> str:
    if ctx is None or ctx.app is None:
        return "Error: no app context."

    if confirm:
        from ui.widgets.confirm_modal import ConfirmModal
        confirmed = await ctx.app.push_screen_wait(
            ConfirmModal(
                title=f"Deploy to {environment}?",
                body=f"This will deploy to {environment} from {ctx.working_directory}",
                confirm_label="Deploy",
            )
        )
        if not confirmed:
            return "Deployment cancelled."

    # Do the deployment
    import asyncio
    proc = await asyncio.create_subprocess_shell(
        f"./deploy.sh {environment}",
        cwd=ctx.working_directory,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode == 0:
        return f"Deployed to {environment} successfully."
    return f"Deploy failed (exit {proc.returncode}): {stderr.decode()}"
```

### Example 3: Workspace Tab Plugin

See the [Workspace Tabs](workspace_tabs.md) document for a complete
example of a tab that opens a file viewer in a workspace pane with
state persistence across splits.

---

## Advanced Patterns

### Auto-Discovery Provider Pattern

When your plugin supports multiple backends (e.g. different database
types), use the auto-discovery pattern:

1. Define an ABC and a decorator registry in your core module.
2. Create a `providers/` sub-package that auto-imports all `.py` files.
3. Each provider self-registers via the decorator at import time.

See the [Plugins](plugins.md) document for the full pattern with the
database plugin as an example.

### Lazy Imports for Optional Dependencies

If a dependency isn't always available, import it inside the function
that uses it rather than at the top of the module:

```python
@register_tool(name="my_tool", tags=["my_plugin"], ...)
async def my_tool(query: str) -> str:
    import heavy_dependency  # only imported when the tool is called
    return heavy_dependency.search(query)
```

This lets the plugin load successfully even if the dependency isn't
installed.  The tool will fail only when actually invoked.

### Accessing AppContext from Widgets

Textual widgets can reach the app context via `self.app`:

```python
class MyWidget(Widget):
    def on_mount(self) -> None:
        ctx = self.app.context
        theme = ctx.config.get("ui.theme", "default")
        if ctx.vault and not ctx.vault.is_locked():
            cred = ctx.vault.get_credential("my_service")
```

### Pushing Modals from Sync Handlers

Event handlers are synchronous, but modals require `await`.  Use
`app.run_worker()`:

```python
@register_handler("my_plugin.prompt")
def _on_prompt(data: dict, ctx: AppContext) -> None:
    app = ctx.app
    if app is None:
        return

    async def do_prompt() -> None:
        from ui.widgets.input_modal import InputModal
        result = await app.push_screen_wait(InputModal("Enter value:"))
        if result is not None:
            ctx.config.set("my_plugin.value", result)
            ctx.config.save()
            app.notify("Value saved!")

    app.run_worker(do_prompt())
```

### Disabling a Bundled Plugin

Create an empty override in a higher tier:

```bash
mkdir -p ~/.agents/plugins/database
echo '---\nname: database\ndescription: Disabled\n---' > ~/.agents/plugins/database/SKILL.md
echo '"""Disabled."""' > ~/.agents/plugins/database/__init__.py
```

Or set `"database": false` in config under `plugins.enabled`.

---

## Troubleshooting

### Plugin not discovered

- Ensure `SKILL.md` exists with valid YAML frontmatter (`name` + `description` required).
- Check the directory name and location match the tier path.

### Import errors

- Verify `__init__.py` exists.
- Use fully-qualified imports: `from core.events import ...`, not `from ..core.events import ...`.
- The project root is on `sys.path` — don't manipulate it yourself.

### Handlers not firing

- Modules with `@register_handler` must be imported by `__init__.py`.

### Tool not showing up

- Modules with `@register_tool` must be imported by `__init__.py`.
- Or place tools in a `tools/` directory for auto-discovery (skills only — plugins need explicit import).

### Plugin fails to load (missing dependency)

- Check stderr for the warning message.
- List the dependency in `requirements:` in SKILL.md.
- Or use lazy imports inside the functions that use it.
- After installing the missing dependency, restart Cody.

### CSS not applied

- The `.tcss` file must be in the plugin directory.
- File is auto-collected by `collect_plugin_tcss()`.
- Check the file extension is `.tcss` (not `.css`).

### Leader chord conflicts

- The registry detects conflicts at registration time and raises `ValueError`.
- Choose a different key path (e.g. `["m", "x"]` instead of `["m", "o"]`).

---

## Quick Reference: All Registries

| What | Module | Decorator/Function | Parameters |
|---|---|---|---|
| Sidebar tab | `ui.sidebar.registry` | `@register_sidebar_tab(name, icon, side, tooltip)` | Widget subclass |
| Event handler | `core.events` | `@register_handler(event_type)` | `(data: dict, ctx: AppContext)` |
| LLM tool | `core.tools` | `@register_tool(name, description, parameters, tags)` | Sync or async function |
| Slash command | `core.commands` | `@register_command(name, description)` | `async (app, args: str)` |
| Leader chord | `core.leader` | `register_action(keys, label, event_type=)` | None (side-effect) |
| Leader submenu | `core.leader` | `register_submenu(keys, label)` | None (side-effect) |
| Config defaults | `core.config` | `register_defaults(dict)` | Nested dict |
| Terminal passthrough | `core.terminal_passthrough` | `register_terminal_passthrough(keys)` | Set of key strings |

---

## Quick Reference: AppContext Fields

| Field | Type | What it provides |
|---|---|---|
| `config` | `Config` | Layered JSON config with dot-path access |
| `skills` | `SkillManager` | Skill catalog (query available skills) |
| `database` | `DatabaseManager` | Chat, message, agent, todo CRUD |
| `db_connections` | `Any` | ConnectionManager from database plugin (or None) |
| `leader` | `LeaderRegistry` | Keyboard chord tree |
| `vault` | `VaultManager` | Encrypted credential + note storage |
| `working_directory` | `str` | Current project directory |
| `app` | `CodyApp` | Running Textual app instance (set after construction) |

---

## Quick Reference: File Conventions

| File | Where | Auto-discovered? | What it registers |
|---|---|---|---|
| `SKILL.md` | Plugin root | Yes (discovery marker) | Plugin name, description, requirements |
| `__init__.py` | Plugin root | Yes (entry point) | All `@register_*` via side-effect imports |
| `*.tcss` | Plugin root (any depth) | Yes | Widget styles |
| `cmd/*.py` | Skills only | Yes | `@register_command()` |
| `tools/*.py` | Skills only | Yes | `@register_tool()` |

**Important:** Plugin code must be explicitly imported from `__init__.py`.
Auto-discovery of `cmd/` and `tools/` directories only works for skills.