"""Application context — service locator holding references to all core services.

Built once at bootstrap and threaded through to every component that needs
to query config, database, leader chords, or issue app commands.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.config import Config
    from core.database import DatabaseManager
    from core.leader import LeaderRegistry
    from core.skills import SkillManager
    from core.vault import VaultManager


@dataclass
class AppContext:
    """Holds references to services components need to *query* at runtime.

    This is a service locator, not a DI container.  The tool registry and
    skill manager remain module-level singletons — their self-registration
    patterns (``@register_tool()``, ``SkillManager()``) are essential for
    drop-in extensibility.

    ``db_connections`` is populated by the plugin system — the database
    plugin's ``PLUGIN_SERVICES`` factory creates the ConnectionManager
    at bootstrap time.
    """

    config: Config | None = None
    skills: SkillManager | None = None
    database: DatabaseManager | None = None
    db_connections: Any = None
    """Connection manager provided by the database plugin.

    Set to a :class:`ConnectionManager` instance by bootstrap if the
    database plugin is loaded; ``None`` otherwise.
    """
    leader: LeaderRegistry | None = None
    vault: VaultManager | None = None
    working_directory: str = ""
    css_paths: list[str] = field(default_factory=list)
    app: Any = None
    """The running :class:`CodyApp` instance.

    Set by the app in its constructor.  Event handlers use this to
    call ``push_screen_wait()``, ``notify()``, and query the DOM.
    """