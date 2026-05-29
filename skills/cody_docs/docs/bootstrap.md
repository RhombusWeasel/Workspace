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
        self._load_sidebar_panels(skills)
        database = self._init_database(config)
        vault = self._init_vault()
        plugin_services = self._load_plugins(config, vault)
        self._init_leader()
        css_paths = self._collect_css()
        ...
```

### Phase 0 — ``sys.path`` guarantee

Adds the Cody project root to ``sys.path`` so that plugins (which may live
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

### Sidebar panels

Imports sidebar panel modules to trigger ``@register_sidebar_tab()``
decorators.  Also imports skill ``components/`` directories, which can
contain sidebar panels, event handlers, leader chords, and config
defaults using the same decorator pattern as plugins.

### Database

Creates a ``DatabaseManager`` backed by SQLite.  The database path comes
from ``config.database.path`` or defaults to ``{working_dir}/cody_data.db``.

### Vault

Creates a ``VaultManager`` with the master vault at ``~/.agents/vault.enc``
and working directory for the local vault.

### Plugins

Discovers and loads plugins from the three ``plugins/`` tiers.  Each
plugin's ``__init__.py`` is imported, which triggers all side-effect
registrations.  Plugin factories declared in ``PLUGIN_SERVICES`` are
called with ``(config, vault)`` and the results collected.

Plugin loading order:
1. Register a synthetic `plugins` package in `sys.modules`
2. For each discovered plugin directory:
   - Load `__init__.py` via `importlib.util.spec_from_file_location`
   - Set `__path__` and `__package__` for correct sub-import resolution
   - Register in `sys.modules` as `plugins.{name}`
   - Catch `ImportError`/`ModuleNotFoundError` — log warning, skip plugin
   - Collect `PLUGIN_SERVICES` if declared
3. Collect `.tcss` files from all plugin directories

### Leader chords

Registers core leader chords (workspace split/close).  Plugin leader
chords are registered during plugin loading (at plugin load time).

### CSS collection

Collects ``.tcss`` files from all three tiers (core) and all plugin
directories.  These paths are passed to the Textual app for CSS loading.

---

## Final Assembly

After all phases complete, Bootstrap assembles `AppContext`:

```python
db_connections = plugin_services.get("db_connections")

return AppContext(
    config=config,
    skills=skills,
    database=database,
    db_connections=db_connections,
    vault=vault,
    leader=leader_registry,
    working_directory=self.wd,
    css_paths=css_paths,
)
```

The `CodyApp` constructor then:
1. Receives this `AppContext`
2. Sets `context.app = self` for handler access to the UI
3. Uses `css_paths` as additional CSS loading paths

---

## Constructor

```python
bootstrap = Bootstrap(
    working_directory="/path/to/project",
    cody_dir="/opt/cody",         # defaults to paths.cody_dir()
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
- **Database before plugins** — Plugins that need database access
  (via `ctx.database`) require the database to be initialized.
- **Vault before plugins** — Plugins that access secrets (e.g. DB
  connection passwords) need the vault manager.
- **Plugins before leader** — Most leader chords come from plugins.
  Core chords are registered after plugins so they don't conflict.
- **CSS last** — CSS paths include plugin CSS, so plugins must be
  loaded first.

---

## Error Isolation

If a plugin fails to load (missing dependency, syntax error), the
bootstrap:

1. Catches the `ImportError`/`ModuleNotFoundError`
2. Prints a warning to stderr
3. Removes the broken module from `sys.modules`
4. Continues with the next plugin

One broken plugin doesn't crash the entire application.  After
installing the missing dependency and restarting, the plugin loads
successfully.

---

## Design Decisions

1. **One-shot, not incremental** — Bootstrap runs once and returns.
  No incremental loading or hot-reload.  Adding plugins or skills
  requires a restart.

2. **sys.path guarantee before any plugins** — Plugins import from
  `core/` using fully-qualified paths.  Adding the project root to
  `sys.path` before plugin loading ensures these imports always work,
  regardless of where a plugin directory lives on disk.

3. **Plugin services → AppContext fields** — Plugins that provide
  services (like `db_connections`) declare them in `PLUGIN_SERVICES`.
  Bootstrap collects these and injects them into `AppContext`.  This
  keeps the context dataclass clean and makes it obvious which plugins
  contribute which services.

4. **Graceful degradation** — Broken plugins are skipped with a warning.
  The app continues to start.  This prevents a single broken plugin
  from making the entire app unusable.