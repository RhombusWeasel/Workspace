"""3-tier path resolution for Cody.

Cody resolves resources (skills, tools, themes, commands) across three tiers
in order of increasing precedence:

1. Cody installation directory (bundled defaults)
2. ~/.agents (user-wide overrides)
3. {working_directory}/.agents (project-specific overrides)

Later tiers override earlier tiers for same-named resources.
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
