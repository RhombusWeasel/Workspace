# Plugin System

**Files:** `core/paths.py` (discovery), `bootstrap.py` (loading), `plugins/` (bundled plugins)

---

## Purpose

Plugins extend Cody with sidebar panels, event handlers, tools, and
application-level services — all without modifying the core codebase.
Plugins are discovered via a 3-tier directory scan and loaded dynamically
at startup.

---

## How Discovery Works

`core/paths.resolve(subpath, working_dir)` returns three directories in
order of increasing precedence:

| Tier | Path | Scope |
|---|---|---|
| 1 — Bundled | `{cody_dir}/plugins/` | Ships with Cody |
| 2 — User | `~/.agents/plugins/` | Global per-user plugins |
| 3 — Project | `{working_dir}/.agents/plugins/` | Per-project plugins |

`discover_plugins(working_dir)` scans each tier for subdirectories containing
a `SKILL.md` manifest.  When two tiers have a plugin with the same directory
name, the **later tier wins** — a project-level plugin overrides a user-level
plugin, which overrides a bundled plugin.

```python
# Example: discover_plugins returns absolute paths to plugin directories
# in tier order, with later-tier overrides applied.
paths = discover_plugins("/home/alice/projects/myapp")
# → ["/opt/cody/plugins/database", "/home/alice/.agents/plugins/git_helper"]
#    bundled plugin             user-level plugin
```

---

## Plugin Directory Structure

A plugin directory must contain a `SKILL.md` and an `__init__.py`:

```
plugins/my_plugin/
├── SKILL.md              # Required — manifest (name + description)
├── __init__.py            # Required — entry point for registrations
├── core/                  # Optional — plugin internals
│   ├── __init__.py
│   └── connections.py
├── my_plugin.tcss         # Optional — plugin CSS (Textual)
├── handlers.py            # Optional — event handlers
├── tools.py               # Optional — agent-callable tools
└── services.py            # Optional — PLUGIN_SERVICES factory
```

### SKILL.md

The manifest uses YAML frontmatter (same format as skills):

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
```

The `name` and `description` fields are **required**.  The `requirements`
field is optional — a YAML list of Python package specifiers (in `pip`
format) that the plugin needs.  When the plugin manager installs a
plugin, it runs `uv pip install` (falling back to `pip install`) to
install these dependencies into the project's virtual environment.

Plugins without `requirements` (or with an empty list) are assumed to
only need packages already in the Cody environment.

### __init__.py (Entry Point)

The `__init__.py` is executed by the bootstrap loader.  It should import
and trigger any modules that register sidebar tabs, event handlers, tools,
or config defaults:

```python
# plugins/my_plugin/__init__.py
"""My Plugin — does something useful."""

# Side-effect imports trigger decorator registrations.
from plugins.my_plugin.handlers import register_handlers  # noqa: F401
from plugins.my_plugin.services import PLUGIN_SERVICES       # noqa: F401

__all__ = ["PLUGIN_SERVICES"]
```

**Important:** modules containing `@register_handler`, `@register_sidebar_tab`,
or `@register_tool` decorators must be imported (directly or transitively)
by `__init__.py` — otherwise the decorators never execute and those
registrations are silently skipped.

---

## How Plugins Are Loaded

The bootstrap sequence in `Bootstrap._load_plugins()`:

1. **`sys.path` guarantee** — The Cody project root is added to `sys.path`
   so plugins can import from `core/` regardless of where the plugin
   directory lives on disk.

2. **Package namespace setup** — A synthetic `plugins` package is registered
   in `sys.modules` with its `__path__` pointing to `{cody_dir}/plugins/`.
   This enables absolute imports like `from plugins.my_plugin.core import X`.

3. **Per-plugin loading** — For each discovered plugin directory:
   - The `__init__.py` is located and loaded via
     `importlib.util.spec_from_file_location`.
   - `__path__` is set to `[plugin_dir]` so that sub-imports resolve from
     the plugin's own directory (even if it lives in `~/.agents/`).
   - `__package__` is set to `f"plugins.{mod_name}"` for correct relative
     import resolution.
   - The module is registered in `sys.modules` under its fully-qualified name.
   - If the module declares a `PLUGIN_SERVICES` dict, each factory callable
     is called with `(config, vault)` and the result is collected.

4. **CSS collection** — ``paths.collect_plugin_tcss()`` gathers ``.tcss`` files from
   all discovered plugin directories for Textual's CSS cascade.

5. **Requirement installation** — If the SKILL.md declares a `requirements`
   list, `PluginManager.install()` runs `uv pip install` (falling back to
   `pip install`) to install those packages into the project's virtual
   environment.  Since plugins run in-process, their dependencies must be
   on `sys.path`.  Requirements are also recorded in `.plugin.json`.

6. **Error isolation** — If a plugin fails to load (e.g. a required
   package is still missing, or there's an `ImportError`), the bootstrap
   logs a warning to `stderr` and skips that plugin.  The application
   continues to start — one broken plugin doesn't crash the entire app.
   The failed module is removed from `sys.modules` so a retry after
   installing the missing dependency will work on the next startup.

---

## Import Resolution

Plugins can import from Cody's core modules because the project root is on
`sys.path` before any plugin is loaded:

```python
# Inside a plugin at ~/.agents/plugins/my_plugin/handlers.py
from core.events import register_handler    # ✅ works
from core.config import Config              # ✅ works
from core.vault import VaultManager         # ✅ works
from context import AppContext              # ✅ works
```

Sub-imports within a plugin resolve from the plugin's own directory because
`__path__` is set correctly during loading:

```python
# Inside plugins/my_plugin/__init__.py
from plugins.my_plugin.core.connections import ConnectionManager  # ✅ works
```

---

## What Plugins Can Register

### Sidebar Tabs

```python
from ui.sidebar.registry import register_sidebar_tab

