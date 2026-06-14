"""Bootstrap — wires together all core services and returns an AppContext.

Called once at application startup.  Steps through:

1. Load layered config from tiered JSON files.
2. Discover skills (3-tier scan).
3. Load agent tools (core + skill tiers).
4. Load slash commands (core + skill tiers).
5. Load skill components (flat imports for sidebar panels, handlers).
6. Load skill __init__.py entry points (full package load for UI skills).
7. Initialize SQLite database.
8. Create vault manager (master + optional local vault).
9. Create provider registry and register provider types.
10. Create agent manager (system prompt templates + agent definitions).
11. Build leader chord tree (core module chords).
12. Collect CSS paths.
13. Return an :class:`AppContext`.

Skills are the unified extension mechanism.  A skill is a directory with
a ``SKILL.md`` manifest.  Skills with ``__init__.py`` are loaded with full
``importlib`` treatment (``__path__``/``__package__`` handling) so that
nested sub-imports work.  Skills without ``__init__.py`` (ecosystem skills
following the Anthropic spec) are discovered and their body is available
for agent activation, but no Python code runs.

Skill directories can live outside the Workspace installation (e.g.
``~/.agents/skills/`` or ``{project}/.agents/skills/``).  To ensure
these skills can import from ``core/``, the Workspace project root is added
to ``sys.path`` before any skills are loaded.
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
from core.agent_registry import AgentManager
from core.providers.registry import ProviderRegistry
from core.leader import leader as leader_registry
from core.vault import VaultManager
from core.agents_md import load_global_agents_md, load_local_agents_md, load_workspace_agents_md
from core.context_files import load_design_md, load_tasks_md, load_user_md


class Bootstrap:
    """One-shot boot sequence.  Call ``run()`` to get an :class:`AppContext`."""

    def __init__(
        self,
        working_directory: str | None = None,
        *,
        workspace_dir: str | None = None,
        agents_dir: str | None = None,
    ):
        self.wd = working_directory or os.getcwd()
        self._workspace_dir = workspace_dir or paths.workspace_dir()
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
        self._load_skill_components(skills)
        skill_service_factories = self._load_skill_init_files(skills)
        database = self._init_database(config)
        vault = self._init_vault()
        providers = self._init_provider_registry(config, vault)
        agents = self._init_agent_registry(database)
        self._register_agent_providers(agents, skills, providers)
        self._init_leader()
        css_paths = self._collect_css()

        # Call skill service factories with config and vault.
        skill_services = {
            name: factory(config, vault)
            for name, factory in skill_service_factories.items()
        }

        # Store service factories on SkillManager for query access.
        skills.set_skill_services(skill_service_factories)

        # Wire known services into dedicated AppContext fields.
        # Everything goes into the services dict too for generic access.
        known_fields = {"db_connections"}
        ctx_kwargs: dict = {"services": skill_services}
        for name, instance in skill_services.items():
            if name in known_fields:
                ctx_kwargs[name] = instance

        return AppContext(
            config=config,
            skills=skills,
            database=database,
            agents=agents,
            prompts=agents,  # deprecated alias
            vault=vault,
            providers=providers,
            leader=leader_registry,
            working_directory=self.wd,
            css_paths=css_paths,
            **ctx_kwargs,
        )

    # ------------------------------------------------------------------
    # Phase 0 — Ensure project root is on sys.path
    # ------------------------------------------------------------------

    def _ensure_project_on_path(self) -> None:
        """Ensure the Workspace project root is on ``sys.path``.

        Skill directories can live outside the installation directory
        (e.g. ``~/.agents/skills/`` or ``{project}/.agents/skills/``).
        When skills are loaded with ``importlib.util.spec_from_file_location``,
        they still need to resolve imports like ``from core.config import Config``.
        Adding the project root guarantees those imports work regardless of the
        skill's physical location.
        """
        workspace_root = self._workspace_dir
        if workspace_root not in sys.path:
            sys.path.insert(0, workspace_root)

    # ------------------------------------------------------------------
    # Phase 1 — Config
    # ------------------------------------------------------------------

    def _init_config(self) -> Config:
        """Load layered config: workspace/ → ~/.agents/ → {wd}/.agents/.

        After loading JSON files, applies module-level defaults registered
        via :func:`~core.config.register_defaults` for any keys still missing.
        """
        # Always include all three tier paths so that Config.save() has a
        # write target (the last path).  Config._load() already skips
        # non-existent files, and Config.save() creates missing directories.
        # If we only include paths that currently exist, a fresh install has
        # an empty list and save() becomes a silent no-op — all config
        # changes are lost.
        bundled = os.path.join(self._workspace_dir, "config", "config.json")
        user = os.path.join(self._agents_dir, "config", "config.json")
        project = os.path.join(self.wd, ".agents", "config", "config.json")

        cfg_paths = [bundled, user, project]

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
            os.path.join(self._workspace_dir, "skills"),
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
        core_tools = os.path.join(self._workspace_dir, "tools")
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
                f"workspace.tool.{mod_name}", mod_path
            )
            if spec is None or spec.loader is None:
                continue
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

    # ------------------------------------------------------------------
    # Phase 4 — Skill components (flat imports)
    # ------------------------------------------------------------------

    def _load_skill_components(self, skills) -> None:
        """Import sidebar panel modules from skill components/ directories.

        Skills with ``components/`` directories get their Python modules
        flat-imported (same as tools/ and cmd/).  This triggers
        ``@register_sidebar_tab()`` and ``@register_handler()`` decorators.
        """
        # Core panels
        core_panels = os.path.join(self._workspace_dir, "ui", "sidebar", "panels")
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
        core_cmd_dir = os.path.join(self._workspace_dir, "cmd")

        # Skill commands — each skill may have a cmd/ subdirectory
        skill_cmd_dirs = skills.get_skill_cmd_dirs()

        load_commands_from_paths([core_cmd_dir] + skill_cmd_dirs)

    # ------------------------------------------------------------------
    # Phase 5 — Skill __init__.py entry points (full package load)
    # ------------------------------------------------------------------

    def _load_skill_init_files(self, skills) -> dict:
        """Load skills that have ``__init__.py`` entry points.

        Skills with ``__init__.py`` are loaded with full ``importlib``
        treatment: correct ``__path__`` and ``__package__`` so that nested
        sub-imports resolve from the skill's own directory.  This is
        essential for skills with deep sub-packages (e.g. ``database``).

        Skills without ``__init__.py`` (ecosystem / Anthropic spec skills)
        are not loaded here — they are discovered and their SKILL.md body
        is available for agent activation, but no Python code runs.

        Each loaded skill may declare ``SKILL_SERVICES`` — a dict mapping
        service names to factory callables ``f(config, vault)``.  These
        are wired into ``AppContext`` as keyword arguments.

        Import errors are caught gracefully so a single broken skill
        doesn't crash the entire application.
        """
        skill_init_dirs = skills.get_skill_init_dirs()
        services: dict = {}

        # Ensure the top-level 'skills' package is registered in
        # sys.modules so that subpackage imports (skills.database.core)
        # resolve correctly.
        if "skills" not in sys.modules:
            skills_init = os.path.join(self._workspace_dir, "skills", "__init__.py")
            if os.path.isfile(skills_init):
                spec = importlib.util.spec_from_file_location(
                    "skills", skills_init
                )
                if spec is not None and spec.loader is not None:
                    pkg = importlib.util.module_from_spec(spec)
                    pkg.__path__ = [os.path.join(self._workspace_dir, "skills")]
                    pkg.__package__ = "skills"
                    sys.modules["skills"] = pkg
                    spec.loader.exec_module(pkg)
            else:
                # Synthetic package — skills/__init__.py may not exist yet.
                synthetic = types.ModuleType("skills")
                synthetic.__path__ = [os.path.join(self._workspace_dir, "skills")]
                synthetic.__package__ = "skills"
                sys.modules["skills"] = synthetic

        for skill_dir in skill_init_dirs:
            init_path = os.path.join(skill_dir, "__init__.py")
            if not os.path.isfile(init_path):
                continue

            mod_name = os.path.basename(skill_dir)
            fq_name = f"skills.{mod_name}"
            spec = importlib.util.spec_from_file_location(
                fq_name, init_path
            )
            if spec is None or spec.loader is None:
                continue
            module = importlib.util.module_from_spec(spec)
            # Set __path__ and __package__ so that sub-imports like
            # ``from skills.database.db_panel import ...`` resolve correctly
            # regardless of which tier the skill directory lives in.
            module.__path__ = [skill_dir]
            module.__package__ = fq_name
            # Register in sys.modules so @dataclass and other
            # module-name-dependent features work correctly.
            sys.modules[fq_name] = module

            # Load the skill, catching import errors so a single
            # broken skill (e.g. missing dependency) doesn't crash
            # the entire application.
            try:
                spec.loader.exec_module(module)
            except (ImportError, ModuleNotFoundError) as exc:
                # Remove the broken module from sys.modules so a later
                # retry (e.g. after installing deps) doesn't hit a stale
                # entry.
                sys.modules.pop(fq_name, None)
                print(
                    f"Warning: skipping skill {mod_name!r}: {exc}",
                    file=sys.stderr,
                )
                continue

            # Collect services declared by the skill.
            skill_services = getattr(module, "SKILL_SERVICES", None)
            if isinstance(skill_services, dict):
                for service_name, factory in skill_services.items():
                    services[service_name] = factory

        return services

    # ------------------------------------------------------------------
    # Phase 6 — Database
    # ------------------------------------------------------------------

    def _init_database(self, config: Config) -> DatabaseManager:
        db_path = config.get("database.path") or os.path.join(
            self.wd, ".agents", "workspace_data.db"
        )
        # Ensure the .agents directory exists so sqlite3 can create the file.
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        return DatabaseManager(db_path)

    # ------------------------------------------------------------------
    # Phase 7 — Vault
    # ------------------------------------------------------------------

    def _init_vault(self) -> VaultManager:
        """Create a VaultManager with master vault at ~/.agents/vault.enc."""
        master_path = os.path.join(self._agents_dir, "vault.enc")
        return VaultManager(master_path, self.wd)

    # ------------------------------------------------------------------
    # Phase 8 — Provider Registry
    # ------------------------------------------------------------------

    def _init_provider_registry(self, config: Config, vault: VaultManager) -> ProviderRegistry:
        """Create the provider registry and register all known provider types.

        Provider types are registered explicitly so the registry can
        instantiate the correct class for each named instance in config.

        The default bundled instance ``"ollama"`` is created lazily on
        first access — no provider is contacted at bootstrap time.
        """
        registry = ProviderRegistry(config=config, vault=vault)

        # Register bundled provider types.
        from core.providers.ollama import register as register_ollama
        register_ollama(registry)

        # Future: register additional provider types here.
        # from core.providers.openai import register as register_openai
        # register_openai(registry)

        return registry

    # ------------------------------------------------------------------
    # Phase 9 — Agent Registry
    # ------------------------------------------------------------------

    def _init_agent_registry(self, db: DatabaseManager) -> AgentManager:
        """Create an AgentManager backed by the database.

        Seeds the default agent definitions (chat assistant, inline suggest)
        on first run.  Also handles migration from legacy ``prompts`` and
        ``agents`` tables.
        """
        return AgentManager(db, working_directory=self.wd)

    def _register_agent_providers(
        self,
        agents: AgentManager,
        skills,
        providers: ProviderRegistry,
    ) -> None:
        """Register dynamic variable providers for agent templates."""
        agents.register_dynamic(
            "agent_name",
            lambda ctx: (
                ctx.config.get("agents.name", "Cody")
                if ctx and ctx.config else "Cody"
            ),
        )
        agents.register_dynamic(
            "skills",
            lambda ctx: {
                "__default__": skill_manager.get_catalog_xml(),
                "catalog": skill_manager.get_catalog_xml(),
                "names": ", ".join(skill_manager.list_skills()),
            },
        )
        agents.register_dynamic(
            "working_directory",
            lambda ctx: ctx.working_directory if ctx and ctx.working_directory else self.wd,
        )
        agents.register_dynamic(
            "project_name",
            lambda ctx: os.path.basename(
                ctx.working_directory if ctx and ctx.working_directory else self.wd
            ),
        )
        from datetime import timezone
        from datetime import datetime as _dt
        agents.register_dynamic(
            "date",
            lambda ctx: _dt.now(timezone.utc).strftime("%Y-%m-%d"),
        )
        agents.register_dynamic(
            "model",
            lambda ctx: (
                ctx.config.get(f"providers.{ctx.config.get('session.provider', 'ollama')}.model", "")
                if ctx and ctx.config
                else ""
            ),
        )
        agents.register_dynamic(
            "provider",
            lambda ctx: (
                ctx.config.get("session.provider", "ollama")
                if ctx and ctx.config
                else "ollama"
            ),
        )
        agents.register_dynamic(
            "user",
            lambda ctx: load_user_md(ctx),
        )
        agents.register_dynamic(
            "design",
            lambda ctx: load_design_md(ctx),
        )
        agents.register_dynamic(
            "tasks",
            lambda ctx: load_tasks_md(ctx),
        )
        agents.register_dynamic(
            "workspace_agents",
            lambda ctx: load_workspace_agents_md(ctx),
        )
        agents.register_dynamic(
            "global_agents",
            lambda ctx: load_global_agents_md(ctx),
        )
        agents.register_dynamic(
            "local_agents",
            lambda ctx: load_local_agents_md(ctx),
        )

    # ------------------------------------------------------------------
    # Phase 10 — Leader chords
    # ------------------------------------------------------------------

    def _init_leader(self) -> None:
        """Register core leader chords from workspace, etc."""
        from ui.workspace.workspace import register_workspace_leader_chords

        register_workspace_leader_chords()

    # ------------------------------------------------------------------
    # Phase 11 — CSS
    # ------------------------------------------------------------------

    def _collect_css(self) -> list[str]:
        """Collect all .tcss files across the three tiers."""
        return paths.collect_tcss(self.wd)