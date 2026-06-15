"""Terminal handler — opens a terminal in the focused workspace pane.

Handles the ``terminal.open`` WorkspaceEvent by creating a
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


# ---------------------------------------------------------------------------
# Session handler registration
# ---------------------------------------------------------------------------

from core.session import TabTypeHandler, register_tab_type


def _serialise_terminal(state: TerminalState) -> dict:
    """Extract persistent data from a TerminalState.

    Note: the running shell process cannot be restored, but we preserve
    the working directory so the terminal reopens in the same location.
    """
    return {
        "command": state.command,
        "working_directory": state.working_directory,
    }


def _deserialise_terminal(data: dict, ctx: AppContext) -> TerminalState:
    """Reconstruct a TerminalState from serialised data."""
    return TerminalState(
        command=data.get("command"),
        working_directory=data.get("working_directory") or ctx.working_directory,
    )


def _make_terminal_from_state(s: TerminalState) -> TerminalView:
    """Content factory that creates a TerminalView from restored state."""
    return TerminalView(s)


register_tab_type(TabTypeHandler(
    tab_type="terminal",
    serialise=_serialise_terminal,
    deserialise=_deserialise_terminal,
    content_factory=_make_terminal_from_state,
    make_label=lambda s: "Terminal",
))