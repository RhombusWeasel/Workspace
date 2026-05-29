# Skill Loading System

**Files:** `core/skills.py` (discovery), `bootstrap.py` (loading), `skills/` (bundled skills)

---

## Purpose

Skills are Cody's sole extension mechanism.  They provide agent knowledge,
sidebar panels, event handlers, tools, and application-level services — all
without modifying the core codebase.  Skills are discovered via a 3-tier
directory scan and loaded dynamically at startup.

---

## How Discovery Works

`core/paths.resolve(subpath, working_dir)` returns three directories in
order of increasing precedence:

| Tier | Path | Scope |
|---|---|---|
| 1 — Bundled | `{cody_dir}/skills/` | Ships with Cody |
| 2 — User | `~/.agents/skills/` | Global per-user skills |
| 3 — Project | `{working_dir}/.agents/skills/` | Per-project skills |

`SkillManager.scan(tier_paths, enabled)` scans each tier for
subdirectories containing a `SKILL.md` manifest.  When two tiers have a
skill with the same directory name, the **later tier wins** — a
project-level skill overrides a user-level skill, which overrides a
bundled skill.

```python
# Example: scan discovers skills across three tiers
skill_manager.scan([
    "/opt/cody/skills",
    "/home/alice/.agents/skills",
    "/project/.agents/skills",
])
```

---

## Skill Directory Structure

### Minimal skill (no Python code)

```
skills/my_skill/
├── SKILL.md              # Required — manifest (name + description)
└── scripts/               # Optional — run via run_skill tool
    └── deploy.py
```

### UI skill (with `__init__.py`)

```
skills/my_skill/
├── SKILL.md              # Required — manifest (name + description)
├── __init__.py            # Required — entry point for registrations
├── core/                  # Optional — skill internals
│   ├── __init__.py
│   └── connections.py
├── my_skill.tcss         # Optional — skill CSS (Textual)
├── handlers.py            # Optional — event handlers
├── tools.py               # Optional — agent-callable tools
└── services.py            # Optional — SKILL_SERVICES factory
```

### SKILL.md

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
```

The `name` and `description` fields are **required**.  The `requirements`
field is optional — a YAML list of Python package specifiers (in `pip`
format) that the skill needs.  When the skill package manager installs a
skill, it runs `uv pip install` (falling back to `pip install`) to
install these dependencies into the project's virtual environment.

Skills without `requirements` (or with an empty list) are assumed to
only need packages already in the Cody environment.

### `__init__.py` (Optional Entry Point)

`__init__.py` is optional.  It determines how the skill is loaded:

- **Without `__init__.py`**: The skill is discovered and its SKILL.md body
  is available to the agent.  Flat subdirectories (`components/`, `tools/`,
  `cmd/`) are auto-imported.  This is compatible with the Anthropic skill
  specification.

- **With `__init__.py`**: The skill gets full `importlib` package loading
  with correct `__path__`/`__package__` handling.  This is needed for
  skills with nested sub-packages.

When present, `__init__.py` should import and trigger any modules that
register sidebar tabs, event handlers, tools, or config defaults:

```python
# skills/my_skill/__init__.py
"""My Skill — does something useful."""

# Side-effect imports trigger decorator registrations.
from skills.my_skill.handlers import register_handlers  # noqa: F401
from skills.my_skill.services import SKILL_SERVICES      # noqa: F401

__all__ = ["SKILL_SERVICES"]
```

**Important:** modules containing `@register_handler`, `@register_sidebar_tab`,
or `@register_tool` decorators must be imported (directly or transitively)
by `__init__.py` — or live in auto-discovered subdirectories
(`components/`, `tools/`, `cmd/`) — otherwise the decorators never execute.

---

## How Skills Are Loaded

The bootstrap sequence in `Bootstrap._load_skill_init_files()`:

1. **`sys.path` guarantee** — The Cody project root is added to `sys.path`
   so skills can import from `core/` regardless of where the skill
   directory lives on disk.

2. **Package namespace setup** — A synthetic `skills` package is registered
   in `sys.modules` with its `__path__` pointing to `{cody_dir}/skills/`.
   This enables absolute imports like `from skills.my_skill.core import X`.

3. **Flat component loading** — Skills with `components/`, `tools/`, and
   `cmd/` directories get their files imported as flat modules.  This
   triggers `@register_*` decorators in those files.

4. **Per-skill `__init__.py` loading** — For each discovered skill with
   `__init__.py`:
   - The `__init__.py` is loaded via
     `importlib.util.spec_from_file_location`.
   - `__path__` is set to `[skill_dir]` so that sub-imports resolve from
     the skill's own directory (even if it lives in `~/.agents/`).
   - `__package__` is set to `f"skills.{mod_name}"` for correct relative
     import resolution.
   - The module is registered in `sys.modules` under its fully-qualified name.
   - If the module declares a `SKILL_SERVICES` dict, each factory callable
     is collected for later invocation with `(config, vault)`.

5. **CSS collection** — ``paths.collect_tcss()`` gathers all ``.tcss`` files
   across the three tiers, including skill directories.

6. **Requirement installation** — If the SKILL.md declares a `requirements`
   list, `SkillPackageManager.install()` runs `uv pip install` (falling back to
   `pip install`) to install those packages into the project's virtual
   environment.  Since skills run in-process, their dependencies must be
   on `sys.path`.  Requirements are also recorded in `.skill.json`.

7. **Error isolation** — If a skill fails to load (e.g. a required
   package is still missing, or there's an `ImportError`), the bootstrap
   logs a warning to `stderr` and skips that skill.  The application
   continues to start — one broken skill doesn't crash the entire app.
   The failed module is removed from `sys.modules` so a retry after
   installing the missing dependency will work on the next startup.

---

## Import Resolution

Skills can import from Cody's core modules because the project root is on
`sys.path` before any skill is loaded:

```python
# Inside a skill at ~/.agents/skills/my_skill/handlers.py
from core.events import register_handler    # ✅ works
from core.config import Config              # ✅ works
from core.vault import VaultManager         # ✅ works
from context import AppContext              # ✅ works
```

For skills with `__init__.py`, sub-imports resolve from the skill's own
directory because `__path__` is set correctly during loading:

```python
# Inside skills/my_skill/__init__.py
from skills.my_skill.core.connections import ConnectionManager  # ✅ works
```

---

## What Skills Can Register

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

@register_handler("my_skill.action")
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
    "my_skill": {
        "max_items": 100,
        "auto_refresh": True,
    }
})
```

