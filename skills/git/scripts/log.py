#!/usr/bin/env python3
"""Git log script — formatted commit history.

Called by the Workspace agent via the ``run_skill`` tool:

    run_skill(skill_name="git", script="scripts/log.py")
    run_skill(skill_name="git", script="scripts/log.py", args=["20"])

Returns a formatted log with branch graph, short hashes, dates, authors,
and commit subjects.
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
            timeout=15,
        )
        return result.stdout.strip(), result.returncode
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return "", 1


def get_log(count: int = 10) -> str:
    """Return a formatted git log for the last *count* commits."""
    # Check if we're in a git repo
    _, rc = _run_git("rev-parse", "--is-inside-work-tree")
    if rc != 0:
        return "Not a git repository."

    # Branch info header
    branch, _ = _run_git("rev-parse", "--abbrev-ref", "HEAD")
    header = f"Branch: {branch or '(detached HEAD)'}"

    tracking, _ = _run_git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    if tracking:
        ahead_behind, _ = _run_git("rev-list", "--left-right", "--count", "@{u}...HEAD")
        if ahead_behind:
            l_r = ahead_behind.split()
            if len(l_r) == 2:
                header += f"  |  Tracking: {tracking}  (ahead {l_r[1]}, behind {l_r[0]})"

    # Format: hash | date | author | subject
    # Use a custom format that's easy to parse and display
    fmt = "%h|%ad|%an|%s"
    log_output, _ = _run_git(
        "log", f"-{count}",
        f"--format={fmt}",
        "--date=short",
    )

    if not log_output:
        return f"{header}\n\nNo commits yet."

    parts: list[str] = [header, ""]

    for line in log_output.split("\n"):
        if not line.strip():
            continue
        segments = line.split("|", 3)
        if len(segments) < 4:
            parts.append(f"  {line}")
            continue
        short_hash = segments[0]
        date = segments[1]
        author = segments[2]
        subject = segments[3]

        parts.append(f"  {short_hash}  {date}  {author:<15}  {subject}")

    parts.append("")
    parts.append(f"Showing last {min(count, len(log_output.split(chr(10))))} commit(s)")
    return "\n".join(parts)


def main() -> None:
    count = 10
    args = sys.argv[1:]

    if args:
        try:
            count = int(args[0])
        except ValueError:
            print(f"Invalid count: {args[0]}. Using default (10).")

    print(get_log(count))


if __name__ == "__main__":
    main()