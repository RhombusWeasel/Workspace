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
from core.events import CodyEvent
from ui.sidebar.sidebar import Sidebar, SidebarContainer
from ui.workspace import Workspace


# ---------------------------------------------------------------------------
# TUI App
# ---------------------------------------------------------------------------


class CodyApp(App):
    """Top-level Textual application.

    Receives an :class:`AppContext` produced by bootstrap and mounts the
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
        super().__init__()

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)

        self.left_container = SidebarContainer(
            Sidebar("left"), side="left"
        )
        self.ws = Workspace()
        self.right_container = SidebarContainer(
            Sidebar("right"), side="right", start_hidden=False
        )

        with Horizontal():
            yield self.left_container
            yield self.ws
            yield self.right_container
        yield Footer()

    async def on_mount(self) -> None:
        self.ws.focus()
        self._init_vault_panel()
        self._init_chat_panel()

    def _init_vault_panel(self) -> None:
        """Find the VaultPanel and bind the vault manager from context."""
        try:
            vault_panel = self.right_container.query_one("VaultPanel")
        except Exception:
            return

        vault_panel.set_vault(self.context.vault)

    def _init_chat_panel(self) -> None:
        """Find the ChatPanel in the right sidebar and wire it to the agent."""
        from core.agent import Agent
        from core.providers.ollama import OllamaProvider
        from core.tools import get_tools
        from core.skills import skill_manager

        try:
            chat_panel = self.right_container.query_one("ChatPanel")
        except Exception:
            return

        # Build agent
        provider = OllamaProvider(self.context.config)
        agent = Agent(
            provider=provider,
            template="You are a helpful AI assistant. {{extra}}",
            variables={"extra": "Use tools when appropriate."},
            model=self.context.config.get("session.model", ""),
            skills_xml=skill_manager.get_catalog_xml(),
        )

        chat_panel.set_agent(agent)
        chat_panel.set_tools(get_tools())

    def action_open_leader(self) -> None:
        """Push the leader key overlay."""
        from ui.widgets.leader_overlay import LeaderOverlay
        from core.leader import leader
        self.push_screen(LeaderOverlay(leader, self))

    def on_cody_event(self, event: CodyEvent) -> None:
        """Handle events from leader chords and sidebar panels."""
        if event.event_type == "leader.workspace.toggle_left":
            self.left_container.toggle()
            event.stop()
        elif event.event_type == "leader.workspace.toggle_right":
            self.right_container.toggle()
            event.stop()
        elif event.event_type == "vault.needs_unlock":
            self._prompt_vault_unlock()
            event.stop()
        elif event.event_type == "vault.needs_init":
            self._prompt_vault_init()
            event.stop()

    def _prompt_vault_unlock(self) -> None:
        from ui.widgets.input_modal import InputModal

        async def do_prompt() -> None:
            modal = InputModal(
                "Enter master password:", "Password", password=True
            )
            result = await self.push_screen_wait(modal)
            if result is None:
                return
            try:
                if self.context.vault.unlock(result):
                    panel = self.right_container.query_one("VaultPanel")
                    panel._rebuild()
            except Exception:
                pass

        self.run_worker(do_prompt())

    def _prompt_vault_init(self) -> None:
        from ui.widgets.input_modal import InputModal

        async def do_prompt() -> None:
            modal = InputModal(
                "Create master password:", "Password", password=True
            )
            result = await self.push_screen_wait(modal)
            if result is None:
                return
            try:
                self.context.vault.initialize_master(result)
                panel = self.right_container.query_one("VaultPanel")
                panel._rebuild()
            except Exception:
                pass

        self.run_worker(do_prompt())


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