@register_sidebar_tab(name="my_panel", icon="◉", side="left", tooltip="My Panel")
class MyPanel(Container):
    ...
```

### Event Handlers

```python
from core.events import register_handler
from context import AppContext

@register_handler("my_plugin.action")
def _on_my_action(data: dict, ctx: AppContext) -> None:
    ...
```

### Agent-Callable Tools

```python
from core.tools import register_tool

@register_tool(
    name="my_tool",
    description="Does something the LLM can invoke",
    parameters={"type": "object", "properties": {"query": {"type": "string"}}},
)
def my_tool(query: str) -> str:
    return f"Result for: {query}"
```

### Slash Commands

```python
from core.commands import register_command

@register_command(name="mycommand", description="My custom command")
async def my_command(app, args: str) -> None:
    # app is the running CodyApp instance
    # args is the raw text after the /command name
    app.notify("Done!")
```

### Config Defaults

```python
from core.config import register_defaults

register_defaults({
    "my_plugin": {
        "max_items": 100,
        "auto_refresh": True,
    }
})
```

---

## Plugin Services (AppContext Extension)

Plugins that need to provide services to other parts of the application
declare a `PLUGIN_SERVICES` dict in their `__init__.py`.  Each entry maps
a service name to a factory callable that receives `(config, vault)`:

```python
# plugins/my_plugin/__init__.py
from plugins.my_plugin.services import create_connection_manager

PLUGIN_SERVICES = {
    "my_service": create_connection_manager,
}
```

```python
# plugins/my_plugin/services.py
from core.config import Config
from core.vault import VaultManager
from plugins.my_plugin.core.connections import ConnectionManager

def create_connection_manager(config: Config, vault: VaultManager) -> ConnectionManager:
    return ConnectionManager(config, vault)
```

Bootstrap calls each factory and stores the result in `AppContext`:

```python
# In AppContext dataclass:
my_service: Any = None  # Populated by plugin if loaded
```

Other components access the service via `ctx.my_service`.

---

## Auto-Discovery Provider Pattern

The database plugin demonstrates a self-registering provider pattern that
makes it trivial to add new database backends.  The key insight: providers
live in a ``providers/`` sub-package that auto-discovers ``.py`` files at
import time and registers them via ``@register_provider``.

### How it works

```
plugins/database/core/
├── db_connections.py     ← DBProvider ABC, registry, ConnectionManager
└── providers/
    ├── __init__.py      ← Auto-discovers .py files, imports them
    └── sqlite.py        ← @register_provider class SQLiteProvider
```

1. ``db_connections.py`` defines the ``DBProvider`` abstract base class
   and the ``register_provider()`` decorator / registry functions.

2. At the bottom of ``db_connections.py``, it imports the providers
   sub-package::

       from plugins.database.core.providers import *  # noqa: F401,F403,E402

3. ``providers/__init__.py`` scans its own directory for ``.py`` files
   (excluding ``_``-prefixed modules) and imports each one via
   ``importlib.import_module()``.

4. Each provider module (e.g. ``sqlite.py``) decorates its class with
   ``@register_provider``, which self-registers into the global
   ``_providers`` dict.

5. When ``ConnectionManager`` needs a provider, it calls
   ``get_provider("sqlite")`` and gets back the registered class.

### Adding a new provider

Drop a ``.py`` file into ``providers/`` and decorate the class:

```python
# plugins/database/core/providers/postgres.py
from typing import Any
from plugins.database.core.db_connections import (
    DBProvider, FormField, ColumnInfo, TableInfo,
    ViewInfo, TriggerInfo, QueryResult, register_provider,
)

