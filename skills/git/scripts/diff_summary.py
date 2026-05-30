#!/usr/bin/env python3
"""Git diff summary script — groups changes by staged, unstaged, and untracked.

Called by the Workspace agent via the ``run_skill`` tool:

    run_skill(skill_name="git", script="scripts/diff_summary.py")

Returns a summary of all changes with file counts and brief descriptions
of what changed in each file.
"""

from __future__ import annotations

import os
import subprocess
import sys


def _run_git(*args: str) -> tuple[str, int]:
    """Run a git command and return (stdout, returncode)."""
    try:
        result = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            timeout=15,
        )
        return result.stdout.strip(), result.returncode
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return "", 1


def _diffstat(output: str) -> str:
    """Format diff output into a brief stat line per file."""
    if not output:
        return ""
    lines = output.split("\n")
    files_changed = set()
    insertions = 0
    deletions = 0

    for line in lines:
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("@@"):
            continue
        if line.startswith("diff "):
            # Extract filename from diff header
            parts = line.split(" b/")
            if len(parts) >= 2:
                files_changed.add(parts[-1])
            continue
        if line.startswith("+") and not line.startswith("+++"):
            insertions += 1
        elif line.startswith("-") and not line.startswith("---"):
            deletions += 1

    if not files_changed:
        return ""

    parts: list[str] = []
    for f in sorted(files_changed):
        parts.append(f"  {f}")
    parts.append("")
    parts.append(f"  {len(files_changed)} file(s), +{insertions}/-{deletions}")
    return "\n".join(parts)


def get_diff_summary() -> str:
    """Return a grouped summary of all git changes."""
    # Check if we're in a git repo
    _, rc = _run_git("rev-parse", "--is-inside-work-tree")
    if rc != 0:
        return "Not a git repository."

    parts: list[str] = []

    # --- Staged changes ---
    staged_diff, _ = _run_git("diff", "--cached", "--stat")
    staged_names, _ = _run_git("diff", "--cached", "--name-only")

    parts.append(f"Staged ({len(staged_names.split(chr(10))) if staged_names.strip() else 0}):")
    if staged_names.strip():
        for name in sorted(staged_names.split("\n")):
            if name.strip():
                parts.append(f"  {name}")
        if staged_diff:
            # Extract the summary line (last line of --stat)
            stat_lines = staged_diff.strip().split("\n")
            summary = stat_lines[-1] if stat_lines else ""
            if summary.strip():
                parts.append(f"  {summary.strip()}")
    else:
        parts.append("  (none)")

    parts.append("")

    # --- Unstaged changes ---
    unstaged_diff, _ = _run_git("diff", "--stat")
    unstaged_names, _ = _run_git("diff", "--name-only")

    parts.append(f"Unstaged ({len(unstaged_names.split(chr(10))) if unstaged_names.strip() else 0}):")
    if unstaged_names.strip():
        for name in sorted(unstaged_names.split("\n")):
            if name.strip():
                parts.append(f"  {name}")
        if unstaged_diff:
            stat_lines = unstaged_diff.strip().split("\n")
            summary = stat_lines[-1] if stat_lines else ""
            if summary.strip():
                parts.append(f"  {summary.strip()}")
    else:
        parts.append("  (none)")

    parts.append("")

    # --- Untracked files ---
    untracked_raw, _ = _run_git("ls-files", "--others", "--exclude-standard")
    untracked_files = [f for f in untracked_raw.split("\n") if f.strip()]

    parts.append(f"Untracked ({len(untracked_files)}):")
    if untracked_files:
        for name in sorted(untracked_files):
            parts.append(f"  {name}")
    else:
        parts.append("  (none)")

    return "\n".join(parts)


def main() -> None:
    print(get_diff_summary())


if __name__ == "__main__":
    main()