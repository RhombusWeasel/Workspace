"""/skill — manage skills: install, update, remove, list.

Subcommands:

    /skill install <url>               Install from git (latest tag, global)
    /skill install <url> --version X    Install a specific tag
    /skill install <url> --local       Install to project-local tier
    /skill install <url> --subdir D   Use a subdirectory of the repo
    /skill update <name>               Update a skill to the latest tag
    /skill update <name> --version X  Update to a specific tag
    /skill update --all                Update all managed skills
    /skill remove <name>              Remove a global skill
    /skill remove <name> --local      Remove a project-local skill
    /skill list                        List all discovered skills

Registered at import time via ``@register_command()``.
"""

from __future__ import annotations

import shlex

from core.commands import register_command
from core.skill_package_manager import SkillInstallError


@register_command(name="skill", description="Manage skills: install, update, remove, list")
async def skill_cmd(app, args: str) -> str:
    """Handle /skill subcommands."""
    if not app or not hasattr(app, "context") or app.context is None:
        return "Error: skill command requires an active application context."

    from core.skill_package_manager import SkillPackageManager

    ctx = app.context
    mgr = SkillPackageManager(ctx.config, ctx.working_directory)

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
    except SkillInstallError as e:
        return f"Error: {e}"


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------


async def _install(mgr: SkillPackageManager, args: list[str]) -> str:
    """Handle /skill install."""
    if not args:
        return "Usage: /skill install <url> [--version X] [--local] [--subdir D]"

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
    return f"Installed skill '{name}' ({ver}) to {tier} tier."


async def _update(mgr: SkillPackageManager, args: list[str]) -> str:
    """Handle /skill update."""
    if not args:
        return "Usage: /skill update <name> [--version X]\n       /skill update --all"

    if args[0] == "--all":
        results = mgr.update_all()
        if not results:
            return "No managed skills to update."
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
        return f"Skill '{name}' is already up to date."
    return f"Updated skill '{name}' to {new_ver}."


async def _remove(mgr: SkillPackageManager, args: list[str]) -> str:
    """Handle /skill remove."""
    if not args:
        return "Usage: /skill remove <name> [--local]"

    name = args[0]
    local = "--local" in args

    removed = mgr.remove(name, local=local)
    if removed:
        tier = "project-local" if local else "global"
        return f"Removed skill '{name}' from {tier} tier."
    return f"Skill '{name}' not found."


def _list(mgr: SkillPackageManager) -> str:
    """Handle /skill list."""
    skills = mgr.list_skills()

    if not skills:
        return "No skills found."

    lines = ["Installed skills:", ""]
    for p in skills:
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
        "Usage: /skill <subcommand> [args]\n"
        "\n"
        "Subcommands:\n"
        "  install <url>              Install skill from git repo (latest tag)\n"
        "  install <url> --version X  Install specific tag\n"
        "  install <url> --local      Install to project-local tier\n"
        "  install <url> --subdir D   Use subdirectory from monorepo\n"
        "  update <name>              Update skill to latest tag\n"
        "  update <name> --version X  Update to specific tag\n"
        "  update --all               Update all managed skills\n"
        "  remove <name>              Remove global skill\n"
        "  remove <name> --local      Remove project-local skill\n"
        "  list                       List all discovered skills"
    )