@register_provider
class PostgreSQLProvider(DBProvider):

    @classmethod
    def provider_type(cls) -> str:
        return "postgres"

    @classmethod
    def display_label(cls, params: dict[str, str]) -> str:
        return f"{params.get('host', 'localhost')}:{params.get('port', '5432')}"

    @classmethod
    def form_fields(cls) -> list[FormField]:
        return [
            FormField(name="host", label="Host", default="localhost"),
            FormField(name="port", label="Port", type="number", default="5432"),
            FormField(name="database", label="Database"),
            FormField(name="user", label="Username"),
            FormField(name="password", label="Password", type="password", sensitive=True),
        ]

    @classmethod
    def connect(cls, params: dict[str, str]) -> Any:
        import psycopg2
        return psycopg2.connect(
            host=params.get("host", "localhost"),
            port=int(params.get("port", "5432")),
            dbname=params.get("database", ""),
            user=params.get("user", ""),
            password=params.get("password", ""),
        )

    # ... (implement all other DBProvider methods)
```

No other changes needed — the connection form will automatically show
the new provider type in its dropdown, and ``ConnectionManager`` will
route to it when a connection uses ``provider_type: "postgres"``.

### Pattern for other plugins

The same auto-discovery pattern works for any plugin that wants
extensible backends:

1. Define an ABC and a decorator registry in your core module.
2. Create a ``providers/`` (or ``backends/``, ``handlers/``, etc.) sub-package.
3. Write an ``__init__.py`` that auto-imports all ``.py`` files.
4. Import the sub-package at the bottom of your core module.
5. Each provider self-registers via the decorator at import time.

---

## 3-Tier Overriding

When the same plugin name exists in multiple tiers, the later tier wins:

```
/opt/cody/plugins/database/      ← bundled (tier 1)
~/.agents/plugins/database/      ← user override (tier 2) ✅ WINS
```

This lets users override bundled plugins with their own versions.  To
**disable** a bundled plugin entirely, create an empty `SKILL.md` in the
override directory (the plugin's `__init__.py` must still exist to be
loaded; use `pass` or a docstring as the body).

---

## Creating a Plugin: Step by Step

### 1. Choose a location

- **User-global:** `~/.agents/plugins/my_plugin/`
- **Project-local:** `{project}/.agents/plugins/my_plugin/`

### 2. Create the directory structure

```bash
mkdir -p ~/.agents/plugins/my_plugin
```

### 3. Write SKILL.md

```bash
cat > ~/.agents/plugins/my_plugin/SKILL.md << 'EOF'
---
name: my_plugin
description: My custom Cody plugin
requirements:
  - requests>=2.28
---

# My Plugin

Describe what your plugin does here.
EOF
```

If your plugin needs Python packages that aren't already in Cody's
environment, list them in the `requirements` field.  The plugin manager
will install them automatically when you run `/plugin install`.  If
you're creating the plugin by hand (not via `/plugin install`), you'll
need to install the dependencies yourself:

```bash
uv pip install requests>=2.28
# or: python -m pip install requests>=2.28
```

### 4. Write __init__.py

```python
# ~/.agents/plugins/my_plugin/__init__.py
"""My Plugin — custom sidebar for Cody."""

from core.events import register_handler
from core.config import register_defaults
from context import AppContext
from textual.containers import Container
from textual.widgets import Static
from ui.sidebar.registry import register_sidebar_tab

# Register config defaults
register_defaults({
    "my_plugin": {
        "greeting": "Hello from my plugin",
    }
})

# Register a sidebar tab
@register_sidebar_tab(name="my_panel", icon="★", side="left", tooltip="My Plugin")
class MyPanel(Container):
    def compose(self):
        yield Static("My Plugin Panel")

# Register an event handler
@register_handler("my_plugin.greet")
def _on_greet(data: dict, ctx: AppContext) -> None:
    if ctx.app:
        msg = ctx.config.get("my_plugin.greeting", "Hi")
        ctx.app.notify(msg, title="My Plugin")
```

### 5. Add CSS (optional)

Create `my_plugin.tcss` in the same directory:

```css
MyPanel {
    height: 100%;
    background: $surface;
}

