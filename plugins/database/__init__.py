"""Database plugin — sidebar browser, query editor, and connection management.

Importing this module triggers all side-effect registrations:
- ``@register_sidebar_tab`` for the DB panel
- ``@register_handler`` for the ``db.open_query`` event
- ``register_defaults`` for ``db.connections`` and ``db.default_page_size`` config

The ``PLUGIN_SERVICES`` dict declares services that bootstrap wires into
AppContext.  Currently provides ``db_connections`` (ConnectionManager).
"""

# Side-effect imports — trigger decorator registrations.
from plugins.database.db_panel import DBPanel  # noqa: F401
from plugins.database.services import PLUGIN_SERVICES  # noqa: F401

__all__ = ["DBPanel", "PLUGIN_SERVICES"]