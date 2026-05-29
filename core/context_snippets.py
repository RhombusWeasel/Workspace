"""Context snippets — gathers code context for inline suggestions.

Builds a compact prompt string from the currently edited file,
including lines around the cursor position with a ``<CURSOR>``
marker.

Currently single-file only.  Multi-file context (open tabs,
imported files) can be added later as the system matures.
"""

from __future__ import annotations

import os


def gather_context(
    file_content: str,
    cursor_row: int,
    cursor_col: int,
    file_path: str = "",
    lines_above: int = 40,
    lines_below: int = 20,
) -> str:
    """Build a prompt-ready context string for inline suggestions.

    Extracts lines surrounding the cursor from *file_content* and
    inserts a ``<CURSOR>`` marker at the exact cursor position.

    Parameters
    ----------
    file_content:
        The full content of the file being edited.
    cursor_row:
        0-based row index of the cursor.
    cursor_col:
        0-based column index of the cursor.
    file_path:
        Optional file path for language context in the prompt header.
    lines_above:
        Maximum number of lines to include above the cursor.
    lines_below:
        Maximum number of lines to include below the cursor.

    Returns
    -------
    str
        A formatted context string with a ``<CURSOR>`` marker at the
        current cursor position, ready to be included in an LLM prompt.
    """
    lines = file_content.split("\n")
    total_lines = len(lines)

    start = max(0, cursor_row - lines_above)
    end = min(total_lines, cursor_row + lines_below + 1)

    context_lines: list[str] = []
    for i in range(start, end):
        line = lines[i]
        if i == cursor_row:
            # Insert the CURSOR marker at the exact cursor position
            context_lines.append(
                line[:cursor_col] + "<CURSOR>" + line[cursor_col:]
            )
        else:
            context_lines.append(line)

    # Add file path header for language context
    header = ""
    if file_path:
        _, ext = os.path.splitext(file_path)
        if ext:
            header = f"File: {file_path}\n\n"

    return header + "\n".join(context_lines)