MyPanel Static {
    padding: 1 2;
}
```

### 6. Restart Cody

Plugins are discovered at startup.  Restart the app to pick up your new plugin.

---

## Troubleshooting

### Plugin not discovered

- Ensure `SKILL.md` exists in the plugin directory with valid YAML
  frontmatter (both `name` and `description` required).
- Check that the directory name matches the expected location:
  `~/.agents/plugins/my_plugin/` or `{project}/.agents/plugins/my_plugin/`.

### Import errors

- Check that `__init__.py` exists in the plugin directory.
- Verify imports use fully-qualified names (`from core.events import ...`,
  not `from ..core.events import ...`).
- The Cody project root is automatically added to `sys.path` before
  plugins load — you should not need to manipulate `sys.path` yourself.
- **If a plugin fails to load due to a missing dependency** (e.g.
  `ModuleNotFoundError: No module named 'requests'`), the bootstrap
  logs a warning to stderr and skips that plugin.  The application
  continues to start.  After installing the missing package,
  restart Cody to load the plugin successfully.

### Handler not firing

- Modules with `@register_handler` decorators must be imported by
  `__init__.py` (directly or transitively).  A decorator in a module that
  is never imported will never execute.

### Plugin fails to load (missing dependency)

- If the plugin's `__init__.py` (or any module it imports) raises
  `ImportError` or `ModuleNotFoundError`, the bootstrap skips that
  plugin and prints a warning to stderr.  Install the missing package
  and restart:
  ```
  Warning: skipping plugin 'my_plugin': No module named 'requests'
  ```
- Make sure `requirements:` is declared in `SKILL.md` so the plugin
  manager auto-installs dependencies when using `/plugin install`.
- For manually-created plugins, run `uv pip install <package>` or
  `python -m pip install <package>` to install into Cody's venv.
- Alternatively, use **lazy imports** inside functions that actually use
  the dependency, so the module can load even if the package isn't
  installed yet:
  ```python
  # __init__.py — always loads
  @register_handler("my_plugin.fetch")
  def _on_fetch(data, ctx):
      import requests  # only imported when the handler is called
      ...
  ```

### Sub-imports fail

- Each plugin module is loaded with `__path__` pointing to its directory
  and `__package__` set to `plugins.{name}`.  Sub-imports should use
  absolute paths: `from plugins.my_plugin.core import X`.

---

## Architecture Diagram

```
Bootstrap._load_plugins()
    │
    ├── _ensure_project_on_path()        ← adds cody_dir to sys.path
    │
    ├── Register synthetic 'plugins'     ← sys.modules["plugins"] + __path__
    │   package in sys.modules
    │
    └── For each discovered plugin dir:
        │
        ├── spec_from_file_location()    ← loads __init__.py
        │
        ├── Set __path__ = [plugin_dir]  ← sub-imports resolve here
        ├── Set __package__ = "plugins.name"
        │
        ├── spec.loader.exec_module()   ← triggers @register_* decorators
        │
        └── Collect PLUGIN_SERVICES      ← factories called with (config, vault)
