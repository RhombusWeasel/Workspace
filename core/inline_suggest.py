"""Inline suggestion engine — fast code completions (single or multi-line).

Provides the core logic for generating inline code suggestions:
building a focused prompt, calling the LLM directly (without the
Agent / tool-calling loop), and extracting the completion text
from the response.

Message redaction is handled automatically by the
:class:`~core.providers.base.BaseProvider` — every call to
:meth:`provider.chat` scrubs secrets before they leave the process.

Designed for low latency — uses a non-streaming ``chat()`` call with
a concise system prompt.  Config defaults are registered via
:func:`~core.config.register_defaults` so they flow through bootstrap.

The :class:`~ui.workspace.file_editor.FileEditor` drives this module
via its ``_fetch_suggestion`` method, which is triggered both
automatically (after a configurable pause) and manually (``Ctrl+A``).

Single-line suggestions appear as ghost text in the editor.  Multi-line
suggestions show the first line inline and the full suggestion in a
docked :class:`~ui.workspace.suggestion_overlay.SuggestionOverlay`.
Both are accepted with ``Ctrl+F`` and dismissed with ``Escape``.
"""

from __future__ import annotations

import re

from core.providers.base import BaseProvider, Message
from core.config import register_defaults

# ---------------------------------------------------------------------------
# Config defaults
# ---------------------------------------------------------------------------

register_defaults(
    {
        "inline_suggest": {
            "enabled": True,
            "model": "",
            "delay_ms": 400,
            "context_lines_above": 40,
            "context_lines_below": 20,
            "max_suggestion_lines": 8,
        },
    }
)


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = (
    "You are a code completion assistant. Complete the code at the <CURSOR> "
    "marker.\n\n"
    "Output ONLY the raw completion text starting from the cursor position. "
    "This may span multiple lines if a natural completion requires it. "
    "Keep completions brief — typically 1–3 lines, maximum 10.\n\n"
    "Do not include:\n"
    "- Any text before the cursor\n"
    "- Explanations, comments, or reasoning\n"
    "- Markdown code fences or formatting\n\n"
    "If you cannot determine a meaningful completion, output nothing."
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def get_inline_suggestion(
    provider: BaseProvider,
    model: str,
    file_path: str,
    file_content: str,
    cursor_row: int,
    cursor_col: int,
    context_lines_above: int = 40,
    context_lines_below: int = 20,
    max_suggestion_lines: int = 8,
) -> str | None:
    """Request a code completion from the LLM.

    Returns the completion text (may contain newlines for multi-line
    completions), or ``None`` if no suggestion could be generated.

    Uses a direct ``provider.chat()`` call — no Agent, no tools,
    no streaming.  This minimizes latency for interactive completions.
    Messages are redacted automatically by the provider's base class.
    """
    from core.context_snippets import gather_context

    context = gather_context(
        file_content=file_content,
        cursor_row=cursor_row,
        cursor_col=cursor_col,
        file_path=file_path,
        lines_above=context_lines_above,
        lines_below=context_lines_below,
    )

    messages = [
        Message(role="system", content=_SYSTEM_PROMPT),
        Message(role="user", content=context),
    ]

    try:
        response = await provider.chat(messages, model)
    except Exception:
        return None

    raw = response.content.strip()
    if not raw:
        return None

    # Determine the text on the current line before the cursor so we
    # can detect (and strip) cases where the model repeats it.
    file_lines = file_content.split("\n")
    current_line = file_lines[cursor_row] if cursor_row < len(file_lines) else ""
    line_prefix = current_line[:cursor_col]

    completion = _clean_completion(raw, line_prefix, max_lines=max_suggestion_lines)
    return completion or None


# ---------------------------------------------------------------------------
# Response cleaning
# ---------------------------------------------------------------------------

# Patterns the model might prefix its completion with.
_PREAMBLE_PATTERNS = [
    re.compile(r"^Here(?:'s| is) (?:the )?completion:?\s*", re.IGNORECASE),
    re.compile(r"^The completion (?:is|would be):?\s*", re.IGNORECASE),
    re.compile(r"^Completion:?\s*", re.IGNORECASE),
    re.compile(r"^Result:?\s*", re.IGNORECASE),
]


def _clean_completion(text: str, line_prefix: str, max_lines: int = 8) -> str:
    """Clean LLM output to extract just the completion text.

    Strips markdown code fences, common preamble patterns, and
    detects cases where the model repeated text before the cursor.
    Supports multi-line completions — returns up to *max_lines* lines.

    For the first line, if the model repeated text before the cursor,
    that prefix is stripped.  Subsequent lines are kept as-is.
    """
    # Remove markdown code fences
    text = re.sub(r"^```\w*\n?", "", text)
    text = re.sub(r"\n?```$", "", text)

    # Remove common preamble patterns
    for pattern in _PREAMBLE_PATTERNS:
        text = pattern.sub("", text, count=1)

    # Collect lines, handling the first line's prefix deduplication
    result_lines: list[str] = []
    first_non_empty_found = False

    for line in text.split("\n"):
        stripped = line.rstrip()

        # Skip leading empty lines (before any content)
        if not stripped and not first_non_empty_found:
            continue

        if not stripped:
            # Keep empty lines that appear between content lines
            # (they may be intentional blank lines in the completion)
            if result_lines:
                result_lines.append("")
            continue

        first_non_empty_found = True

        # For the first content line, strip the cursor prefix if the
        # model repeated text that was already on the line.
        if not result_lines and line_prefix and stripped.startswith(line_prefix):
            result_lines.append(stripped[len(line_prefix) :])
        else:
            result_lines.append(stripped)

    # Remove trailing empty lines
    while result_lines and not result_lines[-1]:
        result_lines.pop()

    # Trim to max_lines
    if max_lines > 0 and len(result_lines) > max_lines:
        result_lines = result_lines[:max_lines]

    return "\n".join(result_lines)