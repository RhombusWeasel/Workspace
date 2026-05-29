# Creating a Skill — Complete Guide

This guide walks through everything you need to create a new Cody skill,
from understanding the architecture to writing, testing, and installing
your skill.

---

## Table of Contents

1. [What Skills Can Do](#what-skills-can-do)
2. [Skill Anatomy](#skill-anatomy)
3. [Choosing a Location](#choosing-a-location)
4. [Step 1: Create SKILL.md](#step-1-create-skillmd)
5. [Step 2: Decide on `__init__.py`](#step-2-decide-on-__init__py)
6. [Step 3: Register Components](#step-3-register-components)
7. [Step 4: Add CSS](#step-4-add-css)
8. [Step 5: Test and Install](#step-5-test-and-install)
9. [Complete Examples](#complete-examples)
10. [Advanced Patterns](#advanced-patterns)
11. [Troubleshooting](#troubleshooting)

---

## What Skills Can Do

Skills can register any combination of:

| Component | How to Register | What It Does |
|---|---|---|
| Agent knowledge | SKILL.md body | Instructions the LLM reads via `activate_skill` |
| Sidebar panel | `@register_sidebar_tab()` | Adds a panel to the left or right sidebar |
| Event handler | `@register_handler()` | Responds to `CodyEvent` messages |
| LLM tool | `@register_tool()` | Exposes a function the LLM can invoke |
| Slash command | `@register_command()` | Adds a `/command` the user can type |
| Leader chord | `register_action()` / `register_submenu()` | Adds keyboard shortcuts to `Ctrl+Space` menu |
| Config defaults | `register_defaults()` | Provides default values for config keys |
| Skill services | `SKILL_SERVICES` dict | Provides services to other parts of the app |
| CSS | `.tcss` file in skill dir | Styles the skill's widgets |

---

## Skill Anatomy

### Minimal skill (ecosystem compatible)

```
my_skill/
├── SKILL.md              # Required — manifest with name + description
└── scripts/               # Optional — run via run_skill tool
    └── deploy.py
```

No `__init__.py` — compatible with the Anthropic skill specification.

### Full-featured UI skill

```
my_skill/
├── SKILL.md              # Manifest (name, description, optional requirements)
├── __init__.py            # Entry point — imports modules with @register_*
├── core/                  # Skill internals
│   ├── __init__.py
│   └── connections.py
├── handlers.py            # Event handlers (@register_handler)
├── tools.py               # Agent-callable tools (@register_tool)
├── cmd/                   # Slash commands (auto-discovered)
│   └── mycommand.py
├── my_skill.tcss         # Skill CSS (auto-collected)
└── services.py            # SKILL_SERVICES factory
```

### Hybrid skill (agent knowledge + UI)

```
my_skill/
├── SKILL.md              # Body = agent knowledge for the LLM
├── scripts/               # Agent-runnable scripts
│   └── status.py
├── components/            # Auto-imported UI modules
│   └── panel.py
├── tools/                 # Auto-imported agent tools
│   └── my_tool.py
└── my_skill.tcss
```

No `__init__.py` — `components/`, `tools/`, and `cmd/` are imported as
flat files by the bootstrap loader.

---

## Choosing a Location

| Tier | Path | Scope | Override behavior |
|---|---|---|---|
| **Bundled** | `{cody_dir}/skills/my_skill/` | Ships with Cody | Overridden by user or project |
| **User-global** | `~/.agents/skills/my_skill/` | Available in all projects | Overrides bundled, overridden by project |
| **Project-local** | `{project}/.agents/skills/my_skill/` | Current project only | Highest precedence |

For most skills, use **user-global** (`~/.agents/skills/`).  Use
**project-local** for project-specific tools.

---

## Step 1: Create SKILL.md

The manifest uses YAML frontmatter:

```markdown
---
name: my_skill
description: Short description shown in the skill catalog
requirements:
  - requests>=2.28
  - psycopg2-binary>=2.9
---

# My Skill

Longer markdown documentation about what the skill does.
This body is available via the `activate_skill` tool if the LLM asks.
```

| Field | Required | Description |
|---|---|---|
| `name` | **Yes** | Unique skill name (letters, numbers, hyphens, underscores) |
| `description` | **Yes** | Short description (shown in catalog and skill list) |
| `requirements` | No | YAML list of pip-format package specifiers |

If `requirements` is declared, `uv pip install` (or `pip install`) is run
when installing via `/skill install`.  For manually-created skills,
install dependencies yourself:

```bash
uv pip install requests>=2.28
```

Or use **lazy imports** so the module can load even if the package isn't
installed yet:

```python
@register_handler("my_skill.fetch")
def _on_fetch(data, ctx):
    import requests  # imported only when the handler is called
    ...
```

---

## Step 2: Decide on `__init__.py`

`__init__.py` is **optional**.  Whether you need it depends on the skill
type:

| Skill type | Need `__init__.py`? | Why |
|---|---|---|
| Ecosystem / knowledge only | ❌ | No Python code needs to run at import time |
| Flat UI components | ❌ | `components/`, `tools/`, `cmd/` are auto-imported |
| Complex UI with sub-packages | ✅ | Needed for correct `__path__`/`__package__` resolution |
| Skills with `SKILL_SERVICES` | ✅ | Services must be declared in a module-level dict |

If you add `__init__.py`, it's the entry point.  It must import all modules
that contain `@register_*` decorators — otherwise the decorators never execute:

```python
# skills/my_skill/__init__.py
"""My Skill — does something useful."""

# Side-effect imports trigger decorator registrations.
from skills.my_skill.handlers import register_handlers  # noqa: F401
from skills.my_skill.services import SKILL_SERVICES      # noqa: F401

# Direct registrations can also go here:
from core.leader import register_submenu, register_action

register_submenu(["m"], "My Skill")
register_action(["m", "o"], "Open", event_type="my_skill.open")

# Declare services for other components
SKILL_SERVICES = {
    "my_service": create_my_service,
}

__all__ = ["SKILL_SERVICES"]
```

**The golden rule:** If a module has a `@register_handler`, `@register_tool`,
`@register_sidebar_tab`, or `@register_command` decorator, it must be
imported (directly or transitively) by `__init__.py` or live in a
auto-discovered directory (`components/`, `tools/`, `cmd/`).

---

## Step 3: Register Components

### Sidebar Panel

```python
from ui.sidebar.registry import register_sidebar_tab

@register_sidebar_tab(name="my_panel", icon="★", side="left", tooltip="My Skill")
class MyPanel(Container):
    def compose(self):
        yield Static("My panel content")
```

See [Sidebar Registry](sidebar.md) for full details.

### Event Handler

```python
from core.events import register_handler
from context import AppContext

@register_handler("my_skill.greet")
def _on_greet(data: dict, ctx: AppContext) -> None:
    app = ctx.app
    if app is None:
        return
    name = data.get("name", "stranger")
    app.notify(f"Hello, {name}!", title="My Skill")
```

See [Events](events.md) for full details.

### LLM Tool

```python
from core.tools import register_tool

@register_tool(
    name="my_lookup",
    tags=["my_skill"],
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

Place in your skill's `cmd/` directory for auto-discovery, or import
from `__init__.py`:

```python
# skills/my_skill/cmd/greet.py
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

register_submenu(["m"], "My Skill")
register_action(
    ["m", "o"], "Open", event_type="my_skill.open",
    labels={"m": "My Skill"},
)
```

See [Leader Chords](leader.md) for full details.

### Config Defaults

```python
from core.config import register_defaults

register_defaults({
    "my_skill": {
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

@register_handler("my_skill.open_tab")
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
        "my-tab", "My Skill", state=state,
        content_factory=_create_my_content,
    )
```

See [Workspace Tabs](workspace_tabs.md) for persistence patterns and full details.

### Skill Services

```python
# skills/my_skill/services.py
from core.config import Config
from core.vault import VaultManager

def create_my_service(config: Config, vault: VaultManager):
    return MyService(config, vault)

# skills/my_skill/__init__.py
from skills.my_skill.services import create_my_service

SKILL_SERVICES = {
    "my_service": create_my_service,
}
```

Bootstrap calls each factory with `(config, vault)` and stores the
result in `AppContext.services`.  Other components access it via
`ctx.services["my_service"]` or, for known services like
`db_connections`, via `ctx.db_connections`.

---

## Step 4: Add CSS

Create a `.tcss` file in the skill directory.  It's auto-collected by
`collect_tcss()`:

```css
/* my_skill.tcss */
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

1. Place the skill in `~/.agents/skills/my_skill/`
2. Restart Cody
3. Check stderr for any import errors
4. Test your registered components

### Installing from a git repo

```bash
/skill install https://github.com/you/cody-my-skill
```

This clones the repo, installs dependencies, writes `.skill.json`, and
updates config.

### Updating

```bash
/skill update my_skill
/skill update my_skill --version v1.2.0
/skill update --all
```

### Removing

```bash
/skill remove my_skill
/skill remove my_skill --local    # project-local only
```

### Listing

```bash
/skill list
```

---

## Complete Examples

### Example 1: Minimal Knowledge Skill

```
~/.agents/skills/deployment/
├── SKILL.md
└── scripts/
    └── deploy.py
```

```markdown
<!-- SKILL.md -->
---
name: deployment
description: Deployment procedures and best practices
---

# Deployment Guide

## Staging

Run `./deploy.sh staging` from the project root...

## Production

Production deployments require approval...
```

No `__init__.py` — this is an ecosystem-compatible knowledge skill.
The LLM activates it via `activate_skill` and reads the instructions.

### Example 2: UI Skill with Sidebar Panel

```
~/.agents/skills/greeter/
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
"""Greeter skill."""
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

### Example 3: Tool Skill with Confirmation

```
~/.agents/skills/deployer/
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
"""Deployer skill."""
from skills.deployer.tools import register_deployer_tools  # noqa: F401
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

### Example 4: Workspace Tab Skill

See the [Workspace Tabs](workspace_tabs.md) document for a complete
example of a tab that opens a file viewer in a workspace pane with
state persistence across splits.

---

## Advanced Patterns

### Auto-Discovery Provider Pattern

When your skill supports multiple backends (e.g. different database
types), use the auto-discovery pattern:

1. Define an ABC and a decorator registry in your core module.
2. Create a `providers/` sub-package that auto-imports all `.py` files.
3. Each provider self-registers via the decorator at import time.

See the [Skills](skills.md) document and the database skill for the
full pattern.

### Lazy Imports for Optional Dependencies

If a dependency isn't always available, import it inside the function
that uses it rather than at the top of the module:

```python
@register_tool(name="my_tool", tags=["my_skill"], ...)
async def my_tool(query: str) -> str:
    import heavy_dependency  # only imported when the tool is called
    return heavy_dependency.search(query)
```

This lets the skill load successfully even if the dependency isn't
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
@register_handler("my_skill.prompt")
def _on_prompt(data: dict, ctx: AppContext) -> None:
    app = ctx.app
    if app is None:
        return

    async def do_prompt() -> None:
        from ui.widgets.input_modal import InputModal
        result = await app.push_screen_wait(InputModal("Enter value:"))
        if result is not None:
            ctx.config.set("my_skill.value", result)
            ctx.config.save()
            app.notify("Value saved!")

    app.run_worker(do_prompt())
```

### Disabling a Bundled Skill

Create an empty override in a higher tier:

```bash
mkdir -p ~/.agents/skills/database
echo '---\nname: database\ndescription: Disabled\n---' > ~/.agents/skills/database/SKILL.md
echo '"""Disabled."""' > ~/.agents/skills/database/__init__.py
```

Or set `"database": false` in config under `skills.enabled`.

---

## Troubleshooting

### Skill not discovered

- Ensure `SKILL.md` exists with valid YAML frontmatter (`name` + `description` required).
- Check the directory name and location match the tier path.

### Import errors

- If the skill has `__init__.py`, verify it exists and is syntactically valid.
- Use fully-qualified imports: `from core.events import ...`, not `from ..core.events import ...`.
- The project root is on `sys.path` — don't manipulate it yourself.
- For `__init__.py` skills, sub-imports should use `from skills.my_skill.core import X`.

### Handlers not firing

- Modules with `@register_handler` must be imported by `__init__.py`
  or live in a `components/` directory.

### Tool not showing up

- Modules with `@register_tool` must be imported by `__init__.py`
  or live in a `tools/` directory (auto-discovered).

### Skill fails to load (missing dependency)

- Check stderr for the warning message.
- List the dependency in `requirements:` in SKILL.md.
- Or use lazy imports inside the functions that use it.
- After installing the missing dependency, restart Cody.

### CSS not applied

- The `.tcss` file must be in the skill directory.
- File is auto-collected by `collect_tcss()`.
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
| `db_connections` | `Any` | ConnectionManager from database skill (or None) |
| `leader` | `LeaderRegistry` | Keyboard chord tree |
| `vault` | `VaultManager` | Encrypted credential + note storage |
| `working_directory` | `str` | Current project directory |
| `services` | `dict[str, Any]` | Dynamic service instances from skill `SKILL_SERVICES` |
| `app` | `CodyApp` | Running Textual app instance (set after construction) |

---

## Quick Reference: File Conventions

| File | Where | Auto-discovered? | What it registers |
|---|---|---|---|
| `SKILL.md` | Skill root | Yes (discovery marker) | Skill name, description, requirements |
| `__init__.py` | Skill root | Yes (entry point for UI skills) | All `@register_*` via side-effect imports |
| `*.tcss` | Skill directory (any depth) | Yes | Widget styles |
| `components/*.py` | Skill subdirectory | Yes | `@register_sidebar_tab()`, `@register_handler()`, etc. |
| `cmd/*.py` | Skill subdirectory | Yes | `@register_command()` |
| `tools/*.py` | Skill subdirectory | Yes | `@register_tool()` |
| `scripts/*.py` | Skill subdirectory | No (run via `run_skill`) | Agent-runnable scripts |