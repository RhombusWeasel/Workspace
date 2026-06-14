"""Shared path resolution for file/command tools.

Provides ``resolve_tool_path`` and ``resolve_tool_cwd`` so that the
``directory`` parameter (``"project"`` / ``"global"``) is handled
consistently across run_command, write_file, edit_file, and read_file.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from context import AppContext

# The two allowed scopes for the ``directory`` parameter.
_VALID_DIRECTORIES = {"project", "global"}


def validate_directory(directory: str) -> str | None:
    """Return an error string if *directory* is invalid, else ``None``."""
    if directory not in _VALID_DIRECTORIES:
        return (
            f"Invalid directory '{directory}'. "
            f"Must be 'project' or 'global'."
        )
    return None


def resolve_tool_path(
    path: str,
    directory: str,
    ctx: "AppContext | None",
) -> tuple[str, str]:
    """Resolve *path* and the root it must stay within.

    Returns ``(resolved_path, boundary_root)`` where *boundary_root* is
    the directory that *resolved_path* must start with.

    * ``directory='project'`` — resolves against the working directory.
    * ``directory='global'`` — resolves against ``~/.agents/``.
    """
    if directory == "global":
        root = os.path.realpath(os.path.expanduser("~/.agents"))
    else:
        wd = ctx.working_directory if ctx else os.getcwd()
        root = os.path.realpath(wd)

    if os.path.isabs(path):
        resolved = os.path.realpath(path)
    else:
        resolved = os.path.realpath(os.path.join(root, path))

    return resolved, root


def check_path_boundary(resolved: str, root: str, display_path: str) -> str | None:
    """Return an error string if *resolved* escapes *root*, else ``None``."""
    # Ensure both end with separator so /foo matches /foobar
    if not resolved.startswith(root + os.sep) and resolved != root:
        return (
            f"Access denied: '{display_path}' resolves outside the "
            f"allowed directory ({root})."
        )
    return None


def resolve_tool_cwd(directory: str, ctx: "AppContext | None") -> str:
    """Return the cwd to use for a command, based on *directory* scope."""
    if directory == "global":
        return os.path.realpath(os.path.expanduser("~/.agents"))
    else:
        return ctx.working_directory if ctx else os.getcwd()