"""Database plugin core — ConnectionManager, DBProvider abstractions, and providers.

Provider modules live in the ``providers/`` sub-package and are auto-discovered
at import time.  Drop a new ``.py`` file there, decorate the class with
``@register_provider``, and it becomes available.
"""