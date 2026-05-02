# Step 13: Bootstrap + AppContext

**Branch:** `step-13-bootstrap`  
**Date:** 2026-05-02

---

## Overview

One-shot boot sequence that wires together all core services and returns an
`AppContext` — a service locator holding references to config, skills,
database, and leader registry.

Called once at application startup. Git checkpoints, themes, and CSS
discovery are deferred to later steps.

---

## Implementation

### `bootstrap.py`

#### `Bootstrap` class

```python
class Bootstrap:
    def __init__(self, working_directory, *, cody_dir=None, agents_dir=None)
    def run() -> AppContext
```

The `cody_dir` and `agents_dir` parameters are optional — when omitted,
they default to `paths.cody_dir()` and `paths.agents_dir()` respectively.
This allows tests to override tier paths.

#### Boot sequence

```
Phase 1 — _init_config()
    Load layered JSON config files:
      1. {cody_dir}/config/config.json  (bundled)
      2. {agents_dir}/config/config.json (user)
      3. {wd}/.agents/config/config.json (project)
    Returns a Config instance.

Phase 2 — _discover_skills(config)
    Scan three tiers for SKILL.md files:
      1. {cody_dir}/skills/
      2. {agents_dir}/skills/
      3. {wd}/.agents/skills/
    Passes config.get("skills.enabled") to skill_manager.scan().
    Returns the module-level skill_manager singleton.

Phase 3 — _load_tools(skills)
    Import tool modules to trigger @register_tool() decorators:
      1. {cody_dir}/tools/*.py
      2. Each skill's tools/*.py (via skills.get_skill_tools_dirs())
    Uses importlib.util for dynamic imports (matching commands.py pattern).

Phase 4 — _init_database(config)
    Reads config.get("database.path"), falls back to {wd}/cody_data.db.
    Creates a DatabaseManager (SQLiteProvider via WAL mode).
    Returns the DatabaseManager instance.

Phase 5 — _init_leader()
    Calls register_workspace_leader_chords() to register workspace
    leader chords (Ctrl+Space w s h/v/c, w c).
    Later: will call equivalent for chat and terminal modules.
```

#### Returned `AppContext`

```python
AppContext(
    config=config,           # Config instance
    skills=skill_manager,    # module-level singleton
    database=database,       # DatabaseManager instance
    leader=leader_registry,  # module-level singleton
    working_directory=wd,
)
```

---

### `context.py`

Unchanged from its earlier creation — the `AppContext` dataclass with five
fields. Used as a service locator (not a DI container) per the design doc.

```python
@dataclass
class AppContext:
    config: Config | None = None
    skills: SkillManager | None = None
    database: DatabaseManager | None = None
    leader: LeaderRegistry | None = None
    working_directory: str = ""
```

---

## Tests

### `tests/test_bootstrap.py` — 1 test

The single integration test creates a complete mock filesystem with:
- **Config files** in cody + project tiers (project overrides cody)
- **Skills** (coding skill with tools)
- **Tool files** (core echo tool + skill code_review tool)

Then runs `Bootstrap(...).run()` and verifies:
- Returned `AppContext` has all five fields populated
- Config has correct layered values (project overrides cody)
- Skills are discovered and enabled
- Tools are registered and discoverable via `get_tools()`
- Database has all expected tables
- Leader registry has workspace chords
- Working directory is set correctly

Uses `_reset_registries` autouse fixture to clear tools, commands, skills,
and leader state before the test.

---

## Design Decisions

1. **Bootstrap constructs tier paths directly** rather than calling
   `paths.resolve()`. This allows tests to supply mock tier directories
   without leaking real `~/.agents/` content into test results.

2. **`run()` returns just the `AppContext`** — no CSS list, no themes.
   Those are deferred. The bootstrap is lean and focused on the core
   service graph.

3. **Skill manager and leader registry are singletons.** Bootstrap
   populates them via their module-level instances. `AppContext` holds
   references to the same instances for query access. This keeps the
   `@register_tool()` / `@register_command()` decorator patterns intact
   (see § 6.1, § 6.3).

4. **No git or themes in this step.** Git checkpointing and theme
   discovery are separate concerns that can be added later without
   changing the bootstrap flow.

5. **Database path from config.** Falls back to `{wd}/cody_data.db` if
   not configured. The DatabaseManager handles table creation and WAL
   mode automatically.

---

## Usage Pattern

```python
from bootstrap import Bootstrap

# Production
bootstrap = Bootstrap(working_directory="/path/to/project")
context = bootstrap.run()

# Access services anywhere
config = context.config
db = context.database
skills = context.skills
leader = context.leader

# Pass AppContext through to UI components
app = TuiApp(context)
app.run()
```

```python
# Testing — override tier paths
from bootstrap import Bootstrap

b = Bootstrap(
    working_directory="/tmp/test_wd",
    cody_dir="/tmp/mock_cody",
    agents_dir="/tmp/mock_agents",
)
ctx = b.run()
```
