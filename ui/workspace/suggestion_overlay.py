"""Suggestion overlay — displays multi-line AI code suggestions.

A docked panel that appears at the bottom of the file editor when
a multi-line AI suggestion is available.  Shows the full suggestion
with a header indicating how to accept or dismiss it.

For single-line suggestions, only the inline ghost text is shown
(via TextArea's ``suggestion`` reactive).  This overlay is only
used when the suggestion spans multiple lines.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.widgets import Static
from textual.widget import Widget


class SuggestionOverlay(Widget):
    """Docked panel that displays multi-line AI code suggestions.

    Hidden by default.  Call :meth:`show_suggestion` to display a
    suggestion and :meth:`hide_suggestion` to dismiss it.

    The overlay docks to the bottom of its parent (FileEditor) and
    pushes the editor content up slightly.  It uses ``display: none``
    / ``display: block`` toggling via the ``-visible`` CSS class.
    """

    DEFAULT_CSS = """
    SuggestionOverlay {
        display: none;
        height: auto;
        max-height: 10;
        dock: bottom;
        background: $surface-darken-1;
        border-top: tall $primary;
        padding: 0 1;
        overflow-y: auto;
        color: $text-muted;
    }

    SuggestionOverlay.-visible {
        display: block;
    }

    SuggestionOverlay .suggestion-header {
        color: $text-disabled;
        text-style: italic;
    }

    SuggestionOverlay .suggestion-code {
        color: $text-muted;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._suggestion: str | None = None

    def compose(self) -> ComposeResult:
        yield Static(id="suggestion-content")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def show_suggestion(self, suggestion: str) -> None:
        """Display the given multi-line suggestion and become visible.

        Parameters
        ----------
        suggestion:
            The full suggestion text (may contain newlines).
        """
        self._suggestion = suggestion
        content = self.query_one("#suggestion-content", Static)

        lines = suggestion.split("\n")
        parts = [
            "[italic]✦ AI  ·  [bold]Ctrl+F[/] accept  ·  "
            "[bold]Esc[/] dismiss[/]"
        ]
        for line in lines:
            parts.append(line)

        content.update("\n".join(parts))
        self.add_class("-visible")

    def hide_suggestion(self) -> None:
        """Dismiss the suggestion and become hidden."""
        self._suggestion = None
        self.remove_class("-visible")
        try:
            content = self.query_one("#suggestion-content", Static)
            content.update("")
        except Exception:
            pass

    @property
    def suggestion(self) -> str | None:
        """The current suggestion text, or ``None`` if hidden."""
        return self._suggestion

    @property
    def is_showing(self) -> bool:
        """Whether the overlay is currently visible."""
        return self.has_class("-visible")