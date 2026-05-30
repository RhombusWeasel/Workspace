#!/usr/bin/env python3
"""Read a documentation file from the workspace_docs skill.

Usage:
    read_doc.py                    List available docs
    read_doc.py <doc_path>          Read a specific doc (e.g. docs/events.md)
    read_doc.py --list             List available docs
    read_doc.py --all              Print every doc concatenated (warning: large)

Called by the Workspace agent via the `run_skill` tool:

    run_skill(skill_name="workspace_docs", script="scripts/read_doc.py", args=["docs/events.md"])
"""

from __future__ import annotations

import os
import sys

# The script lives at skills/workspace_docs/scripts/read_doc.py.
# The docs are at skills/workspace_docs/docs/.
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_SKILL_DIR = os.path.dirname(_SCRIPT_DIR)
_DOCS_DIR = os.path.join(_SKILL_DIR, "docs")


def list_docs() -> str:
    """Return a formatted listing of all docs in the skill."""
    lines: list[str] = ["Available documentation files:", ""]
    try:
        entries = sorted(os.listdir(_DOCS_DIR))
    except OSError as exc:
        return f"Error listing docs: {exc}"

    for entry in entries:
        if not entry.endswith(".md"):
            continue
        path = os.path.join(_DOCS_DIR, entry)
        try:
            size = os.path.getsize(path)
        except OSError:
            size = 0
        # Read first heading for a one-line summary
        summary = _read_heading(path)
        lines.append(f"  docs/{entry:<30} {size:>6} bytes  {summary}")

    return "\n".join(lines)


def _read_heading(path: str) -> str:
    """Read the first markdown heading from a file for a summary line."""
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line.startswith("# "):
                    return line[2:].strip()
                if line:  # non-heading content before heading
                    continue
    except (OSError, UnicodeDecodeError):
        pass
    return ""


def read_doc(doc_path: str) -> str:
    """Read and return a specific doc file."""
    # Validate — only allow files inside docs/
    basename = os.path.basename(doc_path)
    target = os.path.join(_DOCS_DIR, basename)

    # Path safety: resolve and verify it stays inside _DOCS_DIR
    target = os.path.realpath(target)
    docs_real = os.path.realpath(_DOCS_DIR)
    if not target.startswith(docs_real + os.sep) and target != docs_real:
        return (
            f"Access denied: '{doc_path}' resolves outside the docs directory. "
            f"Only files in docs/ are accessible."
        )

    if not os.path.isfile(target):
        return (
            f"File not found: docs/{basename}\n\n"
            f"{list_docs()}"
        )

    try:
        with open(target, encoding="utf-8") as fh:
            return fh.read()
    except UnicodeDecodeError:
        return f"Cannot read docs/{basename} as UTF-8 text."
    except OSError as exc:
        return f"Cannot read docs/{basename}: {exc}"


def read_all_docs() -> str:
    """Concatenate all docs into one output."""
    parts: list[str] = []
    try:
        entries = sorted(os.listdir(_DOCS_DIR))
    except OSError as exc:
        return f"Error listing docs: {exc}"

    for entry in entries:
        if not entry.endswith(".md"):
            continue
        path = os.path.join(_DOCS_DIR, entry)
        try:
            with open(path, encoding="utf-8") as fh:
                content = fh.read()
        except (OSError, UnicodeDecodeError):
            continue
        parts.append(f"{'=' * 70}")
        parts.append(f"# File: docs/{entry}")
        parts.append(f"{'=' * 70}")
        parts.append(content)
        parts.append("")

    if not parts:
        return "No documentation files found."

    return "\n".join(parts)


def main() -> None:
    args = sys.argv[1:]

    if not args or args[0] in ("--list", "-l", "list"):
        print(list_docs())
        return

    if args[0] in ("--all", "-a", "all"):
        total_size = sum(
            os.path.getsize(os.path.join(_DOCS_DIR, f))
            for f in os.listdir(_DOCS_DIR)
            if f.endswith(".md") and os.path.isfile(os.path.join(_DOCS_DIR, f))
        )
        print(f"Warning: outputting all docs ({total_size:,} bytes total).")
        print(read_all_docs())
        return

    # Treat the first argument as the doc path
    # Accept both "docs/events.md" and "events.md" forms
    doc_path = args[0]
    if doc_path.startswith("docs/"):
        doc_path = doc_path[len("docs/"):]

    print(read_doc(doc_path))


if __name__ == "__main__":
    main()