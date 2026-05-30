#!/usr/bin/env python3
"""Git status script — returns detailed repository status.

Called by the Workspace agent via the `run_skill` tool:

    run_skill(skill_name="git", script="scripts/status.py")

Returns structured output including:
- Current branch and tracking info
- Ahead/behind counts
- Stash count
- Changed files grouped by status (staged, unstaged, untracked)
"""

from __future__ import annotations

import os
import subprocess
import sys


def _run_git(*args: str) -> str:
    """Run a git command and return stdout, stripping whitespace."""
    try:
        result = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""


def _run_git_rc(*args: str) -> tuple[str, int]:
    """Run a git command and return (stdout, returncode)."""
    try:
        result = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.stdout.strip(), result.returncode
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return "", 1


def get_status() -> str:
    """Return a detailed git status report."""
    # Check if we're in a git repo
    _, rc = _run_git_rc("rev-parse", "--is-inside-work-tree")
    if rc != 0:
        return "Not a git repository."

    parts: list[str] = []

    # Branch info
    branch = _run_git("rev-parse", "--abbrev-ref", "HEAD")
    parts.append(f"Branch: {branch or '(detached HEAD)'}")

    # Detached HEAD commit
    if not branch or branch == "(detached HEAD)":
        commit = _run_git("rev-parse", "--short", "HEAD")
        parts.append(f"HEAD: {commit}")

    # Tracking info
    tracking = _run_git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    if tracking:
        parts.append(f"Tracking: {tracking}")

        # Ahead/behind
        ahead_behind = _run_git("rev-list", "--left-right", "--count", "@{u}...HEAD")
        if ahead_behind:
            left_right = ahead_behind.split()
            if len(left_right) == 2:
                behind, ahead = left_right
                if ahead != "0" or behind != "0":
                    parts.append(f"Ahead {ahead} / Behind {behind}")

    # Stash count
    stash_list = _run_git("stash", "list")
    if stash_list:
        stash_count = len(stash_list.split("\n"))
        parts.append(f"Stashes: {stash_count}")
    else:
        parts.append("Stashes: 0")

    # Porcelain status for file grouping
    porcelain = _run_git("status", "--porcelain=v1")
    staged: list[str] = []
    unstaged: list[str] = []
    untracked: list[str] = []

    if porcelain:
        for line in porcelain.split("\n"):
            if not line:
                continue
            index_status = line[0] if len(line) > 0 else " "
            worktree_status = line[1] if len(line) > 1 else " "
            filepath = line[3:] if len(line) > 3 else line.strip()

            # Index/staged changes (anything with a non-space, non-? index char)
            if index_status in "MADRC":
                staged.append(f"  {index_status} {filepath}")

            # Worktree/unstaged changes (anything with a non-space worktree char)
            if worktree_status in "MD":
                # Avoid duplicating if already staged (different status)
                unstaged.append(f"  {worktree_status} {filepath}")

            # Untracked files
            if index_status == "?" and worktree_status == "?":
                untracked.append(f"  ? {filepath}")

    parts.append("")
    parts.append(f"Staged ({len(staged)}):")
    if staged:
        parts.extend(staged)
    else:
        parts.append("  (none)")

    parts.append("")
    parts.append(f"Unstaged ({len(unstaged)}):")
    if unstaged:
        parts.extend(unstaged)
    else:
        parts.append("  (none)")

    parts.append("")
    parts.append(f"Untracked ({len(untracked)}):")
    if untracked:
        parts.extend(untracked)
    else:
        parts.append("  (none)")

    return "\n".join(parts)


def main() -> None:
    print(get_status())


if __name__ == "__main__":
    main()