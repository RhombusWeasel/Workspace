"""Write file tool — creates or overwrites a file after user confirmation.

Registered at import time via ``@register_tool()``.  Async because it
pushes a :class:`~ui.widgets.confirm_modal.ConfirmModal`.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from core.tools import register_tool

if TYPE_CHECKING:
    from context import AppContext


@register_tool(
    name="write_file",
    tags=["files"],
    description=(
        "Write content to a file.  Paths outside the working directory "
        "are rejected.  The user is shown a diff and must confirm before "
        "the write happens."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": (
                    "Absolute or relative path for the new file. "
                    "Must resolve inside the working directory."
                ),
            },
            "content": {
                "type": "string",
                "description": "The exact text content to write to the file.",
            },
        },
        "required": ["path", "content"],
    },
)
async def write_file(path: str, content: str, ctx: "AppContext | None" = None) -> str:
    """Write *content* to *path* after user confirmation.

    Shows a confirmation modal with the proposed file content.  The
    user must click **Confirm** for the write to proceed.

    If ``session.yolo_mode`` is enabled in config, the confirmation
    modal is skipped and the file is written immediately.
    """
    if ctx is None:
        return "Error: no context available (working directory unknown)."

    wd = os.path.realpath(ctx.working_directory)

    # Resolve path.
    if os.path.isabs(path):
        resolved = os.path.realpath(path)
    else:
        resolved = os.path.realpath(os.path.join(wd, path))

    # Boundary check — fails fast before any app interaction.
    if not resolved.startswith(wd + os.sep) and resolved != wd:
        return (
            f"Access denied: '{path}' resolves outside the working directory "
            f"({wd})."
        )

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
