"""Run skill tool — executes a script bundled with a skill.

Looks up a skill by name and runs a script from its directory.
Registered at import time via ``@register_tool()``.

Python scripts (``.py``) are executed **in-process** via :func:`exec`,
with a ``context`` namespace that provides direct access to the
:class:`~context.AppContext` (vault, config, etc.).  Non-Python scripts
fall back to :func:`subprocess.run`.
"""

from __future__ import annotations

import io
import os
import subprocess
import sys
from typing import TYPE_CHECKING

from core.tools import register_tool
from core.skills import skill_manager

if TYPE_CHECKING:
    from context import AppContext

_EXEC_TIMEOUT = 30


@register_tool(
    name="run_skill",
    tags=["skills"],
    description=(
        "Execute a script that is bundled with a registered skill. "
        "The script path is relative to the skill's base directory."
    ),
    parameters={
        "type": "object",
        "properties": {
            "skill_name": {
                "type": "string",
                "description": "Name of the skill whose script to run.",
            },
            "script": {
                "type": "string",
                "description": (
                    "Path to the script, relative to the skill's base directory "
                    "(e.g. 'scripts/analyze.sh')."
                ),
            },
            "args": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional command-line arguments for the script.",
            },
        },
        "required": ["skill_name", "script"],
    },
)
def run_skill(
    skill_name: str,
    script: str,
    args: list[str] | None = None,
    ctx: "AppContext | None" = None,
) -> str:
    """Execute *script* from *skill_name*'s directory.

    The script is resolved relative to the skill's ``base_dir``.
    Runs in the working directory with a configurable timeout.
    """
    skill = skill_manager.get_skill(skill_name)
    if skill is None:
        available = ", ".join(skill_manager.list_skills())
        return (
            f"Skill '{skill_name}' not found. "
            f"Available skills: {available}"
        )

    import os
    script_path = os.path.join(skill.base_dir, script)
    if not os.path.isfile(script_path):
        return f"Script not found: '{script}' in skill '{skill_name}'."

    wd = ctx.working_directory if ctx else os.getcwd()

    if script_path.endswith(".py"):
        return _run_python_script(script_path, args, ctx, wd)
    else:
        return _run_subprocess_script(script_path, args, wd)


def _run_python_script(
    script_path: str,
    args: list[str] | None,
    ctx: AppContext | None,
    wd: str,
) -> str:
    """Execute a Python script in-process with access to the app context.

    The script receives a ``context`` global variable holding the
    :class:`~context.AppContext` (or ``None`` if unavailable) and an
    ``args`` global holding the argument list.  ``sys.argv`` is also set
    for backward compatibility with scripts that read it directly.

    Standard output is captured and returned as a string.
    """
    # Save state we'll temporarily replace
    old_cwd = os.getcwd()
    old_argv = sys.argv
    old_stdout = sys.stdout

    captured = io.StringIO()
    sys.stdout = captured
    os.chdir(wd)
    sys.argv = [script_path] + (args or [])

    try:
        namespace: dict = {
            "__name__": "__main__",
            "__file__": script_path,
            "context": ctx,
            "args": args or [],
        }

        with open(script_path, encoding="utf-8") as fh:
            code = compile(fh.read(), script_path, "exec")
            exec(code, namespace)

        output = captured.getvalue().strip()
    except Exception as exc:
        output = f"Script error: {exc}"
    finally:
        sys.stdout = old_stdout
        sys.argv = old_argv
        os.chdir(old_cwd)

    if not output:
        output = "(no output)"

    return output


def _run_subprocess_script(
    script_path: str,
    args: list[str] | None,
    wd: str,
) -> str:
    """Execute a non-Python script as a subprocess (fallback)."""
    cmd = [script_path] + (args or [])

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=_EXEC_TIMEOUT,
            cwd=wd,
        )
    except subprocess.TimeoutExpired:
        return f"Script timed out after {_EXEC_TIMEOUT} seconds."
    except OSError as exc:
        return f"Failed to run script: {exc}"

    output = result.stdout.strip()
    if result.stderr.strip():
        output += f"\n[stderr]\n{result.stderr.strip()}"

    if not output:
        output = "(no output)"

    return f"Exit code: {result.returncode}\n{output}"
