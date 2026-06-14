"""Write file tool — creates or overwrites a file after user confirmation.

Registered at import time via ``@register_tool()``.  Async because it
pushes a :class:`~ui.widgets.confirm_modal.ConfirmModal`.

The ``directory`` parameter controls which root paths are resolved
against:

- ``"project"`` (default) — the workspace working directory.
- ``"global"`` — ``~/.agents/``, allowing agents to create global skills.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from core.tools import register_tool
from tools._path_utils import (
    validate_directory,
    resolve_tool_path,
    check_path_boundary,
)

if TYPE_CHECKING:
    from context import AppContext


@register_tool(
    name="write_file",
    tags=["files"],
    description=(
        "Write content to a file. Paths outside the allowed directory "
        "are rejected. The user is shown a diff and must confirm before "
        "the write happens."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": (
                    "Absolute or relative path for the new file. "
                    "Must resolve inside the allowed directory."
                ),
            },
            "content": {
                "type": "string",
                "description": "The exact text content to write to the file.",
            },
            "directory": {
                "type": "string",
                "description": (
                    "Which directory to resolve the path in: "
                    "'project' (default) for the working directory, "
                    "'global' for ~/.agents/ to manage global skills."
                ),
            },
        },
        "required": ["path", "content"],
    },
)
async def write_file(
    path: str,
    content: str,
    directory: str = "project",
    ctx: "AppContext | None" = None,
) -> str:
    """Write *content* to *path* after user confirmation.

    Shows a confirmation modal with the proposed file content.  The
    user must click **Confirm** for the write to proceed.

    If ``session.yolo_mode`` is enabled in config, the confirmation
    modal is skipped and the file is written immediately.
    """
    if ctx is None:
        return "Error: no context available (working directory unknown)."

    # Validate directory scope.
    err = validate_directory(directory)
    if err:
        return f"Error: {err}"

    # Resolve path and boundary root.
    resolved, root = resolve_tool_path(path, directory, ctx)

    # Boundary check — fails fast before any app interaction.
    err = check_path_boundary(resolved, root, path)
    if err:
        return err

    # Build a preview.
    existing = ""
    if os.path.isfile(resolved):
        try:
            with open(resolved, encoding="utf-8") as fh:
                existing = fh.read()
        except Exception:
            pass

    if existing:
        preview = (
            f"File: {path}\n\n"
            f"--- existing ---\n{existing}\n"
            f"--- proposed ---\n{content}\n"
            f"--- end ---"
        )
    else:
        preview = (
            f"New file: {path}\n\n"
            f"{content}"
        )

    # YOLO mode: skip the confirmation modal and write directly.
    if ctx.config is not None and ctx.config.get("session.yolo_mode", False):
        confirmed = True
    else:
        if ctx.app is None:
            return "Error: no application context available for confirmation."
        # Ask the user.
        from ui.widgets.confirm_modal import ConfirmModal

        modal = ConfirmModal(
            title=f"Write to '{path}'?",
            body=preview,
            confirm_label="Write",
        )
        confirmed = await ctx.app.push_screen_wait(modal)

    if not confirmed:
        return "Write cancelled by user."

    # Write.
    try:
        os.makedirs(os.path.dirname(resolved) or ".", exist_ok=True)
        with open(resolved, "w", encoding="utf-8") as fh:
            fh.write(content)
        size = len(content.encode("utf-8"))
        return f"Wrote {size} bytes to '{path}'."
    except OSError as exc:
        return f"Failed to write '{path}': {exc}"
