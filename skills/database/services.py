"""Skill service factories — maps service names to factory callables.

Each skill that contributes services to AppContext declares them here.
Bootstrap calls each factory with the relevant config/vault objects and
assigns the result to AppContext.
"""

from core.config import Config
from core.vault import VaultManager
from skills.database.core.db_connections import ConnectionManager


def create_db_connections(config: Config, vault: VaultManager) -> ConnectionManager:
    """Factory for the ``db_connections`` service on AppContext."""
    return ConnectionManager(config, vault)


# Service name → factory callable.
# Bootstrap reads this dict to populate AppContext fields.
SKILL_SERVICES = {
    "db_connections": create_db_connections,
}