"""/help — show available slash commands.

Lists all registered slash commands with their descriptions.

Registered at import time via ``@register_command()``.
"""

from __future__ import annotations

from core.commands import register_command


@register_command(name="help", description="Show available slash commands")
async def help_cmd(app, args: str) -> str:
    """List all registered slash commands with their descriptions."""
    from core.commands import get_commands

    cmds = get_commands()
    if not cmds:
        return "No commands registered."

    lines = ["Available commands:"]
    for name in sorted(cmds):
        cmd = cmds[name]
        lines.append(f"  /{name}  —  {cmd.description}")
    return "\n".join(lines)