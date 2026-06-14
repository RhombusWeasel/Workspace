"""Context file loader — reads user, design, and tasks markdown files.

These files provide persistent context that is injected into agent system
prompts via the ``{{user}}``, ``{{design}}``, and ``{{tasks}}`` template
variables.

- ``{{user}}`` — content of ``~/.agents/user.md``
  (global user profile, persisted across all projects)
- ``{{design}}`` — content of ``{working_directory}/.agents/design.md``
  (project design documentation)
- ``{{tasks}}`` — content of ``{working_directory}/.agents/tasks.md``
  (project task tracking)

When a file exists, its content is returned wrapped in newlines for clean
prompt composition (matching the ``agents_md.py`` pattern).

When a file is missing, a brief instruction is returned telling the agent
to create the file.  This ensures agents are always aware of these
context files and will bootstrap them on first use.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from context import AppContext

# ---------------------------------------------------------------------------
# Instruction text injected when files are missing
# ---------------------------------------------------------------------------

_MISSING_USER_INSTRUCTION = (
    "Check for a file in ~/.agents/user.md this is a place for you to store "
    "information about the user, you should always read this file first.  "
    "If it doesn't exist then you should create it and try to gather some "
    "simple information about the user to begin with like their name and "
    "any syntax preferences they may have.\n"
    "This file exists to allow you to share information about the user "
    "between sessions to personalize the experience and allow for more "
    "meaningful responses."
)

_MISSING_DESIGN_INSTRUCTION = (
    "You should always check for any design documentation files in "
    ".agents/design.md or README.md files to try and understand the project "
    "you are working on.\n"
    "If there is no .agents/design.md file then you should create it and "
    "document your understanding of the project there as you learn more.\n"
    "Keep the .agents/design.md document up to date, it should contain a "
    "brief summary of the project as a whole, it's structure and any "
    "patterns used.  This file should contain only the information required "
    "for quick getting started information to speed up induction for a new task."
)

_MISSING_TASKS_INSTRUCTION = (
    "You should also check for the existence of a tasks file like "
    ".agents/tasks.md and ensure the task list is understood and kept up to "
    "date.\n"
    "If there is no task list you should create .agents/tasks.md and "
    "maintain it to track your and the users progress."
)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _read_file(path: str) -> str:
    """Read a file, returning its stripped content or an empty string."""
    if not os.path.isfile(path):
        return ""
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read().strip()
        return content
    except (OSError, UnicodeDecodeError):
        return ""


# ---------------------------------------------------------------------------
# Public loaders
# ---------------------------------------------------------------------------


def load_user_md(ctx: AppContext) -> str:
    """Load the global ``~/.agents/user.md`` file.

    Returns the file content wrapped with newlines for clean prompt
    composition.  If the file does not exist, returns an instruction
    telling the agent to create it.
    """
    path = os.path.join(os.path.expanduser("~"), ".agents", "user.md")
    content = _read_file(path)
    if content:
        return f"\n{content}\n"
    return f"\n{_MISSING_USER_INSTRUCTION}\n"


def load_design_md(ctx: AppContext) -> str:
    """Load the project ``{working_directory}/.agents/design.md`` file.

    Returns the file content wrapped with newlines for clean prompt
    composition.  If the file does not exist (or there is no working
    directory), returns an instruction telling the agent to create it.
    """
    wd = ctx.working_directory if ctx and ctx.working_directory else ""
    if not wd:
        return f"\n{_MISSING_DESIGN_INSTRUCTION}\n"

    path = os.path.join(wd, ".agents", "design.md")
    content = _read_file(path)
    if content:
        return f"\n{content}\n"
    return f"\n{_MISSING_DESIGN_INSTRUCTION}\n"


def load_tasks_md(ctx: AppContext) -> str:
    """Load the project ``{working_directory}/.agents/tasks.md`` file.

    Returns the file content wrapped with newlines for clean prompt
    composition.  If the file does not exist (or there is no working
    directory), returns an instruction telling the agent to create it.
    """
    wd = ctx.working_directory if ctx and ctx.working_directory else ""
    if not wd:
        return f"\n{_MISSING_TASKS_INSTRUCTION}\n"

    path = os.path.join(wd, ".agents", "tasks.md")
    content = _read_file(path)
    if content:
        return f"\n{content}\n"
    return f"\n{_MISSING_TASKS_INSTRUCTION}\n"