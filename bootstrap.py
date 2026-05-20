"""Bootstrap — wires together all core services and returns an AppContext.

Called once at application startup.  Steps through:

1. Load layered config from tiered JSON files.
2. Discover skills (3-tier scan).
3. Load agent tools (core + skill tiers).
4. Initialize SQLite database.
5. Create vault manager (master + optional local vault).
6. Load plugins (sidebar panels, handlers, services).
7. Build leader chord tree (core module chords).
8. Return an :class:`AppContext`.

Git checkpoints and theme/ CSS discovery are deferred to later steps.

Plugin directories can live outside the Cody installation (e.g.
``~/.agents/plugins/`` or ``{project}/.agents/plugins/``).  To ensure
these plugins can import from ``core/``, the Cody project root is added
to ``sys.path`` before any plugins are loaded.
"""

from __future__ import annotations

import os
import sys
import importlib.util
import types
from context import AppContext
from core import paths
from core.config import Config, get_registered_defaults
from core.skills import skill_manager
from core.database import DatabaseManager
from core.leader import leader as leader_registry
from core.vault import VaultManager


class Bootstrap:
    """One-shot boot sequence.  Call ``run()`` to get an :class:`AppContext`."""

    def __init__(
        self,
        working_directory: str | None = None,
        *,
        cody_dir: str | None = None,
        agents_dir: str | None = None,
    ):
        self.wd = working_directory or os.getcwd()
        self._cody_dir = cody_dir or paths.cody_dir()
        self._agents_dir = agents_dir or paths.agents_dir()

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

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

        # Merge plugin-provided services into AppContext fields.
        # Plugins can supply services like ``db_connections`` by declaring
        # them in their ``PLUGIN_SERVICES`` dict.
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

    # ------------------------------------------------------------------
    # Phase 0 — Ensure project root is on sys.path
    # ------------------------------------------------------------------

    def _ensure_project_on_path(self) -> None:
        """Ensure the Cody project root is on ``sys.path``.

        Plugin directories can live outside the installation directory
        (e.g. ``~/.agents/plugins/`` or ``{project}/.agents/plugins/``).
        When plugins are loaded with ``importlib.util.spec_from_file_location``,
        they still need to resolve imports like ``from core.config import Config``.
        Adding the project root guarantees those imports work regardless of the
        plugin's physical location.
        """
        cody_root = self._cody_dir
        if cody_root not in sys.path:
            sys.path.insert(0, cody_root)

    # ------------------------------------------------------------------
    # Phase 1 — Config
    # ------------------------------------------------------------------

    def _init_config(self) -> Config:
        """Load layered config: cody/ → ~/.agents/ → {wd}/.agents/.

        After loading JSON files, applies module-level defaults registered
        via :func:`~core.config.register_defaults` for any keys still missing.
        """
        cfg_paths: list[str] = []

        bundled = os.path.join(self._cody_dir, "config", "config.json")
        if os.path.isfile(bundled):
            cfg_paths.append(bundled)

        user = os.path.join(self._agents_dir, "config", "config.json")
        if os.path.isfile(user):
            cfg_paths.append(user)

        project = os.path.join(self.wd, ".agents", "config", "config.json")
        if os.path.isfile(project):
            cfg_paths.append(project)

        cfg = Config(cfg_paths)
        cfg.defaults(get_registered_defaults())
        cfg.apply_defaults()
        return cfg

    # ------------------------------------------------------------------
    # Phase 2 — Skills
    # ------------------------------------------------------------------

    def _discover_skills(self, config: Config):
        """Scan all tiers for SKILL.md files."""
        tier_paths = [
            os.path.join(self._cody_dir, "skills"),
            os.path.join(self._agents_dir, "skills"),
            os.path.join(self.wd, ".agents", "skills"),
        ]
        enabled = config.get("skills.enabled", {})
        skill_manager.scan(tier_paths, enabled)
        return skill_manager

    # ------------------------------------------------------------------
    # Phase 3 — Tools
    # ------------------------------------------------------------------

    def _load_tools(self, skills) -> None:
        """Import tool modules from core tools/ and skill tools/ directories."""
        # Core tools
        core_tools = os.path.join(self._cody_dir, "tools")
        self._import_modules_from(core_tools)

        # Skill tools
        for tools_dir in skills.get_skill_tools_dirs():
            self._import_modules_from(tools_dir)

    @staticmethod
    def _import_modules_from(dir_path: str) -> None:
        if not os.path.isdir(dir_path):
            return
        try:
            entries = sorted(os.listdir(dir_path))
        except OSError:
            return
        for entry in entries:
            if not entry.endswith(".py") or entry.startswith("_"):
                continue
            mod_path = os.path.join(dir_path, entry)
            mod_name = entry[:-3]
            spec = importlib.util.spec_from_file_location(
                f"cody.tool.{mod_name}", mod_path
            )
            if spec is None or spec.loader is None:
                continue
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

    # ------------------------------------------------------------------
    # Phase 4 — Sidebar panels + skill components
    # ------------------------------------------------------------------

    def _load_sidebar_panels(self, skills) -> None:
        """Import sidebar panel modules to trigger @register_sidebar_tab()."""
        # Core panels
        core_panels = os.path.join(self._cody_dir, "ui", "sidebar", "panels")
        self._import_modules_from(core_panels)

        # Skill components — sidebar panels, event handlers, leader chords, etc.
        for comp_dir in skills.get_skill_components_dirs():
            self._import_modules_from(comp_dir)

    # ------------------------------------------------------------------
    # Phase 4b — Slash commands
    # ------------------------------------------------------------------

    def _load_commands(self, skills) -> None:
        """Load slash commands: core cmd/ directory + skill cmd/ directories.

        Uses ``load_commands_from_paths`` which imports every ``.py`` file
        and triggers ``@register_command()`` decorators at import time.
        """
        from core.commands import load_commands_from_paths

        # Core commands
        core_cmd_dir = os.path.join(self._cody_dir, "cmd")

        # Skill commands — each skill may have a cmd/ subdirectory
        skill_cmd_dirs = skills.get_skill_cmd_dirs()

        load_commands_from_paths([core_cmd_dir] + skill_cmd_dirs)

    # ------------------------------------------------------------------
    # Phase 5 — Database
    # ------------------------------------------------------------------

    def _init_database(self, config: Config) -> DatabaseManager:
        db_path = config.get("database.path") or os.path.join(
            self.wd, "cody_data.db"
        )
        return DatabaseManager(db_path)

    # ------------------------------------------------------------------
    # Phase 6 — Vault
    # ------------------------------------------------------------------

    def _init_vault(self) -> VaultManager:
        """Create a VaultManager with master vault at ~/.agents/vault.enc."""
        master_path = os.path.join(self._agents_dir, "vault.enc")
        return VaultManager(master_path, self.wd)

    # ------------------------------------------------------------------
    # Phase 7 — Plugins
    # ------------------------------------------------------------------

    def _load_plugins(self, config: Config, vault: VaultManager) -> dict:
        """Discover, import, and initialise plugins.

        Scans the three-tier ``plugins/`` directories for ``SKILL.md``
        manifests.  Each discovered plugin directory is imported via its
        ``__init__.py``, triggering side-effect registrations
        (``@register_sidebar_tab``, ``@register_handler``, config defaults,
        etc.).  Plugins that declare ``PLUGIN_SERVICES`` have their
        factories called with *(config, vault)* and the results collected
        into the returned dict.

        Only the ``__init__.py`` and ``core/`` submodules are imported
        directly; the ``__init__.py`` is responsible for pulling in any
        additional modules that need their decorators to fire at load
        time.  Modules with ``@register_sidebar_tab`` or
        ``@register_handler`` must be imported (directly or indirectly)
        by ``__init__.py``.
        """
        plugin_dirs = paths.discover_plugins(self.wd)
        services: dict = {}

        # Ensure the top-level 'plugins' package is registered in
        # sys.modules so that subpackage imports (plugins.database.core)
        # resolve correctly.
        if "plugins" not in sys.modules:
            plugins_init = os.path.join(self._cody_dir, "plugins", "__init__.py")
            if os.path.isfile(plugins_init):
                spec = importlib.util.spec_from_file_location(
                    "plugins", plugins_init
                )
                if spec is not None and spec.loader is not None:
                    pkg = importlib.util.module_from_spec(spec)
                    pkg.__path__ = [os.path.join(self._cody_dir, "plugins")]
                    pkg.__package__ = "plugins"
                    sys.modules["plugins"] = pkg
                    spec.loader.exec_module(pkg)
            else:
                # Synthetic package — plugins/__init__.py may not exist yet.
                synthetic = types.ModuleType("plugins")
                synthetic.__path__ = [os.path.join(self._cody_dir, "plugins")]
                synthetic.__package__ = "plugins"
                sys.modules["plugins"] = synthetic

        for plugin_dir in plugin_dirs:
            # Import the plugin's __init__.py — this triggers all
            # side-effect registrations (@register_sidebar_tab,
            # @register_handler, config defaults, etc.).
            init_path = os.path.join(plugin_dir, "__init__.py")
            if not os.path.isfile(init_path):
                continue

            mod_name = os.path.basename(plugin_dir)
            fq_name = f"plugins.{mod_name}"
            spec = importlib.util.spec_from_file_location(
                fq_name, init_path
            )
            if spec is None or spec.loader is None:
                continue
            module = importlib.util.module_from_spec(spec)
            # Set __path__ and __package__ so that sub-imports like
            # ``from plugins.database.db_panel import ...`` resolve correctly
            # regardless of which tier the plugin directory lives in.
            module.__path__ = [plugin_dir]
            module.__package__ = fq_name
            # Register in sys.modules so @dataclass and other
            # module-name-dependent features work correctly.
            sys.modules[fq_name] = module

            # Load the plugin, catching import errors so a single
            # broken plugin (e.g. missing dependency) doesn't crash
            # the entire application.
            try:
                spec.loader.exec_module(module)
            except (ImportError, ModuleNotFoundError) as exc:
                # Remove the broken module from sys.modules so a later
                # retry (e.g. after installing deps) doesn't hit a stale
                # entry.
                sys.modules.pop(fq_name, None)
                print(
                    f"Warning: skipping plugin {mod_name!r}: {exc}",
                    file=sys.stderr,
                )
                continue

            # Collect services declared by the plugin.
            plugin_services = getattr(module, "PLUGIN_SERVICES", None)
            if isinstance(plugin_services, dict):
                for service_name, factory in plugin_services.items():
                    services[service_name] = factory(config, vault)

        return services

    # ------------------------------------------------------------------
    # Phase 8 — Leader chords
    # ------------------------------------------------------------------

    def _init_leader(self) -> None:
        """Register core leader chords from workspace, etc."""
        from ui.workspace.workspace import register_workspace_leader_chords

        register_workspace_leader_chords()
        # Terminal leader chords are now registered by the terminal plugin
        # at load time (plugins/terminal/__init__.py).

    # ------------------------------------------------------------------
    # Phase 9 — CSS
    # ------------------------------------------------------------------

    def _collect_css(self) -> list[str]:
        """Collect all .tcss files across the three tiers and plugins."""
        css_paths = paths.collect_tcss(self.wd)
        css_paths.extend(paths.collect_plugin_tcss(self.wd))
        return css_paths