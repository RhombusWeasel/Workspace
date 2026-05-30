# Bootstrap Sequence

**File:** `bootstrap.py`
**Depends on:** All core modules, AppContext

---

## Purpose

The `Bootstrap` class wires together all core services in a single
deterministic sequence and returns a fully initialized `AppContext`.
Called once at application startup.

---

## Bootstrap Phases

```python
class Bootstrap:
    def run(self) -> AppContext:
        self._ensure_project_on_path()
        config = self._init_config()
        skills = self._discover_skills(config)
        self._load_tools(skills)
        self._load_commands(skills)
        self._load_skill_components(skills)
        skill_service_factories = self._load_skill_init_files(skills)
        database = self._init_database(config)
        vault = self._init_vault()
        skill_service_factories = self._load_skill_init_files(skills)
        self._init_leader()
        css_paths = self._collect_css()
        ...
```

### Phase 0 — ``sys.path`` guarantee

Adds the Workspace project root to ``sys.path`` so that plugins (which may live
outside the installation directory) can ``from core.config import Config``
regardless of their physical location.

### Config

Loads layered JSON config files from three tiers (bundled → user →
project), feeds in module-level defaults from ``get_registered_defaults()``,
and calls ``apply_defaults()``.

### Skills

Scans the three ``skills/`` directories for ``SKILL.md`` files.  Builds the
enabled skill catalog.

### Tools

Imports every ``.py`` file in ``tools/`` (core) and each enabled skill's
``tools/`` subdirectory.  ``@register_tool()`` decorators fire at import time.

### Commands

Imports every ``.py`` file in ``cmd/`` (core) and each enabled skill's ``cmd/``
subdirectory.  ``@register_command()`` decorators fire at import time.

### Skill components (flat imports)

Imports sidebar panel modules and skill ``components/`` directories
to trigger ``@register_sidebar_tab()`` and ``@register_handler()``
decorators.

### Database

Creates a ``DatabaseManager`` backed by SQLite.  The database path comes
from ``config.database.path`` or defaults to ``{working_dir}/workspace_data.db``.

### Vault

Creates a ``VaultManager`` with the master vault at ``~/.agents/vault.enc``
and working directory for the local vault.

### Skill __init__.py entry points

Discovers and loads skills with ``__init__.py`` from the three
tiers.  Each skill's ``__init__.py`` is imported, which triggers all
side-effect registrations.  Skill factories declared in ``SKILL_SERVICES``
are called with ``(config, vault)`` and the results collected.

Skill loading order:
1. Register a synthetic `skills` package in `sys.modules`
2. For each discovered skill directory with `__init__.py`:
   - Load `__init__.py` via `importlib.util.spec_from_file_location`
   - Set `__path__` and `__package__` for correct sub-import resolution
   - Register in `sys.modules` as `skills.{name}`
   - Catch `ImportError`/`ModuleNotFoundError` — log warning, skip skill
   - Collect `SKILL_SERVICES` if declared
3. CSS is collected by `collect_tcss()` which walks all tiers uniformly

### Leader chords

Registers core leader chords (workspace split/close).  Plugin leader
chords are registered during plugin loading (at plugin load time).

### CSS collection

Collects ``.tcss`` files from all three tiers uniformly (including
skill directories).  These paths are passed to the Textual app.

---

## Final Assembly

After all phases complete, Bootstrap assembles `AppContext`:

```python
# Skill services wired into AppContext

return AppContext(
    config=config,
    skills=skills,
    database=database,
    services=skill_services,  # dynamic skill services
    **known_service_fields,  # e.g. db_connections
    vault=vault,
    leader=leader_registry,
    working_directory=self.wd,
    css_paths=css_paths,
)
```

The `WorkspaceApp` constructor then:
1. Receives this `AppContext`
2. Sets `context.app = self` for handler access to the UI
3. Uses `css_paths` as additional CSS loading paths

---

## Constructor

```python
bootstrap = Bootstrap(
    working_directory="/path/to/project",
    workspace_dir="/opt/workspace",         # defaults to paths.workspace_dir()
    agents_dir="/home/alice/.agents",  # defaults to paths.agents_dir()
)
ctx = bootstrap.run()
```

All parameters are optional — defaults are derived from `core.paths`.

---

## Why This Order Matters

The phase order is deliberate:

- **Config first** — Everything else reads config for defaults.
- **Skills before tools/commands** — The skill catalog determines which
  `tools/` and `cmd/` directories to scan.
- **Skills loaded before services called** — Skill `__init__.py` imports
  happen before database/vault exist, but service factories are called
  after both are initialized.
- **Vault before service factories** — Service factories need access to
  the vault (e.g. DB connection passwords).
- **Skills before leader** — Most leader chords come from skills.
  Core chords are registered after skills so they don't conflict.
- **CSS last** — CSS paths include skill CSS, so skills must be
  loaded first.

---

## Error Isolation

If a skill fails to load (missing dependency, syntax error), the
bootstrap:

1. Catches the `ImportError`/`ModuleNotFoundError`
2. Prints a warning to stderr
3. Removes the broken module from `sys.modules`
4. Continues with the next skill

One broken skill doesn't crash the entire application.  After
installing the missing dependency and restarting, the skill loads
successfully.

---

## Design Decisions

1. **One-shot, not incremental** — Bootstrap runs once and returns.
  No incremental loading or hot-reload.  Adding skills
  requires a restart.

2. **sys.path guarantee before any skills** — Skills import from
  `core/` using fully-qualified paths.  Adding the project root to
  `sys.path` before plugin loading ensures these imports always work,
  regardless of where a plugin directory lives on disk.

3. **Skill services → AppContext fields** — Skills that provide
  services (like `db_connections`) declare them in `SKILL_SERVICES`.
  Bootstrap collects these and injects them into `AppContext.services`.  This
  keeps the context dataclass clean and makes it obvious which plugins
  contribute which services.

4. **Graceful degradation** — Broken skills are skipped with a warning.
  The app continues to start.  This prevents a single broken plugin
  from making the entire app unusable.