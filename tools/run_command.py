"""Run command tool — executes a shell command after user confirmation.

Registered at import time via ``@register_tool()``.  Async because it
pushes a :class:`~ui.widgets.confirm_modal.ConfirmModal`.
"""

from __future__ import annotations

import asyncio
import os
from typing import TYPE_CHECKING

from core.tools import register_tool

if TYPE_CHECKING:
    from context import AppContext

_MAX_OUTPUT = 50 * 1024  # 50 KB


@register_tool(
    name="run_command",
    tags=["system"],
    description=(
        "Run a shell command in the working directory.  The user is "
        "shown the command and must confirm before execution.  Output "
        "is captured and returned."
    ),
    parameters={
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The shell command to execute.",
            },
        },
        "required": ["command"],
    },
)
async def run_command(command: str, ctx: "AppContext | None" = None) -> str:
    """Execute *command* in a subprocess after user confirmation.

    Shows a confirmation modal with the command text.  The user must
    click **Confirm** for execution to proceed.  Runs in the working
    directory with a 30-second timeout.
    """
    if ctx is None or ctx.app is None:
        return "Error: no application context available for confirmation."

    # Ask the user.
    from ui.widgets.confirm_modal import ConfirmModal

    modal = ConfirmModal(
        title="Run this command?",
        body=f"Directory: {ctx.working_directory}\n\n{command}",
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
            cwd=ctx.working_directory,
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
