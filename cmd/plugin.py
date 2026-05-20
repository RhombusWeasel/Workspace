"""/plugin — manage plugins: install, update, remove, list.

Subcommands:

    /plugin install <url>               Install from git (latest tag, global)
    /plugin install <url> --version X    Install a specific tag
    /plugin install <url> --local       Install to project-local tier
    /plugin install <url> --subdir D   Use a subdirectory of the repo
    /plugin update <name>               Update a plugin to the latest tag
    /plugin update <name> --version X  Update to a specific tag
    /plugin update --all                Update all managed plugins
    /plugin remove <name>              Remove a global plugin
    /plugin remove <name> --local      Remove a project-local plugin
    /plugin list                        List all discovered plugins

Registered at import time via ``@register_command()``.
"""

from __future__ import annotations

import shlex

from core.commands import register_command
from core.plugin_manager import PluginError


@register_command(name="plugin", description="Manage plugins: install, update, remove, list")
async def plugin_cmd(app, args: str) -> str:
    """Handle /plugin subcommands."""
    if not app or not hasattr(app, "context") or app.context is None:
        return "Error: plugin command requires an active application context."

    from core.plugin_manager import PluginManager

    ctx = app.context
    mgr = PluginManager(ctx.config, ctx.working_directory)

    parts = shlex.split(args) if args else []

    if not parts:
        return _usage()

    subcommand = parts[0].lower()
    sub_args = parts[1:]

    try:
        if subcommand == "install":
            return await _install(mgr, sub_args)
        elif subcommand == "update":
            return await _update(mgr, sub_args)
        elif subcommand == "remove":
            return await _remove(mgr, sub_args)
        elif subcommand == "list":
            return _list(mgr)
        else:
            return f"Unknown subcommand: {subcommand}\n\n{_usage()}"
    except PluginError as e:
        return f"Error: {e}"


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------


async def _install(mgr: PluginManager, args: list[str]) -> str:
    """Handle /plugin install."""
    if not args:
        return "Usage: /plugin install <url> [--version X] [--local] [--subdir D]"

    url = args[0]
    version = None
    local = False
    subdir = None

    i = 1
    while i < len(args):
        if args[i] == "--version" and i + 1 < len(args):
            version = args[i + 1]
            i += 2
        elif args[i] == "--local":
            local = True
            i += 1
        elif args[i] == "--subdir" and i + 1 < len(args):
            subdir = args[i + 1]
            i += 2
        else:
            i += 1

    name = mgr.install(url, version=version, local=local, subdir=subdir)
    tier = "project-local" if local else "global"
    ver = version or "latest"
    return f"Installed plugin '{name}' ({ver}) to {tier} tier."


async def _update(mgr: PluginManager, args: list[str]) -> str:
    """Handle /plugin update."""
    if not args:
        return "Usage: /plugin update <name> [--version X]\n       /plugin update --all"

    if args[0] == "--all":
        results = mgr.update_all()
        if not results:
            return "No managed plugins to update."
        lines = []
        for name, new_ver in results.items():
            if new_ver is None:
                lines.append(f"  {name}: already up to date")
            else:
                lines.append(f"  {name}: updated to {new_ver}")
        return "Update results:\n" + "\n".join(lines)

    name = args[0]
    version = None
    i = 1
    while i < len(args):
        if args[i] == "--version" and i + 1 < len(args):
            version = args[i + 1]
            i += 2
        else:
            i += 1

    new_ver = mgr.update(name, version=version)
    if new_ver is None:
        return f"Plugin '{name}' is already up to date."
    return f"Updated plugin '{name}' to {new_ver}."


async def _remove(mgr: PluginManager, args: list[str]) -> str:
    """Handle /plugin remove."""
    if not args:
        return "Usage: /plugin remove <name> [--local]"

    name = args[0]
    local = "--local" in args

    removed = mgr.remove(name, local=local)
    if removed:
        tier = "project-local" if local else "global"
        return f"Removed plugin '{name}' from {tier} tier."
    return f"Plugin '{name}' not found."


def _list(mgr: PluginManager) -> str:
    """Handle /plugin list."""
    plugins = mgr.list_plugins()

    if not plugins:
        return "No plugins found."

    lines = ["Installed plugins:", ""]
    for p in plugins:
        # Status indicators
        if p.tier == "missing":
            status = "✗ missing"
        elif not p.enabled:
            status = "○ disabled"
        else:
            status = "● enabled"

        # Version info
        if p.version:
            ver = p.version
        elif p.managed:
            ver = "?"
        else:
            ver = "-"

        # Source info
        if p.source:
            source = f"  source: {p.source}"
        else:
            source = ""

        # Tier
        tier_label = {
            "bundled": "(bundled)",
            "global": "~/.agents",
            "project": "project-local",
            "missing": "(missing)",
        }.get(p.tier, p.tier)

        lines.append(f"  {p.name:<20} {ver:<10} {status:<14} {tier_label}{source}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Usage
# ---------------------------------------------------------------------------


def _usage() -> str:
    """Return usage help."""
    return (
        "Usage: /plugin <subcommand> [args]\n"
        "\n"
        "Subcommands:\n"
        "  install <url>              Install plugin from git repo (latest tag)\n"
        "  install <url> --version X  Install specific tag\n"
        "  install <url> --local      Install to project-local tier\n"
        "  install <url> --subdir D   Use subdirectory from monorepo\n"
        "  update <name>              Update plugin to latest tag\n"
        "  update <name> --version X  Update to specific tag\n"
        "  update --all               Update all managed plugins\n"
        "  remove <name>              Remove global plugin\n"
        "  remove <name> --local      Remove project-local plugin\n"
        "  list                       List all discovered plugins"
    )