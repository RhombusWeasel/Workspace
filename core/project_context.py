"""Project context file loader — reads user, design, and tasks markdown files.

Workspace resolves project context from two locations:

1. ``~/.agents/user.md`` — global user profile (name, preferences, etc.)
2. ``{working_directory}/.agents/design.md`` — project design documentation
3. ``{working_directory}/.agents/tasks.md`` — project task tracking

These files are injected into agent system prompts via ``{{user}}``,
``{{design}}``, and ``{{tasks}}`` template variables.

If a file exists, its content is returned verbatim (stripped of leading/
trailing whitespace).  If a file is missing, a helpful instruction block
is returned telling the agent to create and populate the file.  This
ensures the agent always has guidance about these context files regardless
of whether they've been initialised yet.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from context import AppContext

# ---------------------------------------------------------------------------
# Fallback instructions (returned when files are missing)
# ---------------------------------------------------------------------------

_USER_MISSING = (
    "# User Profile\n\n"
    "No user profile file found.  Create ``~/.agents/user.md`` with basic "
    "information about the user — name, preferred syntax, project preferences, "
    "etc.  Read this file at the start of every session to personalise "
    "responses.  Keep it updated as you learn more about the user.\n"
)

_DESIGN_MISSING = (
    "# Project Design\n\n"
    "No design document found.  Create ``.agents/design.md`` in the working "
    "directory with a brief summary of the project, its structure, and any "
    "patterns used.  This file should contain only the information required "
    "for quick getting-started context — enough to speed up induction for a "
    "new task.  Keep it updated as the project evolves.\n"
)

_TASKS_MISSING = (
    "# Tasks\n\n"
    "No task tracking file found.  Create ``.agents/tasks.md`` in the working "
    "directory to track current and completed work.  Update it as you and the "
    "user make progress.  Use it to maintain continuity between sessions.\n"
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_file(path: str) -> str | None:
    """Read a file, returning its content stripped, or ``None`` on failure."""
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read().strip()
        return content if content else None
    except (OSError, UnicodeDecodeError):
        return None


def _wrap(content: str) -> str:
    """Wrap content with newlines for clean prompt composition.

    Ensures a leading newline (to separate from preceding template text)
    and a trailing newline (to separate from following sections).
    """
    return f"\n{content}\n"


# ---------------------------------------------------------------------------
# Public loaders
# ---------------------------------------------------------------------------


def load_user_md(ctx: AppContext) -> str:
    """Load the global user profile from ``~/.agents/user.md``.

    Returns the file content if present, or fallback instructions telling
    the agent to create and populate the file.
    """
    agents_dir = os.path.join(os.path.expanduser("~"), ".agents")
    path = os.path.join(agents_dir, "user.md")
    content = _read_file(path)
    if content is not None:
        return _wrap(content)
    return _wrap(_USER_MISSING)


def load_design_md(ctx: AppContext) -> str:
    """Load the project design document from ``{wd}/.agents/design.md``.

    Returns the file content if present, or fallback instructions telling
    the agent to create and populate the file.
    """
    wd = ""
    if ctx and ctx.working_directory:
        wd = ctx.working_directory
    if not wd:
        return _wrap(_DESIGN_MISSING)

    path = os.path.join(wd, ".agents", "design.md")
    content = _read_file(path)
    if content is not None:
        return _wrap(content)
    return _wrap(_DESIGN_MISSING)


def load_tasks_md(ctx: AppContext) -> str:
    """Load the project task tracking file from ``{wd}/.agents/tasks.md``.

    Returns the file content if present, or fallback instructions telling
    the agent to create and populate the file.
    """
    wd = ""
    if ctx and ctx.working_directory:
        wd = ctx.working_directory
    if not wd:
        return _wrap(_TASKS_MISSING)

    path = os.path.join(wd, ".agents", "tasks.md")
    content = _read_file(path)
    if content is not None:
        return _wrap(content)
    return _wrap(_TASKS_MISSING)