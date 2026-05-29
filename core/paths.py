"""3-tier path resolution for Cody.

Cody resolves resources (skills, tools, themes, commands) across
three tiers in order of increasing precedence:

1. Cody installation directory (bundled defaults)
2. ~/.agents (user-wide overrides)
3. {working_directory}/.agents (project-specific overrides)

Later tiers override earlier tiers for same-named resources.

Skills are the sole extension mechanism.  A skill is a directory with a
``SKILL.md`` manifest.  Skills with ``__init__.py`` are loaded at bootstrap
with full ``importlib`` treatment; ecosystem skills (Anthropic spec) work
without ``__init__.py`` — they are discovered and their body is available
for agent activation.
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
        paths.extend(_find_tcss(root))
    return paths


def _find_tcss(root: str) -> list[str]:
    """Walk *root* and return all ``.tcss`` files, sorted for determinism.

    Returns an empty list if *root* does not exist.
    """
    if not os.path.isdir(root):
        return []
    result: list[str] = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for f in sorted(filenames):
            if f.endswith(".tcss"):
                result.append(os.path.join(dirpath, f))
    return result