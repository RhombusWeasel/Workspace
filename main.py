"""Cody — AI coding assistant TUI.

Entry point: parses arguments, bootstraps services, launches the app.
"""

from __future__ import annotations

import argparse
import os
import sys

from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.widgets import Footer, Header

from bootstrap import Bootstrap
from context import AppContext
from core.events import CodyEvent, dispatch
from ui.sidebar.sidebar import Sidebar, SidebarContainer
from ui.workspace import Workspace

# Import leader overlay early so its @register_handler("app.open_leader") runs.
import ui.widgets.leader_overlay  # noqa: F401 — side-effect import for handler registration


# ---------------------------------------------------------------------------
# TUI App
# ---------------------------------------------------------------------------


class CodyApp(App):
    """Top-level Textual application.

    Receives a :class:`AppContext` produced by bootstrap and mounts the
    primary UI shell (workspace, footer).  Additional UI (chat tabs,
    sidebars, leader modal) will be added in later steps.

    CSS paths are dynamically collected from three tiers at bootstrap time
    (cody bundled → ~/.agents/ → project .agents/) and set on the instance
    via ``context.css_paths``.
    """

    CSS_PATH = []

    BINDINGS = [
        ("ctrl+q", "quit", "Quit"),
        ("ctrl+space", "open_leader", "Leader"),
    ]

    def __init__(self, context: AppContext):
        self.CSS_PATH = context.css_paths
        self.context = context
        context.app = self
        super().__init__()

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)

        self.left_container = SidebarContainer(
            Sidebar("left"), side="left", id="sidebar-left"
        )
        self.ws = Workspace()
        self.right_container = SidebarContainer(
            Sidebar("right"), side="right", start_hidden=False,
            id="sidebar-right"
        )

        with Horizontal():
            yield self.left_container
            yield self.ws
            yield self.right_container
        yield Footer()

    async def on_mount(self) -> None:
        self.ws.focus()

    def action_open_leader(self) -> None:
        """Post an event so the handler in leader_overlay.py pushes the screen."""
        self.post_message(CodyEvent("app.open_leader", {}))

    def on_cody_event(self, event: CodyEvent) -> None:
        """Route every :class:`CodyEvent` through the handler registry.

        This is the **only** handler the app needs.  Every feature or
        skill registers handlers via ``@register_handler(...)``; the
        app file never grows.
        """
        dispatch(event, self.context)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Cody — AI coding assistant TUI",
    )
    parser.add_argument(
        "working_directory",
        nargs="?",
        default=os.getcwd(),
        help="Project directory to work in (default: current directory)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)

    wd = os.path.abspath(args.working_directory)
    if not os.path.isdir(wd):
        print(f"Error: {wd} is not a directory", file=sys.stderr)
        sys.exit(1)

    # Bootstrap all services
    bootstrap = Bootstrap(working_directory=wd)
    context = bootstrap.run()

    # Launch the TUI
    app = CodyApp(context)
    app.run()


if __name__ == "__main__":
    main()