---

## Skill Services (AppContext Extension)

Skills with `__init__.py` that need to provide services to other parts of
the application declare a `SKILL_SERVICES` dict.  Each entry maps a service
name to a factory callable that receives `(config, vault)`:

```python
# skills/my_skill/__init__.py
from skills.my_skill.services import create_connection_manager

SKILL_SERVICES = {
    "my_service": create_connection_manager,
}
```

```python
# skills/my_skill/services.py
from core.config import Config
from core.vault import VaultManager
from skills.my_skill.core.connections import ConnectionManager

def create_connection_manager(config: Config, vault: VaultManager) -> ConnectionManager:
    return ConnectionManager(config, vault)
```

Bootstrap calls each factory and stores the result in `AppContext.services`:

```python
# Access in other components:
ctx.services["my_service"]
# Or for known services:
ctx.db_connections
```

---

## Auto-Discovery Provider Pattern

The database skill demonstrates a self-registering provider pattern that
makes it trivial to add new database backends.  The key insight: providers
live in a ``providers/`` sub-package that auto-discovers ``.py`` files at
import time and registers them via ``@register_provider``.

### How it works

```
skills/database/core/
├── db_connections.py     ← DBProvider ABC, registry, ConnectionManager
└── providers/
    ├── __init__.py      ← Auto-discovers .py files, imports them
    └── sqlite.py        ← @register_provider class SQLiteProvider
```

1. ``db_connections.py`` defines the ``DBProvider`` abstract base class
   and the ``register_provider()`` decorator / registry functions.

2. At the bottom of ``db_connections.py``, it imports the providers
   sub-package::

       from skills.database.core.providers import *  # noqa: F401,F403,E402

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
# skills/database/core/providers/postgres.py
from typing import Any
from skills.database.core.db_connections import (
    DBProvider, FormField, ColumnInfo, TableInfo,
    ViewInfo, TriggerInfo, QueryResult, register_provider,
)

@register_provider
class PostgreSQLProvider(DBProvider):

    @classmethod
    def provider_type(cls) -> str:
        return "postgres"

    # ... (implement all other DBProvider methods)
