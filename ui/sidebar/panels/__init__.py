"""Sidebar panels.

Core panels are imported here so their @register_sidebar_tab decorators
fire at import time.  Plugin panels (e.g. database) are registered by
the plugin system during bootstrap.
"""

# Core panels — sidebar tabs that are always present.
# (Vault, file browser, config, chat panels are imported by bootstrap's
# _load_sidebar_panels which scans ui/sidebar/panels/ for .py files.)