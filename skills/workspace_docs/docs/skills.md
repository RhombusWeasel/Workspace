# Skills System

**Files:** `core/skills.py` (discovery), `core/paths.py` (tier resolution), `bootstrap.py` (loading), `core/skill_package_manager.py` (install/update/remove)
**Depends on:** `os`, `importlib`, `sys`

---

## Purpose

Skills are the sole extension mechanism in Workspace. A skill is a directory containing a `SKILL.md` manifest — a format compatible with the Anthropic skill specification (ClaudeCode, Codex). Skills provide:

- **Agent knowledge** — markdown instructions the LLM reads via `activate_skill`
- **UI registrations** — sidebar panels, event handlers, leader chords
- **Agent tools** — Python functions the LLM can invoke
- **Slash commands** — `/command` entries the user can type
- **AppContext services** — service factories wired into the app context

---

## Discovery & 3-Tier Overriding

`core/paths.resolve(subpath, working_dir)` returns three directories in order of increasing precedence:

| Tier | Path | Scope |
|---|---|---|
| 1 — Bundled | `{workspace_dir}/skills/` | Ships with Workspace |
| 2 — User | `~/.agents/skills/` | Global per-user skills |
| 3 — Project | `{working_dir}/.agents/skills/` | Per-project skills — **wins** |

`SkillManager.scan(tier_paths, enabled)` scans each tier for subdirectories containing a `SKILL.md` manifest. When two tiers have a skill with the same name, the **later tier wins**. To disable a skill entirely, set `"skill_name": false` in config under `skills.enabled`.

---

## SKILL.md Format

```markdown
---
name: my_skill
description: Short description shown in catalog
requirements:
  - requests>=2.28
  - psycopg2-binary>=2.9
---

# My Skill

Detailed markdown instructions that the LLM reads when the skill
is activated.  This body is returned by the `activate_skill` tool.
```

YAML frontmatter requires `name` and `description`. The body after `---` is the skill's documentation. Optional fields:

| Field | Description |
|---|---|
| `requirements` | YAML list of pip-format package specifiers (installed via `uv pip install` when using `/skill install`) |

---

## Skill Profiles

### Ecosystem skill (Anthropic spec)

No `__init__.py`. Just SKILL.md + optional `scripts/`. Compatible with any tool that follows the Anthropic skill specification.

```
my_skill/
├── SKILL.md
└── scripts/
    └── deploy.py
```

### UI skill

Has `__init__.py`. Gets full `importlib` load with `__path__`/`__package__` handling for nested sub-packages.

```
my_skill/
├── SKILL.md
├── __init__.py
├── core/
│   ├── __init__.py
│   └── connections.py
├── services.py          # SKILL_SERVICES factory
└── my_skill.tcss
```

### Hybrid skill

Has agent knowledge (SKILL.md body) plus flat UI components. Uses `components/` directory for sidebar panels, handlers, etc. No `__init__.py` needed.

```
my_skill/
├── SKILL.md              # Body = agent knowledge
├── scripts/               # Agent-runnable scripts
├── components/
│   └── panel.py           # @register_sidebar_tab, @register_handler
├── tools/
│   └── my_tool.py         # @register_tool
└── my_skill.tcss
```

---

## The `__init__.py` Gate

`__init__.py` is **optional**. Its presence determines loading:

| Has `__init__.py`? | Loading | Used for |
|---|---|---|
| ❌ | Discovery only — SKILL.md body available to agent, scripts runnable | Ecosystem/pure knowledge skills |
| ✅ | Full `importlib` load — `__path__`/`__package__` set, nested sub-imports work | UI skills with complex packages |

Skills without `__init__.py` can still have Python code in `components/`, `tools/`, and `cmd/` — those are auto-imported as flat files by the bootstrap loader.

---

## Loading Process

Bootstrap loads skills in `Bootstrap._load_skill_init_files()`:

1. **`sys.path` guarantee** — Project root added to `sys.path` so skills can `from core.config import Config`.
2. **Package namespace setup** — A synthetic `skills` package is registered in `sys.modules` with `__path__` pointing to `{workspace_dir}/skills/`. Enables absolute imports like `from skills.my_skill.core import X`.
3. **Flat component loading** — Skills with `components/`, `tools/`, and `cmd/` directories get their files imported as flat modules, triggering `@register_*` decorators.
4. **Per-skill `__init__.py` loading** — For each discovered skill with `__init__.py`:
   - Loaded via `importlib.util.spec_from_file_location`
   - `__path__` set to `[skill_dir]` so sub-imports resolve from the skill's own directory
   - `__package__` set to `f"skills.{mod_name}"` for correct relative import resolution
   - Module registered in `sys.modules` under its fully-qualified name
   - If the module declares `SKILL_SERVICES`, each factory callable is collected for later invocation with `(config, vault)`
5. **CSS collection** — `paths.collect_tcss()` gathers all `.tcss` files across all tiers.
6. **Requirement installation** — If SKILL.md declares `requirements`, `SkillPackageManager.install()` runs `uv pip install` (fallback: `pip install`). Dependencies must be on `sys.path` since skills run in-process.
7. **Error isolation** — Failed skills are skipped with a warning to stderr. The application continues. The broken module is removed from `sys.modules`.

**Import resolution:** Skills can import from `core/` because the project root is on `sys.path`:
```python
from core.events import register_handler    # ✅ works
from core.config import Config              # ✅ works
from context import AppContext              # ✅ works
```

Skills with `__init__.py` can also do sub-imports:
```python
from skills.my_skill.core.connections import ConnectionManager  # ✅ works
```