```

---

## Design Decisions

1. **SKILL.md as manifest** — Reuses the same discovery format as skills.
   Plugins ARE skills, but they also carry Python code that registers
   UI components, event handlers, and services.

2. **Decorator self-registration** — `@register_sidebar_tab`,
   `@register_handler`, `@register_tool`, and `@register_command` all
   self-register at import time.  Plugin authors just write decorators;
   no manual wiring needed.

3. **sys.path guarantee** — The Cody project root is explicitly added to
   `sys.path` before plugins load.  This means plugins can import from
   `core/` regardless of where the plugin directory lives on disk.  This
   is intentional: plugins are extensions of Cody, not independent applications.

4. **__path__ and __package__ for each plugin** — Without setting these,
   `importlib.util.spec_from_file_location` creates modules whose
   sub-imports break when the plugin lives outside the Cody installation
   directory.  Explicitly setting them ensures `from plugins.my_plugin.core`
   resolves from the correct directory.

5. **PLUGIN_SERVICES for AppContext extension** — Rather than having plugins
   mutate `AppContext` directly, they declare service factories that bootstrap
   calls and injects.  This keeps the context dataclass clean and makes it
   obvious which plugins contribute which services.

6. **Later tier overrides earlier** — Same as skills, CSS, and config: a
   project-level plugin at `{wd}/.agents/plugins/my_plugin/` silently replaces
   a user-level or bundled plugin with the same name.

7. **Dependencies install into the project venv** — Since plugins run
   in-process, their Python dependencies must be on `sys.path`.  The
   plugin manager installs `requirements:` from SKILL.md directly into
   Cody's virtual environment using `uv pip install` (or `pip install`
   as fallback).  This is a conscious trade-off: it's simple and works,
   but means there's no isolation between plugin dependencies.  On
   `/plugin remove`, dependencies are NOT uninstalled (other things
   may depend on them).

8. **Graceful degradation on import failure** — If a plugin can't be
   loaded (missing dependency, import error, syntax error), the bootstrap
   catches the exception, prints a warning to stderr, and skips that
   plugin.  The application continues to start.  This prevents a single
   broken plugin from making the entire app unusable.  The broken
   module is also removed from `sys.modules` so a retry after fixing
   the issue works without restarting Python.

---

## Plugin Manager

Cody includes a plugin manager (``core/plugin_manager.py``) that handles
installing, updating, removing, and listing plugins from git repositories.
Plugins are always installed from a **tagged release** — never from a live
branch.  After cloning, the ``.git/`` directory is stripped so installed
plugins are just source files with no nested git repo.

### Install metadata: ``.plugin.json``

Every plugin installed via the manager gets a ``.plugin.json`` file in its
directory:

```json
{
    "source": "https://github.com/user/cody-postgres",
    "version": "v0.3.1",
    "installed_at": "2025-05-21T10:30:00Z",
    "requirements": [
        "psycopg2-binary>=2.9",
        "requests>=2.28"
    ]
}
```

This file is the source of truth for "what version is installed, where
it came from, and what dependencies it needs".  Plugins without
``.plugin.json`` are either bundled or manually created — they still work
fine, they just can't be updated via the ``/plugin update`` command.

The ``requirements`` field is populated from the ``requirements:`` list in
the plugin's SKILL.md.  It's stored here for reference and for any future
``/plugin deps`` command that re-installs dependencies.

### Config integration

Install metadata is mirrored to the layered config under ``plugins.installed``,
and enable/disable state is tracked under ``plugins.enabled``:

```json
// ~/.agents/config/config.json
{
    "plugins": {
        "enabled": {
            "postgres": true,
            "database": false
        },
        "installed": {
            "postgres": {
                "source": "https://github.com/user/cody-postgres",
                "version": "v0.3.1",
                "installed_at": "2025-05-21T10:30:00Z"
            }
        }
    }
}
```

This makes plugins visible in the ConfigPanel and allows toggling them
on/off without deleting files.  Setting ``"database": false`` disables
the bundled database plugin.

### Slash command

The ``/plugin`` slash command provides the user-facing interface:

```
/plugin install <url>                  Install from git (latest tag, global)
/plugin install <url> --version X      Install a specific tag
/plugin install <url> --local          Install to project-local tier
/plugin install <url> --subdir D       Use a subdirectory from a monorepo
/plugin update <name>                  Update to latest tag
/plugin update <name> --version X     Update to a specific tag
/plugin update --all                   Update all managed plugins
/plugin remove <name>                  Remove global plugin
/plugin remove <name> --local          Remove project-local plugin
/plugin list                            List all discovered plugins
```

### Install flow

1. Query the repo for tags (``git ls-remote --tags``)
2. Find the latest semver tag (or use ``--version``)
3. Clone shallow (``git clone --depth 1 --branch <tag>``)
4. If ``--subdir`` specified, use that subdirectory
5. Read ``SKILL.md`` to get the plugin name and requirements
6. Remove the ``.git/`` directory
7. Move to the target tier directory (``~/.agents/plugins/<name>/`` or
   ``{wd}/.agents/plugins/<name>/``)
8. Install Python dependencies via ``uv pip install`` (or ``pip install``)
   if the SKILL.md declares ``requirements``
9. Write ``.plugin.json`` metadata (includes requirements list)
10. Update config (``plugins.installed`` + ``plugins.enabled``)

### Update flow

1. Read ``.plugin.json`` for source URL and current version
2. Check for newer tags via ``git ls-remote``
3. If newer version available, repeat the install flow
4. Replace the entire plugin directory with the new version

### PluginInfo data

The ``list_plugins()`` method returns a list of ``PluginInfo`` objects:

| Field | Type | Description |
|---|---|---|
| ``name`` | ``str`` | Plugin name from SKILL.md |
| ``description`` | ``str`` | Description from SKILL.md |
| ``location`` | ``str`` | Absolute path to plugin directory |
| ``version`` | ``str \| None`` | Installed version (from .plugin.json) |
| ``source`` | ``str \| None`` | Git URL (from .plugin.json) |
| ``installed_at`` | ``str \| None`` | ISO-8601 timestamp |
| ``tier`` | ``str`` | "bundled", "global", or "project" |
| ``enabled`` | ``bool`` | Whether enabled in config |
| ``managed`` | ``bool`` | Has .plugin.json (installable/updateable) |
| ``requirements`` | ``list[str]`` | Python packages from SKILL.md frontmatter |