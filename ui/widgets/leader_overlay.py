"""Leader key overlay — ``Ctrl+Space`` chord navigation.

A semi-transparent overlay that reads :class:`~core.leader.LeaderRegistry`
and shows available chords.  Key presses walk the tree; leaf nodes trigger
their handler callbacks.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.widgets import Label

from core.leader import LeaderNode, LeaderRegistry


# ---------------------------------------------------------------------------
# Overlay
# ---------------------------------------------------------------------------


class LeaderOverlay(ModalScreen[None]):
    """Modal overlay for leader key chord navigation.

    Press ``Ctrl+Space`` to open; press ``Escape`` to dismiss at any
    time.  Single-character keys walk the chord tree; when a leaf is
    reached its :attr:`LeaderNode.handler` is invoked and the overlay
    closes.
    """

    CSS = """
    LeaderOverlay {
        align: center middle;
    }

    #leader-hint {
        width: auto;
        height: auto;
        padding: 1 2;
        background: $surface;
        border: round $primary;
    }
    """

    def __init__(self, registry: LeaderRegistry, app) -> None:
        super().__init__()
        self._registry = registry
        self._app_ref = app
        self._path: list[str] = []
        self._current: LeaderNode = registry.get_root()

    def compose(self) -> ComposeResult:
        yield Label(self._build_display(), id="leader-hint")

    # ------------------------------------------------------------------
    # Key handling
    # ------------------------------------------------------------------

    def on_key(self, event) -> None:
        key = event.key

        if key == "escape":
            self.dismiss(None)
            return

        # Only handle single printable characters
        if len(key) != 1:
            return

        if key in self._current.children:
            self._path.append(key)
            self._current = self._current.children[key]

            if self._current.handler is not None:
                self._current.handler()
                self.dismiss(None)
            elif self._current.event_type is not None:
                from core.events import CodyEvent
                from ui.workspace.workspace import Workspace
                try:
                    ws = self._app_ref.query_one(Workspace)
                    ws.post_message(
                        CodyEvent(self._current.event_type, {})
                    )
                except Exception:
                    pass
                self.dismiss(None)
            else:
                self._refresh()

    # ------------------------------------------------------------------
    # Display
    # ------------------------------------------------------------------

    def _refresh(self) -> None:
        label = self.query_one("#leader-hint", Label)
        label.update(self._build_display())

    def _build_display(self) -> str:
        if self._path:
            breadcrumb = " ".join(self._path)
        else:
            breadcrumb = "leader"

        lines = [breadcrumb, "─" * 20]

        for key in sorted(self._current.children):
            child = self._current.children[key]
            label = child.label or key
            marker = "…" if child.handler is None else "✓"
            lines.append(f" {key}  {label}  {marker}")

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Event handler — registered at import time
# ---------------------------------------------------------------------------

from core.events import register_handler
from context import AppContext


@register_handler("app.open_leader")
def _on_open_leader(data: dict, ctx: AppContext) -> None:
    """Push the leader key overlay on ``app.open_leader``."""
    from core.leader import leader

    app = ctx.app
    if app is None:
        return
    app.push_screen(LeaderOverlay(leader, app))