**Golden rule:** Modules with `@register_handler`, `@register_tool`, `@register_sidebar_tab`, or `@register_command` must be imported by `__init__.py` or live in an auto-discovered directory (`components/`, `tools/`, `cmd/`).

---

## SkillManager API

```python
mgr = SkillManager()
mgr.scan(tier_paths, enabled_map)
```

| Method | Returns | Description |
|---|---|---|
| `scan(tier_paths, enabled=None)` | — | Rebuild catalog from tier paths |
| `list_skills()` | `list[str]` | Sorted enabled skill names |
| `get_skill(name)` | `Skill \| None` | Skill by name (even if disabled) |
| `get_skill_body(name)` | `str \| None` | Markdown body (even if disabled) |
| `get_skill_dirs()` | `list[tuple[str, str]]` | `(name, base_dir)` for enabled skills |
| `get_skill_init_dirs()` | `list[str]` | Base dirs with `__init__.py` |
| `get_skill_cmd_dirs()` | `list[str]` | Paths to enabled `cmd/` subdirectories |
| `get_skill_tools_dirs()` | `list[str]` | Paths to enabled `tools/` subdirectories |
| `get_skill_components_dirs()` | `list[str]` | Paths to enabled `components/` subdirectories |
| `get_skill_services()` | `dict` | Collected `SKILL_SERVICES` from loaded modules |
| `set_skill_services(services)` | — | Store service factories |
| `get_catalog_xml()` | `str` | Bare XML listing enabled skills |
| `render_selected(skill_names)` | `str` | XML catalog in code fences for system prompts |
| `reset()` | — | Clear all skills (for tests) |

### Skill Data Class

```python
@dataclass
class Skill:
    name: str           # From SKILL.md frontmatter
    description: str    # From SKILL.md frontmatter
    location: str        # Absolute path to SKILL.md
    base_dir: str        # Directory containing SKILL.md
    body: str = ""       # Markdown content after frontmatter
```

---

## SKILL_SERVICES Convention

Skills with `__init__.py` may declare a `SKILL_SERVICES` dict mapping service names to factory callables. Bootstrap calls each factory with `(config, vault)`:

```python
# skills/my_skill/__init__.py
from skills.my_skill.services import create_my_service

SKILL_SERVICES = {
    "my_service": create_my_service,
}
```

Other components access via `ctx.services["my_service"]` or, for known services like `db_connections`, via `ctx.db_connections`.

---

## Auto-Discovery Provider Pattern

For skills that support multiple backends (e.g. different database types):

1. Define an ABC and `@register_provider` decorator in your core module
2. Create a `providers/` sub-package that auto-imports all `.py` files
3. Each provider self-registers via the decorator at import time

```
skills/database/core/
├── db_connections.py     ← DBProvider ABC, registry
└── providers/
    ├── __init__.py      ← Auto-discovers .py files, imports them
    └── sqlite.py        ← @register_provider class SQLiteProvider
```

No other changes needed — the connection form automatically shows new provider types, and `ConnectionManager` routes to them.

---

## Skill Package Manager

`core/skill_package_manager.py` handles installing, updating, removing, and listing skills from git repositories. Skills are always installed from a **tagged release** — never from a live branch.

### `.skill.json` metadata

Every installed skill gets a `.skill.json`:
```json
{
    "source": "https://github.com/user/workspace-postgres",
    "version": "v0.3.1",
    "installed_at": "2025-05-21T10:30:00Z",
    "requirements": ["psycopg2-binary>=2.9", "requests>=2.28"]
}
```

### Slash command

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

---

## Creating a Skill

### 1. Create the directory
```bash
mkdir -p ~/.agents/skills/my_skill
```

### 2. Write SKILL.md
```bash
cat > ~/.agents/skills/my_skill/SKILL.md << 'EOF'
---
name: my_skill
description: Instructions for doing X with the project
---

# My Skill

Detailed instructions the LLM should follow when this skill is activated.
EOF
```

### 3. (Optional) Add `__init__.py` for UI skills
```python
# skills/my_skill/__init__.py
from skills.my_skill.handlers import register_handlers  # noqa: F401
from skills.my_skill.services import SKILL_SERVICES       # noqa: F401
__all__ = ["SKILL_SERVICES"]
```

### 4. (Optional) Add tools, commands, or components

| Directory | Auto-discovered? | What it registers |
|---|---|---|
| `tools/` | Yes | `@register_tool()` |
| `cmd/` | Yes | `@register_command()` |
| `components/` | Yes | `@register_sidebar_tab()`, `@register_handler()`, etc. |

### 5. (Optional) Add CSS

Create a `.tcss` file in the skill directory — auto-collected by `collect_tcss()`.

### 6. Restart Workspace

Skills are discovered at startup. Restart to pick up new skills.

---

## Design Decisions

1. **Unified skill concept** — Skills are the sole extension mechanism. The former "plugins" concept has been merged. A skill with `__init__.py` gets full loading treatment; without it, works as an ecosystem-compatible knowledge bundle.
2. **Decorator self-registration** — `@register_sidebar_tab`, `@register_handler`, `@register_tool`, and `@register_command` all self-register at import time. No manual wiring needed.
3. **Explicit scan, no auto-reload** — `scan()` is called once at bootstrap. Adding a skill requires a restart.
4. **XML catalog for LLM** — The catalog XML is injected into the agent's system prompt so the LLM knows which skills exist.
5. **Later tier overrides earlier** — Same as config: project-level overrides user-level overrides bundled.
6. **Graceful degradation on import failure** — Broken skills are skipped with a warning. The application continues.
7. **Dependencies install into project venv** — Since skills run in-process, their Python dependencies must be on `sys.path`. `uv pip install` (fallback: `pip install`) installs `requirements:` from SKILL.md.