"""Read file tool — reads a file's contents, restricted to the working directory.

Registered at import time via ``@register_tool()``.

Supports ``offset`` and ``limit`` parameters for reading large files in
chunks.  When the file exceeds ``_MAX_OUTPUT_LINES`` lines and no limit
is specified, the output is truncated with instructions to continue
reading with offset/limit.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from core.tools import register_tool

if TYPE_CHECKING:
    from context import AppContext

_MAX_BYTES = 256 * 1024  # 256 KB
_MAX_OUTPUT_LINES = 500  # Max lines returned when limit is not specified


@register_tool(
    name="read_file",
    tags=["files"],
    description=(
        "Read the contents of a file. Paths outside the working directory are rejected. "
        "For large files, use offset and limit to read in chunks — "
        "offset is the 1-indexed line number to start from, "
        "limit is the maximum number of lines to return. "
        "If the file has more lines than the output limit and no limit is specified, "
        "the output is truncated with a summary showing total lines and how to continue."
    ),
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
            "offset": {
                "type": "integer",
                "description": (
                    "Line number to start reading from (1-indexed). "
                    "Use this with limit to read large files in chunks."
                ),
            },
            "limit": {
                "type": "integer",
                "description": (
                    "Maximum number of lines to return. "
                    "If set, only this many lines are returned starting from offset. "
                    "If not set, the file is read entirely but may be truncated "
                    "if it exceeds the output line limit."
                ),
            },
        },
        "required": ["path"],
    },
)
def read_file(
    path: str,
    offset: int | None = None,
    limit: int | None = None,
    ctx: "AppContext | None" = None,
) -> str:
    """Read and return the contents of *path*, optionally starting at
    *offset* (1-indexed line number) and returning at most *limit* lines.

    *path* is resolved relative to the working directory (from *ctx*).
    Absolute paths are accepted only if they resolve inside the working
    directory.  Symlinks are resolved before the boundary check.

    When *limit* is not specified and the file exceeds
    ``_MAX_OUTPUT_LINES`` lines, the output is truncated with a summary
    showing the total line count and instructions to continue reading.

    Returns the file text on success, or an error message string.
    """
    # Validate offset/limit early.
    if offset is not None and offset < 1:
        return f"Invalid offset: {offset}. Offset must be >= 1 (1-indexed)."
    if limit is not None and limit < 1:
        return f"Invalid limit: {limit}. Limit must be >= 1."

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
            f"Read the file in smaller chunks using offset and limit."
        )

    # Read.
    try:
        with open(resolved, encoding="utf-8") as fh:
            all_lines = fh.readlines()
    except UnicodeDecodeError:
        return f"Cannot read '{path}' as UTF-8 text (possibly binary)."
    except OSError as exc:
        return f"Cannot read '{path}': {exc}"

    total_lines = len(all_lines)
    start = (offset or 1) - 1  # Convert 1-indexed to 0-indexed

    # Clamp start to file range.
    if start >= total_lines:
        return (
            f"Offset {offset} exceeds file length ({total_lines} lines). "
            f"File '{path}' has {total_lines} lines."
        )

    # Determine effective limit.
    effective_limit = limit if limit is not None else _MAX_OUTPUT_LINES
    selected = all_lines[start : start + effective_limit]

    # Build output.
    result = "".join(selected)

    # Add line number prefix for clarity when paginating.
    if offset is not None or limit is not None:
        numbered = []
        for i, line in enumerate(selected, start=start + 1):
            numbered.append(f"{i:>6}\t{line}")
        result = "".join(numbered)

    # Truncation notice.
    end_line = start + len(selected)
    truncated = end_line < total_lines
    if truncated:
        result += (
            f"\n\n[File '{path}' — showing lines {start + 1}-{end_line} "
            f"of {total_lines}. Use offset={end_line + 1} to continue reading.]"
        )

    return result
