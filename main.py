"""Workspace — AI coding assistant TUI.

Entry point: parses arguments, bootstraps services, launches the app.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

from textual import events
from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.widgets import Footer, Header

from bootstrap import Bootstrap
from context import AppContext
from core.config import register_defaults
from core.events import WorkspaceEvent, dispatch
from ui.sidebar.sidebar import Sidebar, SidebarContainer
from ui.workspace import Workspace
from core.terminal_passthrough import register_terminal_passthrough

log = logging.getLogger(__name__)

# App-level keys that must pass through the terminal widget.
register_terminal_passthrough({"ctrl+q", "ctrl+space", "ctrl+@"})

# ---------------------------------------------------------------------------
# Config defaults — UI theme
# ---------------------------------------------------------------------------

_UI_DEFAULT_THEME = "textual-dark"
register_defaults({"ui": {"theme": _UI_DEFAULT_THEME}})

# Import leader overlay early so its @register_handler("app.open_leader") runs.
import ui.widgets.leader_overlay  # noqa: F401 — side-effect import for handler registration
# Import file edit handler so its @register_handler("files.edit") runs.
import ui.workspace.file_edit_handler  # noqa: F401 — side-effect import for handler registration
import ui.workspace.welcome_view  # noqa: F401 — side-effect import for session handler registration
# Import inline suggestion module so its register_defaults() runs
# before bootstrap's apply_defaults().
import core.inline_suggest  # noqa: F401 — side-effect import for config defaults
# Import agent registry so its config defaults are registered.
import core.agent_registry  # noqa: F401 — side-effect import for config defaults
# Import provider registry so its config defaults are registered.
import core.providers.registry  # noqa: F401 — side-effect import for config defaults
# Import provider base so redaction config defaults register early.
import core.providers.base  # noqa: F401 — side-effect import for redaction defaults
# Import ollama provider so its config defaults register.
import core.providers.ollama  # noqa: F401 — side-effect import for config defaults
# Chat skill session defaults must be registered before apply_defaults().
# We register them inline here to avoid importing the entire skill
# (which triggers handler/command/leader registrations that depend on
# services not yet available at this point in bootstrap).
register_defaults({
    "session": {
        "open_thinking": False,
        "open_tools": False,
        "show_system_prompt": False,
    },
})
# Terminal handler is now registered by the terminal plugin
# (plugins/terminal/__init__.py) at plugin load time.


# ---------------------------------------------------------------------------
# TUI App
# ---------------------------------------------------------------------------


class WorkspaceApp(App):
    """Top-level Textual application.

    Receives a :class:`AppContext` produced by bootstrap and mounts the
    primary UI shell (workspace, footer).  Additional UI (chat tabs,
    sidebars, leader modal) will be added in later steps.

    CSS paths are dynamically collected from three tiers at bootstrap time
    (workspace bundled → ~/.agents/ → project .agents/) and set on the instance
    via ``context.css_paths``.
    """

    CSS_PATH = []

    BINDINGS = [
        ("ctrl+q", "quit", "Quit"),
        ("ctrl+space,ctrl+@", "open_leader", "Leader"),
    ]

    def __init__(self, context: AppContext):
        self.CSS_PATH = context.css_paths
        self.context = context
        context.app = self
        self._theme_loading = False
        # Keys that the terminal widget should never consume, so
        # app-level and widget-level shortcuts still work.
        from core.terminal_passthrough import get_terminal_passthrough_keys
        self.terminal_passthrough_keys = get_terminal_passthrough_keys()
        super().__init__()

    # ------------------------------------------------------------------
    # Theme persistence
    # ------------------------------------------------------------------

    def _apply_theme_from_config(self) -> None:
        """Set the Textual theme from the persisted config value."""
        cfg = self.context.config
        if cfg is None:
            return
        theme_name = cfg.get("ui.theme", _UI_DEFAULT_THEME)
        if theme_name and theme_name in self.available_themes:
            self._theme_loading = True
            self.theme = theme_name
            self._theme_loading = False

    def _watch_theme(self, theme_name: str) -> None:
        """Persist theme pick to config whenever the theme changes.

        This covers every source of theme change:
        * Textual's built-in theme picker (header → Change Theme).
        * ``ConfigPanel`` editing ``ui.theme``.
        * Any future action that sets ``self.theme``.
        """
        super()._watch_theme(theme_name)
        if not self._theme_loading and self.context.config is not None:
            self.context.config.set("ui.theme", theme_name)
            self.context.config.save()

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)

        self.left_container = SidebarContainer(
            Sidebar("left"), side="left", start_hidden=False,
            id="sidebar-left"
        )
        self.ws = Workspace()
        self.right_container = SidebarContainer(
            Sidebar("right"), side="right",
            id="sidebar-right"
        )

        with Horizontal():
            yield self.left_container
            yield self.ws
            yield self.right_container
        yield Footer()

    async def on_mount(self) -> None:
        self._apply_theme_from_config()

        # Wire session manager's ctx now that the app exists
        self.context.session_manager.ctx = self.context

        # Restore session if one exists, otherwise open welcome tab
        if self.context.session_manager.has_session:
            restored = self.context.session_manager.restore(
                self.ws, self.left_container, self.right_container
            )
            if not restored:
                # Session restore failed — fall back to welcome tab
                self.ws.run_worker(self.ws._open_welcome_tab())
        else:
            # No session file — open the welcome tab as usual
            self.ws.run_worker(self.ws._open_welcome_tab())

        self.ws.focus()

        # Periodically save session state (every 5 seconds)
        self._session_save_interval = self.set_interval(
            5, self._periodic_session_save
        )

    async def on_unmount(self) -> None:
        """Save session state before the app shuts down."""
        # Stop periodic save
        if hasattr(self, "_session_save_interval"):
            self._session_save_interval.stop()

        # Best-effort final save (may fail if DOM is already torn down)
        self._save_session()

    _save_count = 0

    def _save_session(self) -> None:
        """Save current session state to disk."""
        WorkspaceApp._save_count += 1
        n = WorkspaceApp._save_count
        try:
            left_hidden = self.left_container.is_hidden
            right_hidden = self.right_container.is_hidden
            children = list(self.ws.children)
            if not children:
                log.debug("_save_session #%d: skipping (no DOM children)", n)
                return
            self.context.session_manager.save(
                self.ws, left_hidden, right_hidden
            )
            log.debug("Session saved (#%d)", n)
        except Exception as e:
            log.warning("Failed to save session (#%d): %s", n, e, exc_info=True)

    def _periodic_session_save(self) -> None:
        """Periodically save session state to protect against crashes."""
        self._save_session()

    def action_open_leader(self) -> None:
        """Post an event so the handler in leader_overlay.py pushes the screen."""
        self.post_message(WorkspaceEvent("app.open_leader", {}))

    def exit(self, result=None, return_code=0, message=None) -> None:
        """Override exit to save session before shutting down."""
        self._save_session()
        super().exit(result=result, return_code=return_code, message=message)

    async def action_quit(self) -> None:
        """Save session before quitting."""
        self._save_session()
        await super().action_quit()

    async def _on_exit_app(self) -> None:
        """Save session at the very start of the shutdown sequence."""
        self._save_session()
        await super()._on_exit_app()

    def on_key(self, event: events.Key) -> None:
        """Intercept Ctrl+Q to save session before quit."""
        if event.key == "ctrl+q":
            self._save_session()

    def on_workspace_event(self, event: WorkspaceEvent) -> None:
        """Route every :class:`WorkspaceEvent` through the handler registry.

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
        description="Workspace — AI coding assistant TUI",
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
    app = WorkspaceApp(context)
    app.run()


if __name__ == "__main__":
    main()