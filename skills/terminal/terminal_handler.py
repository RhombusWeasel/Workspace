"""Terminal handler — opens a terminal in the focused workspace pane.

Handles the ``terminal.open`` CodyEvent by creating a
:class:`~skills.terminal.terminal.TerminalView` tab in the focused
workspace pane's :class:`~ui.workspace.tabs.WorkspaceTabs`.

Each invocation opens a **new** terminal tab rather than switching to an
existing one, so a user can have multiple terminals across panes.

Registered at import time via ``@register_handler``.
"""

from __future__ import annotations

import os

from context import AppContext
from core.events import register_handler
from skills.terminal.terminal import TerminalState, TerminalView, next_terminal_id
from ui.workspace.workspace import PaneContainer
from ui.workspace.tabs import WorkspaceTabs


@register_handler("terminal.open")
def _on_terminal_open(data: dict, ctx: AppContext) -> None:
    """Open a new terminal tab in the focused workspace pane.

    Event data (all optional):

        command (str):
            Shell command to run.  Defaults to ``$SHELL``.
        working_directory (str):
            Working directory.  Defaults to the project directory
            from :class:`AppContext`.
    """
    command = data.get("command")
    working_directory = data.get("working_directory") or ctx.working_directory or os.getcwd()

    app = ctx.app
    if app is None:
        return

    try:
        ws = app.query_one("#workspace")
    except Exception:
        return

    # Find the focused pane container
    focused_id = ws.focused_id
    try:
        container = app.query_one(f"#pane-{focused_id}", PaneContainer)
    except Exception:
        return

    # Check if the container already has a WorkspaceTabs
    existing_tabs = None
    try:
        existing_tabs = container.query_one(WorkspaceTabs)
    except Exception:
        pass

    # Each open creates a fresh tab (unique ID).
    tab_id = next_terminal_id()
    label = "Terminal"

    # Create the persistent state for this tab.
    state = TerminalState(
        command=command,
        working_directory=working_directory,
    )

    # Factory that recreates the TerminalView after workspace recomposition.
    # Receives the same state object — the fresh widget reads from it.
    def _make_terminal(s: TerminalState) -> TerminalView:
        return TerminalView(s)

    if existing_tabs is not None:
        existing_tabs.open_tab(tab_id, label, state=state, content_factory=_make_terminal)
    else:
        # Create new WorkspaceTabs and mount in the pane
        tabs = WorkspaceTabs()

        async def _do() -> None:
            await container.mount(tabs)
            tabs.open_tab(tab_id, label, state=state, content_factory=_make_terminal)

        app.run_worker(_do())


# ---------------------------------------------------------------------------
# Leader chord registration
# ---------------------------------------------------------------------------


def register_terminal_leader_chords() -> None:
    """Register leader chords for terminal actions.

    Creates a new ``t`` chord group ("Terminal") distinct from the
    existing ``w`` ("Workspace") group.

    Chords:

    - ``Ctrl+Space t o`` → open a new terminal in the focused pane
    """
    from core.leader import register_action, register_submenu

    register_submenu(["t"], "Terminal")
    register_action(
        ["t", "o"],
        "Open",
        event_type="terminal.open",
    )