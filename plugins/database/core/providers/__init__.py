"""Auto-discovery for database providers.

Scans this directory for ``.py`` files (excluding ``__init__.py`` and
private modules starting with ``_``) and imports each one.  Provider
modules use ``@register_provider`` to self-register into the global
provider registry in ``db_connections.py`` — so simply dropping a new
provider file into this directory is all that's needed to add backend
support.
"""

import importlib
import os

# --- Auto-discover all provider modules in this directory ---
_dir = os.path.dirname(__file__)
for _filename in sorted(os.listdir(_dir)):
    if _filename.endswith(".py") and not _filename.startswith("_"):
        _mod_name = _filename[:-3]
        importlib.import_module(f".{_mod_name}", __package__)