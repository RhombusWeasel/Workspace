"""Bootstrap — wires together all core services and returns an AppContext.

Called once at application startup.  Steps through:

1. Load layered config from tiered JSON files.
2. Discover skills (3-tier scan).
3. Load agent tools (core + skill tiers).
4. Initialize SQLite database.
5. Create vault manager (master + optional local vault).
6. Build leader chord tree (core module chords).
7. Return an :class:`AppContext`.

Git checkpoints and theme/ CSS discovery are deferred to later steps.
"""

from __future__ import annotations

import os
import importlib.util
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
        config = self._init_config()
        skills = self._discover_skills(config)
        self._load_tools(skills)
        self._load_commands(skills)
        self._load_sidebar_panels(skills)
        database = self._init_database(config)
        vault = self._init_vault()
        self._init_leader()
        css_paths = self._collect_css()

        return AppContext(
            config=config,
            skills=skills,
            database=database,
            vault=vault,
            leader=leader_registry,
            working_directory=self.wd,
            css_paths=css_paths,
        )

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
    # Phase 4 — Sidebar panels
    # ------------------------------------------------------------------

    def _load_sidebar_panels(self, skills) -> None:
        """Import sidebar panel modules to trigger @register_sidebar_tab()."""
        # Core panels
        core_panels = os.path.join(self._cody_dir, "ui", "sidebar", "panels")
        self._import_modules_from(core_panels)

        # Skill panels (future: discover from skill dirs)

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
    # Phase 7 — Leader chords
    # ------------------------------------------------------------------

    def _init_leader(self) -> None:
        """Register core leader chords from workspace (and later chat, terminal)."""
        from ui.workspace.workspace import register_workspace_leader_chords

        register_workspace_leader_chords()

    # ------------------------------------------------------------------
    # Phase 8 — CSS
    # ------------------------------------------------------------------

    def _collect_css(self) -> list[str]:
        """Collect all .tcss files across the three tiers."""
        return paths.collect_tcss(self.wd)
