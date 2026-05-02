"""Cody — AI coding assistant TUI.

Entry point: parses arguments, bootstraps services, launches the app.
"""

from __future__ import annotations

import argparse
import os
import sys

from textual.app import App, ComposeResult
from textual.widgets import Footer, Header

from bootstrap import Bootstrap
from context import AppContext
from ui.workspace import Workspace


# ---------------------------------------------------------------------------
# TUI App
# ---------------------------------------------------------------------------


class CodyApp(App):
    """Top-level Textual application.

    Receives an :class:`AppContext` produced by bootstrap and mounts the
    primary UI shell (workspace, footer).  Additional UI (chat tabs,
    sidebars, leader modal) will be added in later steps.
    """

    CSS_PATH = "ui/workspace/workspace.css"

    BINDINGS = [
        ("ctrl+q", "quit", "Quit"),
        ("ctrl+space", "open_leader", "Leader"),
    ]

    def __init__(self, context: AppContext):
        super().__init__()
        self.context = context

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        self.ws = Workspace()
        yield self.ws
        yield Footer()

    async def on_mount(self) -> None:
        self.ws.focus()

    def action_open_leader(self) -> None:
        """Push the leader key overlay."""
        from ui.widgets.leader_overlay import LeaderOverlay
        from core.leader import leader
        self.push_screen(LeaderOverlay(leader, self))


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
