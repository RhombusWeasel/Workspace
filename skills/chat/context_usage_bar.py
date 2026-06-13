"""Context usage bar — a single-line bar showing token usage vs context window.

Renders as a 1-row-high bar with a proportional background fill and
centered text showing model name, token counts, and percentage.
"""

from __future__ import annotations

from rich.text import Text
from rich.style import Style

from textual.widget import Widget


class ContextUsageBar(Widget):
    """A single-line bar showing token usage vs the model's context window.

    The bar background fills proportionally to ``used / total`` and
    the text ``{model_name} {used:,}/{total:,} [{pct}%]`` is centred
    on the line.

    Hidden by default; becomes visible when :meth:`update` is called
    with a non-zero *total*.

    Default CSS:

    .. code-block:: css

        ContextUsageBar {
            display: none;
            height: 1;
            width: 1fr;
            padding: 0;
            margin: 0;
        }
    """

    DEFAULT_CSS = """
    ContextUsageBar {
        display: none;
        height: 1;
        width: 1fr;
        padding: 0;
        margin: 0;
        border: none;
        background: transparent;
    }
    """

    can_focus = False

    def __init__(self) -> None:
        super().__init__()
        self._model_name: str = ""
        self._used: int = 0
        self._total: int = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update(
        self,
        model_name: str,
        used: int,
        total: int | None,
    ) -> None:
        """Update the bar with current token usage.

        Parameters
        ----------
        model_name:
            Display name of the model (e.g. ``"qwen3.5:0.8b"``).
        used:
            Total tokens consumed so far (prompt + completion).
        total:
            Maximum context window size, or ``None`` if unknown.
            When ``None`` or zero the bar is hidden.
        """
        self._model_name = model_name
        self._used = used
        self._total = total or 0
        if self._total > 0:
            self.display = True
        else:
            self.display = False
        self.refresh()

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def render(self) -> Text:
        if self._total <= 0:
            return Text("")

        width = self.size.width or 80
        pct = min(self._used / self._total, 1.0)
        fill_width = max(int(width * pct), 0)

        percentage = pct * 100
        label = f"{self._model_name} {self._used:,}/{self._total:,} [{percentage:.1f}%]"

        # Pad / centre the label to fill the full width
        padded = label.center(width)

        # Build Rich Text efficiently: one span for the filled portion,
        # one for the unfilled portion.
        text = Text()
        fill_style = Style(bgcolor="rgb(40,80,155)")

        if fill_width > 0:
            text.append(padded[:fill_width], style=fill_style)
        if fill_width < width:
            text.append(padded[fill_width:])

        return text