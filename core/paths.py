"""3-tier path resolution for Cody.

Cody resolves resources (skills, tools, themes, commands, plugins) across
three tiers in order of increasing precedence:

1. Cody installation directory (bundled defaults)
2. ~/.agents (user-wide overrides)
3. {working_directory}/.agents (project-specific overrides)

Later tiers override earlier tiers for same-named resources.

For plugins specifically, each tier is scanned for subdirectories under
``plugins/`` that contain a ``SKILL.md`` manifest.  A plugin at
``~/.agents/plugins/my_plugin/`` overrides a same-named plugin at
``{cody_dir}/plugins/my_plugin/``.  Plugins are loaded by
:func:`bootstrap.Bootstrap._load_plugins`, which ensures:

- The Cody project root is on ``sys.path`` so plugins can import from
  ``core/``.
- Each plugin module gets correct ``__path__`` and ``__package__``
  attributes so sub-imports (e.g. ``from plugins.my_plugin.core import X``)
  resolve from the plugin's own directory, regardless of which tier it
  lives in.
"""

import os


def cody_dir() -> str:
    """Absolute path to the Cody installation directory."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def agents_dir() -> str:
    """Absolute path to the global ~/.agents directory."""
    return os.path.join(os.path.expanduser("~"), ".agents")


def resolve(subpath: str, working_dir: str) -> list[str]:
    """Resolve *subpath* across all three tiers.

    Returns three absolute paths in order: cody, user, project.
    """
    return [
        os.path.normpath(os.path.join(cody_dir(), subpath)),
        os.path.normpath(os.path.join(agents_dir(), subpath)),
        os.path.normpath(os.path.join(working_dir, ".agents", subpath)),
    ]


def collect_tcss(working_dir: str) -> list[str]:
    """Collect all ``.tcss`` files across all three tiers.

    Returns paths in order: cody (bundled), user (``~/.agents/``),
    project (``{wd}/.agents/``).  Later tiers override earlier tiers in
    Textual's CSS cascade, so project-level CSS can override user-level
    which can override bundled defaults.
    """
    roots = resolve("", working_dir)
    paths: list[str] = []
    for root in roots:
        paths.extend(_find_tcss(root, skip_plugins=True))
    return paths


def _find_tcss(root: str, *, skip_plugins: bool = False) -> list[str]:
    """Walk *root* and return all ``.tcss`` files, sorted for determinism.

    Returns an empty list if *root* does not exist.

    If *skip_plugins* is True, the ``plugins/`` subdirectory is
    excluded — plugin CSS is collected separately by
    :func:`collect_plugin_tcss` so that tier overriding works correctly.
    """
    if not os.path.isdir(root):
        return []
    result: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        # Skip the plugins/ subtree — plugin CSS is collected separately
        # by collect_plugin_tcss() which applies 3-tier override semantics.
        if skip_plugins:
            dirnames[:] = [d for d in dirnames if d != "plugins"]
        for f in sorted(filenames):
            if f.endswith(".tcss"):
                result.append(os.path.join(dirpath, f))
    return result


# ---------------------------------------------------------------------------
# Plugin discovery
# ---------------------------------------------------------------------------


def discover_plugins(working_dir: str) -> list[str]:
    """Discover plugin directories containing a ``SKILL.md`` manifest.

    Scans the three-tier paths under the ``plugins/`` subdirectory.
    Returns absolute paths to plugin directories (the parent of
    SKILL.md), in tier order (cody → user → project).  Later tiers
    override earlier tiers for same-named plugins.

    A valid plugin directory has this structure::

        plugins/my_plugin/
        ├── SKILL.md          # Required — manifest with name + description
        ├── __init__.py       # Required — entry point for registrations
        ├── core/             # Optional — plugin internals
        │   └── ...
        ├── my_plugin.tcss    # Optional — plugin CSS
        └── ...               # Other modules imported by __init__.py

    The ``__init__.py`` file is executed by the bootstrap loader and
    should trigger side-effect registrations (``@register_sidebar_tab``,
    ``@register_handler``, config defaults) and optionally declare
    ``PLUGIN_SERVICES`` — a dict mapping service names to factory
    callables that bootstrap wires into ``AppContext``.
    """
    tier_paths = resolve("plugins", working_dir)
    discovered: dict[str, str] = {}

    for tier_dir in tier_paths:
        if not os.path.isdir(tier_dir):
            continue
        try:
            entries = sorted(os.listdir(tier_dir))
        except OSError:
            continue
        for entry in entries:
            plugin_dir = os.path.join(tier_dir, entry)
            md_path = os.path.join(plugin_dir, "SKILL.md")
            if os.path.isfile(md_path):
                discovered[entry] = plugin_dir

    return list(discovered.values())


def collect_plugin_tcss(working_dir: str) -> list[str]:
    """Collect ``.tcss`` files from all discovered plugins.

    Returns paths sorted for deterministic CSS load order.
    """
    plugin_dirs = discover_plugins(working_dir)
    paths: list[str] = []
    for plugin_dir in plugin_dirs:
        paths.extend(_find_tcss(plugin_dir))
    return paths