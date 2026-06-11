"""Edit file tool — performs targeted search/replace edits after user confirmation.

Registered at import time via ``@register_tool()``.  Async because it
pushes a :class:`~ui.widgets.confirm_modal.ConfirmModal`.

Each edit specifies a ``search`` string and a ``replace`` string.  The
tool finds ``search`` in the file and replaces it with ``replace``.
Edits are applied in order, so each subsequent edit operates on the
result of the prior one.

Uniqueness check
~~~~~~~~~~~~~~~~
If a ``search`` string appears more than once in the file (at the time
the edit is applied), the edit is **rejected** and no changes are made.
The returned error message includes the line numbers of every match so
the agent can refine its search string and retry.
"""

from __future__ import annotations

import difflib
import os
from typing import TYPE_CHECKING

from core.tools import register_tool

if TYPE_CHECKING:
    from context import AppContext


def _find_occurrences(text: str, search: str) -> list[int]:
    """Return 1-indexed line numbers where *search* begins in *text*.

    Uses raw string searching (``str.find``) so that matches are
    consistent with ``str.replace``, which operates on the raw text
    rather than on split lines.
    """
    hits: list[int] = []
    start = 0
    while True:
        pos = text.find(search, start)
        if pos == -1:
            break
        # Convert character offset to 1-indexed line number.
        line_num = text[:pos].count("\n") + 1
        hits.append(line_num)
        start = pos + 1
    return hits


def _count_occurrences(text: str, search: str) -> int:
    """Count non-overlapping occurrences of *search* in *text*."""
    count = 0
    if not search:
        return 0
    start = 0
    while True:
        pos = text.find(search, start)
        if pos == -1:
            break
        count += 1
        start = pos + len(search)
    return count


def _apply_edits(content: str, edits: list[dict]) -> tuple[str | None, str]:
    """Apply a list of search/replace edits to *content*.

    On success, returns ``(new_content, diff_text)``.
    On failure, returns ``(None, error_message)``.
    """
    current = content
    for idx, edit in enumerate(edits, start=1):
        search = edit["search"]
        replace = edit["replace"]

        # Reject empty search strings — they match everywhere.
        if not search:
            return (
                None,
                f"Edit {idx} failed: search string is empty. "
                f"Provide a non-empty search string.",
            )

        count = _count_occurrences(current, search)
        if count == 0:
            return (
                None,
                f"Edit {idx} failed: search string not found in file. "
                f"The file may have changed since you last read it. "
                f"Try reading the file again and adjusting your search string.",
            )
        if count > 1:
            hits = _find_occurrences(current, search)
            line_list = ", ".join(str(h) for h in hits)
            return (
                None,
                f"Edit {idx} failed: search string is not unique — found "
                f"{count} occurrences starting at lines {line_list}. "
                f"Provide more surrounding context in the search string "
                f"to make it unique, then retry.",
            )

        current = current.replace(search, replace, 1)

    # Success — build a unified diff for the preview.
    old_lines = content.splitlines(keepends=True)
    new_lines = current.splitlines(keepends=True)
    diff_lines = list(
        difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile="original",
            tofile="edited",
        )
    )
    diff_text = "".join(diff_lines)
    return current, diff_text


def _plural_edits(n: int) -> str:
    """Return a human-readable count of edits."""
    return f"{n} edit" if n == 1 else f"{n} edits"


@register_tool(
    name="edit_file",
    tags=["files"],
    description=(
        "Perform targeted search/replace edits on an existing file. "
        "Each edit specifies a 'search' string (must be unique in the file) "
        "and a 'replace' string.  Edits are applied in order.  "
        "The user is shown a diff and must confirm before changes are saved. "
        "Paths outside the working directory are rejected."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": (
                    "Absolute or relative path to the file to edit. "
                    "Must resolve inside the working directory."
                ),
            },
            "edits": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "search": {
                            "type": "string",
                            "description": (
                                "The exact text to find.  Must be unique in "
                                "the file at the time this edit is applied "
                                "(i.e. after any prior edits)."
                            ),
                        },
                        "replace": {
                            "type": "string",
                            "description": "The text to replace the search match with.",
                        },
                    },
                    "required": ["search", "replace"],
                },
                "description": (
                    "A list of search/replace pairs to apply in order.  "
                    "Each search string must be unique in the file; "
                    "if it's not, the edit fails and returns an error "
                    "with the line numbers of all matches so you can "
                    "refine your search string."
                ),
            },
        },
        "required": ["path", "edits"],
    },
)
async def edit_file(
    path: str,
    edits: list[dict],
    ctx: "AppContext | None" = None,
) -> str:
    """Apply targeted search/replace edits to *path* after user confirmation.

    * Edits are applied sequentially — each edit sees the result of prior ones.
    * If any ``search`` string is not found or is not unique, the entire
      operation is aborted with an informative error message.
    * The user is shown a unified diff and must confirm before the file
      is written.
    """
    if ctx is None:
        return "Error: no context available (working directory unknown)."

    wd = os.path.realpath(ctx.working_directory)

    # Resolve path.
    if os.path.isabs(path):
        resolved = os.path.realpath(path)
    else:
        resolved = os.path.realpath(os.path.join(wd, path))

    # Boundary check.
    if not resolved.startswith(wd + os.sep) and resolved != wd:
        return (
            f"Access denied: '{path}' resolves outside the working directory "
            f"({wd})."
        )

    # Must be an existing regular file.
    if not os.path.isfile(resolved):
        return f"Cannot edit: '{path}' is not an existing regular file."

    # Read current content.
    try:
        with open(resolved, encoding="utf-8") as fh:
            original = fh.read()
    except OSError as exc:
        return f"Cannot read '{path}': {exc}"

    # Apply edits.
    result = _apply_edits(original, edits)
    if result[0] is None:
        # Error case: result[1] is the error message.
        return result[1]

    new_content, diff_text = result

    # Nothing to do?
    if new_content == original:
        return f"No changes to make — the search and replace strings are identical in '{path}'."

    if ctx.app is None:
        return "Error: no application context available for confirmation."

    # Show the diff to the user.
    from ui.widgets.confirm_modal import ConfirmModal

    preview = f"File: {path}\n\n{diff_text}"
    modal = ConfirmModal(
        title=f"Edit '{path}'?",
        body=preview,
        confirm_label="Apply Edits",
    )
    confirmed = await ctx.app.push_screen_wait(modal)

    if not confirmed:
        return "Edit cancelled by user."

    # Write the modified content.
    try:
        with open(resolved, "w", encoding="utf-8") as fh:
            fh.write(new_content)
        return f"Applied {_plural_edits(len(edits))} to '{path}'."
    except OSError as exc:
        return f"Failed to write '{path}': {exc}"