```

No other changes needed — the connection form will automatically show
the new provider type in its dropdown, and ``ConnectionManager`` will
route to it when a connection uses ``provider_type: "postgres"``.

### Pattern for other skills

The same auto-discovery pattern works for any skill that wants
extensible backends:

1. Define an ABC and a decorator registry in your core module.
2. Create a ``providers/`` (or ``backends/``, ``handlers/``, etc.) sub-package.
3. Write an ``__init__.py`` that auto-imports all ``.py`` files.
4. Import the sub-package at the bottom of your core module.
5. Each provider self-registers via the decorator at import time.

---

## 3-Tier Overriding

When the same skill name exists in multiple tiers, the later tier wins:

```
/opt/cody/skills/database/      ← bundled (tier 1)
~/.agents/skills/database/      ← user override (tier 2) ✅ WINS
```

This lets users override bundled skills with their own versions.  To
**disable** a bundled skill entirely, set `"database": false` in config
under `skills.enabled`.

---

## Skill Package Manager

Cody includes a skill package manager (``core/skill_package_manager.py``)
that handles installing, updating, removing, and listing skills from git
repositories.  Skills are always installed from a **tagged release** —
never from a live branch.  After cloning, the ``.git/`` directory is
stripped so installed skills are just source files with no nested git repo.

### Install metadata: ``.skill.json``

Every skill installed via the manager gets a ``.skill.json`` file in its
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
it came from, and what dependencies it needs".  Skills without
``.skill.json`` are either bundled or manually created — they still work
fine, they just can't be updated via the ``/skill update`` command.

The ``requirements`` field is populated from the ``requirements:`` list in
the skill's SKILL.md.  It's stored here for reference and for any future
``/skill deps`` command that re-installs dependencies.

### Config integration

Install metadata is mirrored to the layered config under ``skills.installed``,
and enable/disable state is tracked under ``skills.enabled``:

```json
// ~/.agents/config/config.json
{
    "skills": {
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

This makes skills visible in the ConfigPanel and allows toggling them
on/off without deleting files.  Setting ``"database": false`` disables
the bundled database skill.

### Slash command

The ``/skill`` slash command provides the user-facing interface:

```
/skill install <url>                  Install from git (latest tag, global)
/skill install <url> --version X      Install a specific tag
/skill install <url> --local          Install to project-local tier
/skill install <url> --subdir D       Use a subdirectory from a monorepo
/skill update <name>                  Update to latest tag
/skill update <name> --version X     Update to a specific tag
/skill update --all                   Update all managed skills
/skill remove <name>                  Remove global skill
/skill remove <name> --local          Remove project-local skill
/skill list                            List all discovered skills
```

### Install flow

1. Query the repo for tags (``git ls-remote --tags``)
2. Find the latest semver tag (or use ``--version``)
3. Clone shallow (``git clone --depth 1 --branch <tag>``)
4. If ``--subdir`` specified, use that subdirectory
5. Read ``SKILL.md`` to get the skill name and requirements
6. Remove the ``.git/`` directory
7. Move to the target tier directory (``~/.agents/skills/<name>/`` or
   ``{wd}/.agents/skills/<name>/``)
8. Install Python dependencies via ``uv pip install`` (or ``pip install``)
   if the SKILL.md declares ``requirements``
9. Write ``.skill.json`` metadata (includes requirements list)
10. Update config (``skills.installed`` + ``skills.enabled``)

### SkillInfo data

The ``list_skills()`` method returns a list of ``SkillInfo`` objects:

| Field | Type | Description |
|---|---|---|
| ``name`` | ``str`` | Skill name from SKILL.md |
| ``description`` | ``str`` | Description from SKILL.md |
| ``location`` | ``str`` | Absolute path to skill directory |
| ``version`` | ``str \| None`` | Installed version (from .skill.json) |
| ``source`` | ``str \| None`` | Git URL (from .skill.json) |
| ``installed_at`` | ``str \| None`` | ISO-8601 timestamp |
| ``tier`` | ``str`` | "bundled", "global", or "project" |
| ``enabled`` | ``bool`` | Whether enabled in config |
| ``managed`` | ``bool`` | Has .skill.json (installable/updateable) |
| ``requirements`` | ``list[str]`` | Python packages from SKILL.md frontmatter |

---

## Architecture Diagram

```
Bootstrap._load_skill_init_files()
    │
    ├── _ensure_project_on_path()        ← adds cody_dir to sys.path
    │
    ├── Register synthetic 'skills'     ← sys.modules["skills"] + __path__
    │   package in sys.modules
    │
    └── For each discovered skill dir with __init__.py:
        │
        ├── spec_from_file_location()    ← loads __init__.py
        │
        ├── Set __path__ = [skill_dir]   ← sub-imports resolve here
        ├── Set __package__ = "skills.name"
        │
        ├── spec.loader.exec_module()   ← triggers @register_* decorators
        │
        └── Collect SKILL_SERVICES       ← factories called with (config, vault)
```

---

## Design Decisions

1. **Unified skill concept** — Skills are the sole extension mechanism.
   The former separate "plugins" concept has been merged.  A skill with
   `__init__.py` gets the same loading treatment; a skill without it is
   compatible with the Anthropic skill specification.

2. **Decorator self-registration** — `@register_sidebar_tab`,
   `@register_handler`, `@register_tool`, and `@register_command` all
   self-register at import time.  Skill authors just write decorators;
   no manual wiring needed.

3. **sys.path guarantee** — The Cody project root is explicitly added to
   `sys.path` before skills load.  This means skills can import from
   `core/` regardless of where the skill directory lives on disk.

4. **__path__ and __package__ for each skill** — Without setting these,
   `importlib.util.spec_from_file_location` creates modules whose
   sub-imports break when the skill lives outside the Cody installation
   directory.  Explicitly setting them ensures `from skills.my_skill.core`
   resolves from the correct directory.

5. **SKILL_SERVICES for AppContext extension** — Rather than having skills
   mutate `AppContext` directly, they declare service factories that bootstrap
   calls and injects.  This keeps the context dataclass clean and makes it
   obvious which skills contribute which services.

6. **Later tier overrides earlier** — Same as config: a project-level
   skill at `{wd}/.agents/skills/my_skill/` silently replaces a user-level
   or bundled skill with the same name.

7. **Dependencies install into the project venv** — Since skills run
   in-process, their Python dependencies must be on `sys.path`.  The
   skill package manager installs `requirements:` from SKILL.md directly
   into Cody's virtual environment using `uv pip install` (or `pip install`
   as fallback).

8. **Graceful degradation on import failure** — If a skill can't be
   loaded (missing dependency, import error, syntax error), the bootstrap
   catches the exception, prints a warning to stderr, and skips that
   skill.  The application continues to start.