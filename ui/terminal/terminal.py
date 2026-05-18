"""Terminal view — embedded terminal emulator for workspace panes.

Wraps :class:`textual_terminal.Terminal` with lifecycle management
(start on mount, stop on unmount), working directory context, and
integration with the :class:`~ui.workspace.tabs.WorkspaceTabs` system.

Opened via the ``terminal.open`` CodyEvent (typically triggered by
the leader chord ``Ctrl+Space t o``).

Tab state is managed by :class:`TerminalState`, which owns the PTY
emulator, pyte screen, and rendered display.  When the workspace is
reorganised (split / close), the ``TerminalState`` object survives
the DOM rebuild unchanged — the fresh ``TerminalView`` reads from and
writes to the same state object.  No snapshot extraction or injection
is needed.
"""

from __future__ import annotations

import asyncio
import itertools
import os
import shlex
from dataclasses import dataclass, field
from typing import Any

from textual.app import ComposeResult
from textual.widget import Widget
from textual_terminal import Terminal as PtyTerminal

from ui.workspace.tabs import TabState


# Incrementing counter for unique tab IDs.
_tab_counter = itertools.count(1)


# ---------------------------------------------------------------------------
# TerminalState — persistent state for terminal tabs
# ---------------------------------------------------------------------------


@dataclass
class TerminalState(TabState):
    """State for a terminal tab that survives workspace recomposition.

    Owns the PTY emulator (which backs a running shell process) and
    the pyte screen / rendered display.  When a terminal tab is closed
    permanently, ``dispose()`` stops the PTY process.

    When the workspace is reorganised (split / close), the
    ``TerminalState`` object is carried through ``SavedTab`` and
    handed to the fresh ``TerminalView`` — the widget simply reads
    from ``state.emulator``, ``state.screen``, ``state.display``
    to restore the terminal.
    """

    command: str | None = None
    """Shell command to run.  When None, $SHELL is used."""

    working_directory: str | None = None
    """Working directory for the shell session."""

    emulator: Any = field(default=None)
    """Live PTY emulator — keeps the shell process running."""

    screen: Any = field(default=None)
    """pyte Screen with the character buffer and cursor position."""

    display: Any = field(default=None)
    """TerminalDisplay with the rendered Rich Text lines."""

    def dispose(self) -> None:
        """Stop the PTY process when the tab is permanently closed."""
        if self.emulator is not None:
            try:
                self.emulator.stop()
            except Exception:
                pass
            self.emulator = None


def next_terminal_id() -> str:
    """Return a fresh, unique tab ID like ``"term-1"``."""
    return f"term-{next(_tab_counter)}"


class TerminalView(Widget):
    """Embedded terminal emulator widget for workspace panes.

    Wraps :class:`textual_terminal.Terminal` with proper lifecycle
    management — the PTY process starts when the widget mounts and
    stops when the tab is permanently closed (via
    ``TerminalState.dispose()``).

    The widget reads from and writes to a :class:`TerminalState`
    object.  On mount, it adopts an existing emulator from the state
    (preserving a running shell) or creates a fresh one.  On unmount,
    it flushes references back to the state but does **not** stop the
    PTY process — that only happens when the tab is permanently closed.

    Parameters
    ----------
    state:
        The :class:`TerminalState` for this tab.  Provides the command,
        working directory, and (after first mount) the live emulator.
    """

    def __init__(self, state: TerminalState, **kwargs):
        super().__init__(**kwargs)
        self.state = state
        self._pty: PtyTerminal | None = None

        # Build the command string for textual_terminal.Terminal.
        shell = state.command or os.environ.get("SHELL", "/bin/sh")
        if state.working_directory:
            inner_script = (
                f"cd {shlex.quote(state.working_directory)} && exec {shell}"
            )
            self._command = f"{shell} -c {shlex.quote(inner_script)}"
        else:
            self._command = shell

    # ------------------------------------------------------------------
    # State sync
    # ------------------------------------------------------------------

    def flush_state(self) -> None:
        """Sync current widget state back to ``self.state``.

        Called by :meth:`WorkspaceTabs.save_state` before recomposition.
        Flushes the emulator, screen, and display back to the state
        object so the fresh widget can adopt them after the rebuild.
        """
        if self._pty is None:
            return

        # Capture emulator
        if self._pty.emulator is not None:
            self.state.emulator = self._pty.emulator

        # Capture screen and display before disconnecting
        if hasattr(self._pty, "_screen") and self._pty._screen is not None:
            self.state.screen = self._pty._screen
        if hasattr(self._pty, "_display") and self._pty._display is not None:
            self.state.display = self._pty._display

        # Cancel the recv task — a fresh one will be created by the
        # new TerminalView when it adopts the emulator.
        if self._pty.recv_task is not None:
            self._pty.recv_task.cancel()

        # Disconnect the old PtyTerminal from the emulator so that
        # the emulator's queues are not read by two recv tasks.
        self._pty.emulator = None
        self._pty.send_queue = None
        self._pty.recv_queue = None
        self._pty.recv_task = None

    # ------------------------------------------------------------------
    # Compose
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        if self._pty is None:
            self._pty = PtyTerminal(self._command, default_colors="textual")
        yield self._pty

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def on_mount(self) -> None:
        """Start the PTY emulator when the widget is mounted.

        If the state already has an emulator (from a previous widget
        instance), the PtyTerminal adopts it and restores the saved
        screen/display so the user sees their previous output
        immediately.  Otherwise, a fresh shell process is started.
        """
        if self._pty is None:
            return

        if self.state.emulator is not None:
            # Adopt the live emulator — keep the PTY process running.
            self._pty.emulator = self.state.emulator
            self._pty.send_queue = self.state.emulator.recv_queue
            self._pty.recv_queue = self.state.emulator.send_queue

            # Restore the screen and display so that output produced
            # before the split is visible immediately.
            if self.state.screen is not None:
                self._pty._screen = self.state.screen
                self._pty.stream.screen = self.state.screen
                self._pty.ncol = self.state.screen.columns
                self._pty.nrow = self.state.screen.lines
            if self.state.display is not None:
                self._pty._display = self.state.display

            # Start receiving output from the emulator.
            self._pty.recv_task = asyncio.create_task(self._pty.recv())

            # Trigger a repaint so the restored display is shown.
            self._pty.refresh()
        else:
            # Fresh terminal — spawn a new shell process.
            self._pty.start()

    def on_unmount(self) -> None:
        """Handle widget removal from the DOM.

        Does **not** stop the PTY process — that only happens when the
        tab is permanently closed via ``TerminalState.dispose()``.
        During recomposition, this method is called when the old widget
        is destroyed, but the emulator in ``self.state`` is preserved
        and will be adopted by the new widget in ``on_mount``.
        """
        # The emulator lives in state — nothing to stop here.
        # Permanent cleanup happens in TerminalState.dispose().
        self._pty = None