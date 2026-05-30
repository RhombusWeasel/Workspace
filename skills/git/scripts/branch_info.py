#!/usr/bin/env python3
"""Git branch info script — current branch, tracking, and remote details.

Called by the Workspace agent via the ``run_skill`` tool:

    run_skill(skill_name="git", script="scripts/branch_info.py")

Returns detailed info about the current branch including tracking
status, ahead/behind counts, and remote configuration.
"""

from __future__ import annotations

import subprocess
import sys


def _run_git(*args: str) -> tuple[str, int]:
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


def get_branch_info() -> str:
    """Return detailed information about the current branch."""
    # Check if we're in a git repo
    _, rc = _run_git("rev-parse", "--is-inside-work-tree")
    if rc != 0:
        return "Not a git repository."

    parts: list[str] = []

    # Current branch
    branch, _ = _run_git("rev-parse", "--abbrev-ref", "HEAD")
    if not branch:
        # Detached HEAD
        commit, _ = _run_git("rev-parse", "--short", "HEAD")
        parts.append(f"HEAD: (detached) at {commit}")
        return "\n".join(parts)

    parts.append(f"Branch: {branch}")

    # Current commit
    commit, _ = _run_git("rev-parse", "--short", "HEAD")
    full_commit, _ = _run_git("rev-parse", "HEAD")
    parts.append(f"Commit:  {commit}  ({full_commit[:12]}...)")

    # Tracking branch
    tracking, _ = _run_git(
        "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"
    )
    if tracking:
        parts.append(f"Tracking: {tracking}")

        # Ahead/behind
        ahead_behind, _ = _run_git(
            "rev-list", "--left-right", "--count", "@{u}...HEAD"
        )
        if ahead_behind:
            l_r = ahead_behind.split()
            if len(l_r) == 2:
                behind, ahead = l_r
                parts.append(f"Ahead: {ahead}  Behind: {behind}")
    else:
        parts.append("Tracking: (none — no upstream set)")

    # Remote info
    remote, _ = _run_git("remote")
    if remote:
        remotes = [r.strip() for r in remote.split("\n") if r.strip()]
        parts.append(f"\nRemotes ({len(remotes)}):")
        for r_name in remotes:
            url, _ = _run_git("remote", "get-url", r_name)
            parts.append(f"  {r_name}: {url}")
    else:
        parts.append("\nRemotes: (none)")

    # All local branches
    branches_raw, _ = _run_git("branch", "--format=%(refname:short)")
    if branches_raw:
        branches = [b.strip() for b in branches_raw.split("\n") if b.strip()]
        parts.append(f"\nLocal branches ({len(branches)}):")
        for b in branches:
            marker = " *" if b == branch else "  "
            parts.append(f"{marker} {b}")

    # Recent tags
    tags_raw, _ = _run_git("tag", "-l", "--sort=-creatordate", "--format=%(refname:short)")
    if tags_raw:
        tags = [t.strip() for t in tags_raw.split("\n") if t.strip()][:5]
        parts.append(f"\nRecent tags:")
        for t in tags:
            parts.append(f"  {t}")
        if len(tags_raw.split("\n")) > 5:
            parts.append(f"  ... and {len(tags_raw.split(chr(10))) - 5} more")

    return "\n".join(parts)


def main() -> None:
    print(get_branch_info())


if __name__ == "__main__":
    main()