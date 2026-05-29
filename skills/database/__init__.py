"""Database skill — sidebar browser, query editor, and connection management.

Importing this module triggers all side-effect registrations:
- ``@register_sidebar_tab`` for the DB panel
- ``@register_handler`` for the ``db.open_query`` event
- ``register_defaults`` for ``db.connections`` and ``db.default_page_size`` config

The ``SKILL_SERVICES`` dict declares services that bootstrap wires into
AppContext.  Currently provides ``db_connections`` (ConnectionManager).
"""

# Side-effect imports — trigger decorator registrations.
from skills.database.db_panel import DBPanel  # noqa: F401
from skills.database.services import SKILL_SERVICES  # noqa: F401

__all__ = ["DBPanel", "SKILL_SERVICES"]