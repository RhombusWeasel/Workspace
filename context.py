"""Application context — service locator holding references to all core services.

Built once at bootstrap and threaded through to every component that needs
to query config, database, leader chords, or issue app commands.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.config import Config
    from core.database import DatabaseManager
    from core.leader import LeaderRegistry
    from core.skills import SkillManager


@dataclass
class AppContext:
    """Holds references to services components need to *query* at runtime.

    This is a service locator, not a DI container.  The tool registry and
    skill manager remain module-level singletons — their self-registration
    patterns (``@register_tool()``, ``SkillManager()``) are essential for
    drop-in extensibility.
    """

    config: Config | None = None
    skills: SkillManager | None = None
    database: DatabaseManager | None = None
    leader: LeaderRegistry | None = None
    working_directory: str = ""
