"""Run command tool — executes a shell command after user confirmation.

Registered at import time via ``@register_tool()``.  Async because it
pushes a :class:`~ui.widgets.confirm_modal.ConfirmModal`.

The ``directory`` parameter controls which directory the command runs in:

- ``"project"`` (default) — the workspace working directory.
- ``"global"`` — ``~/.agents/``, allowing agents to manage global skills.
"""

from __future__ import annotations

import asyncio
import os
from typing import TYPE_CHECKING

from core.tools import register_tool
from tools._path_utils import (
    validate_directory,
    resolve_tool_cwd,
)

if TYPE_CHECKING:
    from context import AppContext

_MAX_OUTPUT = 50 * 1024  # 50 KB


@register_tool(
    name="run_command",
    tags=["system"],
    description=(
        "Run a shell command in the working directory.  The user is "
        "shown the command and must confirm before execution.  Output "
        "is captured and returned.  Paths outside the working directory "
        "are rejected."
    ),
    parameters={
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The shell command to execute.",
            },
            "directory": {
                "type": "string",
                "description": (
                    "Which directory to run the command in: "
                    "'project' (default) for the working directory, "
"'global' for ~/.agents/ to manage global skills."
                ),
            },
        },
        "required": ["command"],
    },
)
async def run_command(command: str, directory: str = "project", ctx: "AppContext | None" = None) -> str:
    """Execute *command* in a subprocess after user confirmation.

    Shows a confirmation modal with the command text.  The user must
    click **Confirm** for execution to proceed.  Runs in the working
    directory with a 30-second timeout.

    If ``session.yolo_mode`` is enabled in config, the confirmation
    modal is skipped and the command runs immediately.
    """
    if ctx is None:
        return "Error: no context available (working directory unknown)."

    # Validate directory scope.
    err = validate_directory(directory)
    if err:
        return f"Error: {err}"

    # Resolve cwd based on directory scope.
    cwd = resolve_tool_cwd(directory, ctx)

    # YOLO mode: skip the confirmation modal and run directly.
    if ctx.config is not None and ctx.config.get("session.yolo_mode", False):
        confirmed = True
    else:
        if ctx.app is None:
            return "Error: no application context available for confirmation."
        from ui.widgets.confirm_modal import ConfirmModal

        modal = ConfirmModal(
            title="Run this command?",
            body=f"Directory: {cwd}\n\n{command}",
            confirm_label="Run",
        )
        confirmed = await ctx.app.push_screen_wait(modal)

    if not confirmed:
        return "Command cancelled by user."

    # Execute.
    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=30
        )
    except asyncio.TimeoutError:
        return "Command timed out after 30 seconds."
    except OSError as exc:
        return f"Failed to run command: {exc}"

    # Build output.
    parts: list[str] = []
    if stdout:
        out_text = stdout.decode("utf-8", errors="replace")
        if len(out_text) > _MAX_OUTPUT:
            out_text = out_text[:_MAX_OUTPUT] + "\n... (output truncated)"
        parts.append(out_text)
    if stderr:
        err_text = stderr.decode("utf-8", errors="replace")
        if len(err_text) > _MAX_OUTPUT:
            err_text = err_text[:_MAX_OUTPUT] + "\n... (output truncated)"
        parts.append(f"[stderr]\n{err_text}")

    result = "\n".join(parts) if parts else "(no output)"
    return f"Exit code: {proc.returncode}\n{result}"
