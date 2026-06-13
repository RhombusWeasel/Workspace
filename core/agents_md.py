"""AGENTS.md file loader — scans tiered directories for agent rules files.

Workspace resolves resources across three tiers:

1. Workspace installation directory (bundled defaults)
2. ~/.agents (user-wide overrides)
3. {working_directory}/.agents (project-specific overrides)

This module scans all three tiers for ``AGENTS.md`` files and returns
their contents as strings for injection into agent system prompts via the
``{{workspace_agents}}``, ``{{global_agents}}``, and ``{{local_agents}}``
template variables.

- ``{{workspace_agents}}`` — content of ``{workspace_dir}/AGENTS.md``
  (bundled defaults)
- ``{{global_agents}}`` — content of ``~/.agents/AGENTS.md``
  (user-wide rules)
- ``{{local_agents}}`` — content of ``{working_directory}/.agents/AGENTS.md``
  and/or ``{working_directory}/AGENTS.md`` (project-specific rules)

For ``local_agents``, both the ``.agents/`` subdirectory and the project
root are checked.  If both files exist, their contents are concatenated
(with ``.agents/`` content first, as it is the more specific location).

If any file is missing, the corresponding variable resolves to an empty
string, so the placeholder is cleanly removed from the rendered prompt.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from core.paths import workspace_dir as get_workspace_dir

if TYPE_CHECKING:
    from context import AppContext


def load_workspace_agents_md(ctx: AppContext) -> str:
    """Load the workspace-bundled ``{workspace_dir}/AGENTS.md`` file.

    Returns the file content wrapped with newlines for clean prompt
    composition, or an empty string if the file does not exist.
    The returned string (when non-empty) starts with a newline so it
    sits naturally after preceding template lines, and ends with a
    newline so the next section is properly separated.
    """
    path = os.path.join(get_workspace_dir(), "AGENTS.md")
    content = _read_agents_md(path)
    if content:
        return f"\n{content}\n"
    return ""


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
    """Load project-local AGENTS.md files.

    Checks two locations in the working directory:
    1. ``{working_directory}/.agents/AGENTS.md`` (project .agents dir)
    2. ``{working_directory}/AGENTS.md`` (project root)

    If both files exist, their contents are concatenated (``.agents/``
    first, then root) so that the more specific ``.agents/`` rules take
    precedence in ordering.  The combined content is wrapped with
    newlines for clean prompt composition.

    Returns an empty string if neither file exists.
    """
    wd = ""
    if ctx and ctx.working_directory:
        wd = ctx.working_directory

    if not wd:
        return ""

    parts: list[str] = []

    # Check .agents/ subdirectory first (more specific)
    agents_subdir_path = os.path.join(wd, ".agents", "AGENTS.md")
    agents_subdir_content = _read_agents_md(agents_subdir_path)
    if agents_subdir_content:
        parts.append(agents_subdir_content)

    # Also check project root (common convention)
    root_path = os.path.join(wd, "AGENTS.md")
    root_content = _read_agents_md(root_path)
    if root_content:
        parts.append(root_content)

    if not parts:
        return ""

    combined = "\n\n".join(parts)
    return f"\n{combined}\n"


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