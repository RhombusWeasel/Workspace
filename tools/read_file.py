"""Read file tool — reads a file's contents, restricted to the working directory.

Registered at import time via ``@register_tool()``.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from core.tools import register_tool

if TYPE_CHECKING:
    from context import AppContext

_MAX_BYTES = 256 * 1024  # 256 KB


@register_tool(
    name="read_file",
    tags=["files"],
    description="Read the contents of a file. Paths outside the working directory are rejected.",
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": (
                    "Absolute or relative path to the file. "
                    "Must resolve to a path inside the working directory."
                ),
            },
        },
        "required": ["path"],
    },
)
def read_file(path: str, ctx: "AppContext | None" = None) -> str:
    """Read and return the contents of *path*.

    *path* is resolved relative to the working directory (from *ctx*).
    Absolute paths are accepted only if they resolve inside the working
    directory.  Symlinks are resolved before the boundary check.

    Returns the file text on success, or an error message string.
    """
    wd = ctx.working_directory if ctx else os.getcwd()
    wd = os.path.realpath(wd)

    # Resolve the requested path.
    if os.path.isabs(path):
        resolved = os.path.realpath(path)
    else:
        resolved = os.path.realpath(os.path.join(wd, path))

    # Boundary check: resolved path must start with wd + separator.
    if not resolved.startswith(wd + os.sep) and resolved != wd:
        return (
            f"Access denied: '{path}' resolves outside the working directory "
            f"({wd})."
        )

    # Must be a regular file.
    if not os.path.isfile(resolved):
        return f"Not a regular file: '{path}'."

    # Size check.
    try:
        size = os.path.getsize(resolved)
    except OSError as exc:
        return f"Cannot stat '{path}': {exc}"

    if size > _MAX_BYTES:
        return (
            f"File too large: {size} bytes (max {_MAX_BYTES}). "
            f"Read the file in smaller chunks."
        )

    # Read.
    try:
        with open(resolved, encoding="utf-8") as fh:
            return fh.read()
    except UnicodeDecodeError:
        return f"Cannot read '{path}' as UTF-8 text (possibly binary)."
    except OSError as exc:
        return f"Cannot read '{path}': {exc}"
