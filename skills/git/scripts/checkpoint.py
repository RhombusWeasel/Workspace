#!/usr/bin/env python3
"""Git checkpoint script — create, list, and restore WIP checkpoints.

Checkpoints are WIP commits tagged with a ``workspace-checkpoint/`` prefix.
They let the agent create a rollback point before making potentially
destructive changes, and restore to that point if something goes wrong.

Called by the Workspace agent via the ``run_skill`` tool:

    run_skill(skill_name="git", script="scripts/checkpoint.py", args=["create", "before refactor"])
    run_skill(skill_name="git", script="scripts/checkpoint.py", args=["list"])
    run_skill(skill_name="git", script="scripts/checkpoint.py", args=["restore", "before-refactor"])
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from datetime import datetime


def _run_git(*args: str) -> tuple[str, int, str]:
    """Run a git command and return (stdout, returncode, stderr)."""
    try:
        result = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            timeout=15,
        )
        return result.stdout.strip(), result.returncode, result.stderr.strip()
    except subprocess.TimeoutExpired:
        return "", 1, "command timed out"
    except FileNotFoundError:
        return "", 1, "git not found"


def _sanitize_tag_name(message: str) -> str:
    """Convert a message into a valid git tag name component.

    Replaces non-alphanumeric characters with hyphens, collapses
    multiple hyphens, strips leading/trailing hyphens, and lowercases.
    """
    # Replace spaces and non-alphanumeric with hyphens
    tag = re.sub(r"[^a-zA-Z0-9]", "-", message)
    # Collapse multiple hyphens
    tag = re.sub(r"-+", "-", tag)
    # Strip leading/trailing hyphens and lowercase
    tag = tag.strip("-").lower()
    # Truncate to reasonable length
    tag = tag[:60]
    return tag


def create_checkpoint(message: str) -> str:
    """Create a WIP checkpoint commit with a tag.

    Strategy:
    1. Stage all changes (tracked + untracked)
    2. Create a WIP commit
    3. Tag with workspace-checkpoint/<sanitized-message>

    If the working tree is clean, just tag the current HEAD.
    """
    # Check if we're in a git repo
    _, rc, _ = _run_git("rev-parse", "--is-inside-work-tree")
    if rc != 0:
        return "Not a git repository."

    tag_name = f"workspace-checkpoint/{_sanitize_tag_name(message)}"

    # Check if tag already exists
    _, rc, _ = _run_git("rev-parse", tag_name)
    if rc == 0:
        # Tag exists — add a numeric suffix
        counter = 2
        while True:
            alt_tag = f"{tag_name}-{counter}"
            _, rc, _ = _run_git("rev-parse", alt_tag)
            if rc != 0:
                tag_name = alt_tag
                break
            counter += 1
            if counter > 100:
                return "Error: too many checkpoints with this name."

    # Check for working tree changes
    status_out, _, _ = _run_git("status", "--porcelain")
    has_changes = bool(status_out.strip())

    if has_changes:
        # Stage everything (including untracked)
        _, rc, err = _run_git("add", "-A")
        if rc != 0:
            return f"Error staging files: {err}"

        # Create WIP commit
        commit_msg = f"wip: checkpoint — {message}"
        _, rc, err = _run_git("commit", "-m", commit_msg)
        if rc != 0:
            return f"Error creating checkpoint commit: {err}"
    else:
        # Clean working tree — just tag HEAD
        pass

    # Create the tag with timestamp
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    tag_msg = f"Workspace checkpoint ({timestamp}): {message}"
    _, rc, err = _run_git("tag", "-a", tag_name, "-m", tag_msg)
    if rc != 0:
        # Tag creation failed — undo the WIP commit if we made one
        if has_changes:
            _run_git("reset", "--soft", "HEAD~1")
            _run_git("reset", "HEAD")
        return f"Error creating tag: {err}"

    result_parts = [f"Checkpoint created: {tag_name}"]
    if has_changes:
        result_parts.append("  (WIP commit created with staged changes)")
    else:
        result_parts.append("  (tagged current HEAD — working tree was clean)")
    result_parts.append(f"  Message: {message}")
    result_parts.append("")
    result_parts.append("To restore: run_skill(skill_name='git', script='scripts/checkpoint.py', args=['restore', '" + tag_name.split("/", 1)[1] + "'])")

    return "\n".join(result_parts)


def list_checkpoints() -> str:
    """List all workspace-checkpoint tags with dates and messages."""
    # Check if we're in a git repo
    _, rc, _ = _run_git("rev-parse", "--is-inside-work-tree")
    if rc != 0:
        return "Not a git repository."

    output, rc, _ = _run_git(
        "tag", "-l", "workspace-checkpoint/*",
        "--format=%(refname:short)|%(creatordate:short)|%(subject)"
    )

    if not output:
        return "No checkpoints found."

    lines = output.split("\n")
    parts: list[str] = ["Checkpoints:", ""]

    for line in lines:
        line = line.strip()
        if not line:
            continue
        # Parse: tag-name|date|subject
        segments = line.split("|", 2)
        tag = segments[0] if len(segments) > 0 else "?"
        date = segments[1] if len(segments) > 1 else "?"
        subject = segments[2] if len(segments) > 2 else ""

        # Short display name (strip workspace-checkpoint/ prefix)
        short_name = tag.replace("workspace-checkpoint/", "")
        parts.append(f"  {short_name:<40} {date}  {subject}")

    parts.append("")
    parts.append(f"Total: {len([l for l in lines if l.strip()])} checkpoint(s)")
    return "\n".join(parts)


def restore_checkpoint(tag_fragment: str) -> str:
    """Restore the working tree to a checkpoint state.

    Strategy:
    1. Find the matching tag (exact or partial match)
    2. Reset --hard to the tagged commit
    3. Delete the checkpoint tag
    """
    # Try exact match first
    full_tag = f"workspace-checkpoint/{tag_fragment}"
    _, rc, _ = _run_git("rev-parse", full_tag)

    if rc != 0:
        # Try partial match — find tags containing the fragment
        output, _, _ = _run_git("tag", "-l", f"workspace-checkpoint/*{tag_fragment}*")
        if output:
            matches = [m.strip() for m in output.split("\n") if m.strip()]
            if len(matches) == 1:
                full_tag = matches[0]
            elif len(matches) > 1:
                short_names = [m.replace("workspace-checkpoint/", "") for m in matches]
                return (
                    f"Multiple checkpoints match '{tag_fragment}':\n"
                    + "\n".join(f"  {n}" for n in short_names)
                    + "\n\nPlease specify a more precise name."
                )
            else:
                return f"No checkpoint matching '{tag_fragment}' found."
        else:
            return f"No checkpoint matching '{tag_fragment}' found."

    # Warn about uncommitted changes
    status_out, _, _ = _run_git("status", "--porcelain")
    if status_out.strip():
        return (
            "Warning: you have uncommitted changes that will be lost.\n"
            "Stash or commit them first, or use run_command with "
            "'git checkout -- .' to discard them, then try again."
        )

    # Get short hash for display
    short_hash, _, _ = _run_git("rev-parse", "--short", full_tag)

    # Reset to the checkpoint
    _, rc, err = _run_git("reset", "--hard", full_tag)
    if rc != 0:
        return f"Error restoring checkpoint: {err}"

    # Delete checkpoint tag (one-time use)
    _run_git("tag", "-d", full_tag)

    return (
        f"Restored to checkpoint: {full_tag}\n"
        f"  Commit: {short_hash}\n"
        f"  Working tree is now at the checkpoint state.\n"
        f"  Checkpoint tag has been removed."
    )


def main() -> None:
    args = sys.argv[1:]

    if not args or args[0] in ("--help", "-h", "help"):
        print(
            "Git Checkpoint — create, list, and restore safety checkpoints\n"
            "\n"
            "Usage:\n"
            "  checkpoint.py create <message>   Create a checkpoint\n"
            "  checkpoint.py list                List all checkpoints\n"
            "  checkpoint.py restore <name>      Restore a checkpoint\n"
        )
        return

    command = args[0]

    if command == "create":
        if len(args) < 2:
            print("Error: checkpoint create requires a message argument.")
            print('Usage: checkpoint.py create "before refactor"')
            sys.exit(1)
        message = " ".join(args[1:])
        print(create_checkpoint(message))

    elif command == "list":
        print(list_checkpoints())

    elif command == "restore":
        if len(args) < 2:
            print("Error: checkpoint restore requires a name argument.")
            print("Usage: checkpoint.py restore before-refactor")
            sys.exit(1)
        name = args[1]
        print(restore_checkpoint(name))

    else:
        print(f"Unknown command: {command}")
        print("Commands: create, list, restore")
        sys.exit(1)


if __name__ == "__main__":
    main()