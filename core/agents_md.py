"""AGENTS.md file loader — scans tiered directories for agent rules files.

Workspace resolves resources across three tiers:

1. Workspace installation directory (bundled defaults)
2. ~/.agents (user-wide overrides)
3. {working_directory}/.agents (project-specific overrides)

This module scans the **user** and **project** tiers for ``AGENTS.md`` files
and returns their contents as strings for injection into agent system prompts
via the ``{{global_agents}}`` and ``{{local_agents}}`` template variables.

- ``{{global_agents}}`` — content of ``~/.agents/AGENTS.md`` (user-wide rules)
- ``{{local_agents}}`` — content of ``{working_directory}/.agents/AGENTS.md``
  (project-specific rules)

If either file is missing, the corresponding variable resolves to an empty
string, so the placeholder is cleanly removed from the rendered prompt.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from context import AppContext


def load_global_agents_md(ctx: AppContext) -> str:
    """Load the global ``~/.agents/AGENTS.md`` file.

    Returns the file content wrapped with newlines for clean prompt
    composition, or an empty string if the file does not exist.
    The returned string (when non-empty) starts with a newline so it
    sits naturally after preceding template lines, and ends with a
    newline so the next section is properly separated.
    """
    agents_dir = os.path.join(os.path.expanduser("~"), ".agents")
    path = os.path.join(agents_dir, "AGENTS.md")
    content = _read_agents_md(path)
    if content:
        return f"\n{content}\n"
    return ""


def load_local_agents_md(ctx: AppContext) -> str:
    """Load the project-local ``{working_directory}/.agents/AGENTS.md`` file.

    Returns the file content wrapped with newlines for clean prompt
    composition, or an empty string if the file does not exist.
    The returned string (when non-empty) starts with a newline so it
    sits naturally after preceding template lines, and ends with a
    newline so the next section is properly separated.
    """
    wd = ""
    if ctx and ctx.working_directory:
        wd = ctx.working_directory

    if not wd:
        return ""

    path = os.path.join(wd, ".agents", "AGENTS.md")
    content = _read_agents_md(path)
    if content:
        return f"\n{content}\n"
    return ""


def _read_agents_md(path: str) -> str:
    """Read an AGENTS.md file, returning its content or an empty string."""
    if not os.path.isfile(path):
        return ""
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read().strip()
        return content
    except (OSError, UnicodeDecodeError):
        return ""