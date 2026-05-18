"""Terminal view — embedded terminal emulator for workspace panes.

Wraps :class:`textual_terminal.Terminal` with lifecycle management
(start on mount, stop on unmount), working directory context, and
integration with the :class:`~ui.workspace.tabs.WorkspaceTabs` system.

Opened via the ``terminal.open`` CodyEvent (typically triggered by
the leader chord ``Ctrl+Space t o``).

When the workspace is reorganised (split / close), the terminal's PTY
emulator **and visible output** are preserved across the DOM rebuild so
the shell session survives and the user doesn't lose their terminal
history.  This relies on three mechanisms:

* ``_preserving`` prevents ``on_unmount`` from killing the PTY
  process during a temporary DOM removal.
* ``_inherited_snapshot`` allows a freshly-created TerminalView to
  adopt a live emulator **and** the saved screen/display state from a
  previous instance, keeping the shell session alive and its output
  visible across workspace recompositions.
* :class:`TerminalSnapshot` bundles the emulator, pyte screen, and
  rendered display so they can be threaded through
  ``SavedTab`` → ``restore_state`` → ``on_mount``.
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


# Incrementing counter for unique tab IDs.
_tab_counter = itertools.count(1)


# ---------------------------------------------------------------------------
# Terminal snapshot (for preservation across recomposition)
# ---------------------------------------------------------------------------


@dataclass
class TerminalSnapshot:
    """Captured state from a running terminal that can be restored after a
    workspace recomposition.

    Bundles three things so they travel together through
    ``SavedTab`` → ``restore_state`` → ``on_mount``:

    * The live PTY emulator (keeps the shell process alive).
    * The pyte screen (character buffer + cursor position) so that
      new output is rendered correctly against the existing state.
    * The rendered display (Rich Text lines) so that the user sees
      their previous output immediately rather than a blank screen.

    These are **plain Python objects**, not Textual widgets, so they can
    be freely transferred between widget instances without needing to
    remount anything.
    """

    emulator: Any
    """Live :class:`TerminalEmulator` — keeps the PTY process running."""
    screen: Any = field(default=None)
    """pyte Screen with the character buffer and cursor position."""
    display: Any = field(default=None)
    """TerminalDisplay with the rendered Rich Text lines."""

    def stop_emulator(self) -> None:
        """Stop the PTY emulator (used for cleanup of orphaned terminals)."""
        from textual_terminal._terminal import TerminalEmulator
        if isinstance(self.emulator, TerminalEmulator):
            try:
                self.emulator.stop()
            except Exception:
                pass
        elif hasattr(self.emulator, 'stop') and callable(self.emulator.stop):
            try:
                self.emulator.stop()
            except Exception:
                pass


def next_terminal_id() -> str:
    """Return a fresh, unique tab ID like ``"term-1"``."""
    return f"term-{next(_tab_counter)}"


class TerminalView(Widget):
    """Embedded terminal emulator widget for workspace panes.

    Wraps :class:`textual_terminal.Terminal` with proper lifecycle
    management — the PTY process starts when the widget mounts and
    stops when it's removed from the DOM.

    Terminal colors adapt to the active Textual theme via the fork's
    ``default_colors="textual"`` option.

    When the workspace is reorganised (split / close), the PTY emulator
    and visible output are preserved so the shell session survives the
    DOM rebuild.  This relies on two mechanisms:

    * ``_preserving`` prevents ``on_unmount`` from killing the PTY
      process during a temporary DOM removal.
    * ``_inherited_snapshot`` allows a freshly-created TerminalView to
      adopt a live emulator **and** the saved screen/display from a
      previous instance, keeping the shell session alive and its
      visible output intact across workspace recompositions.

    Parameters
    ----------
    command:
        Shell command to run.  When ``None`` (the default), the
        ``$SHELL`` environment variable is used, falling back to
        ``/bin/sh``.
    working_directory:
        Working directory for the shell session.  If provided, the
        shell command is wrapped with ``cd`` so it starts in this
        directory.  When ``None``, the terminal inherits the parent
        process's working directory.
    """

    def __init__(
        self,
        command: str | None = None,
        working_directory: str | None = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._working_directory = working_directory
        self._shell = command or os.environ.get("SHELL", "/bin/sh")
        self._pty: PtyTerminal | None = None
        self._preserving: bool = False
        """When True, ``on_unmount`` will not stop the PTY process.

        Set by the workspace recomposition logic before temporarily
        removing the terminal from the DOM.  Reset in ``on_mount``
        after the widget is re-added.
        """
        self._inherited_snapshot: TerminalSnapshot | None = None
        """A :class:`TerminalSnapshot` transferred from a previous
        TerminalView instance.  When set, ``on_mount`` will adopt the
        emulator and restore the screen/display so the shell session
        and its visible output survive the workspace recomposition.
        """

        # Build the command string for textual_terminal.Terminal.
        #
        # If a working directory is given we wrap the shell invocation
        # so the PTY lands in the right folder:
        #
        #   /bin/bash -c 'cd '/path/to/dir' && exec /bin/bash'
        #
        # ``shlex.quote`` is used at every level so paths with spaces
        # or special characters round-trip correctly through the
        # ``shlex.split()`` call inside ``Terminal.open_terminal()``.
        if working_directory:
            inner_script = (
                f"cd {shlex.quote(working_directory)} && exec {self._shell}"
            )
            self._command = f"{self._shell} -c {shlex.quote(inner_script)}"
        else:
            self._command = self._shell

    # ------------------------------------------------------------------
    # Emulator transfer
    # ------------------------------------------------------------------

    def detach_emulator(self) -> TerminalSnapshot | None:
        """Extract the live PTY emulator, screen, and display and cancel
        the recv task.

        Called by the workspace recomposition logic *before* the DOM
        rebuild.  The returned :class:`TerminalSnapshot` can be passed to
        a new ``TerminalView`` via ``_inherited_snapshot`` so the shell
        session **and its visible output** survive the recomposition.

        Returns a :class:`TerminalSnapshot`, or ``None`` if the
        terminal has no running emulator.
        """
        if self._pty is None or self._pty.emulator is None:
            return None

        emulator = self._pty.emulator

        # Capture the screen and display *before* disconnecting.
        # These are plain Python objects (not Textual widgets) so they
        # survive the DOM rebuild and can be injected into the new
        # PtyTerminal after recomposition.
        screen = self._pty._screen
        display = self._pty._display

        # Cancel the recv task — a fresh one will be created when
        # the new TerminalView adopts the emulator in on_mount().
        if self._pty.recv_task is not None:
            self._pty.recv_task.cancel()

        # Disconnect the old PtyTerminal from the emulator so that
        # the emulator's queues are not read by two recv tasks.
        self._pty.emulator = None
        self._pty.send_queue = None
        self._pty.recv_queue = None
        self._pty.recv_task = None

        return TerminalSnapshot(
            emulator=emulator,
            screen=screen,
            display=display,
        )

    @classmethod
    def stop_orphaned_emulator(cls, emulator: object) -> None:
        """Stop an emulator that was preserved but never adopted.

        Called when a pane containing a terminal is closed — the
        emulator's PTY process must be killed explicitly because
        ``on_unmount`` was skipped (``_preserving`` was True).

        Also accepts a :class:`TerminalSnapshot` for convenience
        (stops ``snapshot.emulator``).
        """
        # Accept a TerminalSnapshot directly for backward compatibility
        # and convenience.
        if isinstance(emulator, TerminalSnapshot):
            emulator.stop_emulator()
            return

        from textual_terminal._terminal import TerminalEmulator
        if isinstance(emulator, TerminalEmulator):
            try:
                emulator.stop()
            except Exception:
                pass  # Best-effort — the process may already be dead.
        elif hasattr(emulator, 'stop') and callable(emulator.stop):
            try:
                emulator.stop()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Compose
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        # Reuse the existing PTY if one was set externally (e.g. by
        # a test or during preservation); otherwise create a fresh one.
        # compose() may be called again if the widget is remounted
        # after a DOM rebuild, so we must not overwrite an existing PTY.
        if self._pty is None:
            self._pty = PtyTerminal(self._command, default_colors="textual")
        yield self._pty

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def on_mount(self) -> None:
        """Start the PTY emulator when the widget is mounted.

        If a snapshot was transferred from a previous instance
        (``_inherited_snapshot``), the new PtyTerminal adopts the live
        emulator **and** restores the saved screen/display so the user
        sees their previous terminal output immediately.  Otherwise,
        ``start()`` creates a fresh emulator.
        """
        if self._pty is not None:
            if self._inherited_snapshot is not None:
                snapshot = self._inherited_snapshot
                self._inherited_snapshot = None

                # Adopt the live emulator: keep the PTY process running.
                self._pty.emulator = snapshot.emulator
                self._pty.send_queue = snapshot.emulator.recv_queue
                self._pty.recv_queue = snapshot.emulator.send_queue

                # Restore the screen and display so that output produced
                # before the split is visible immediately after the
                # workspace is rebuilt.  These are plain Python objects
                # (not Textual widgets), so we can safely replace the
                # newly-created PtyTerminal's defaults.
                if snapshot.screen is not None:
                    self._pty._screen = snapshot.screen
                    # Keep the pyte Stream pointing at the transferred
                    # screen so that new output feeds into it correctly.
                    self._pty.stream.screen = snapshot.screen
                    self._pty.ncol = snapshot.screen.columns
                    self._pty.nrow = snapshot.screen.lines
                if snapshot.display is not None:
                    self._pty._display = snapshot.display

                # Start receiving output from the emulator.
                self._pty.recv_task = asyncio.create_task(self._pty.recv())

                # Trigger a repaint so the restored display is shown.
                self._pty.refresh()
            else:
                # Fresh terminal — spawn a new shell process.
                self._pty.start()
        self._preserving = False

    def on_unmount(self) -> None:
        """Stop the PTY emulator when the widget is removed from the DOM.

        If ``_preserving`` is True, the removal is temporary (workspace
        recomposition) and the PTY process is kept alive so it can be
        adopted by a new TerminalView after the DOM rebuild.
        """
        if self._preserving:
            return  # PTY stays alive — emulator will be transferred.
        if self._pty is not None:
            try:
                self._pty.stop()
            except Exception:
                pass  # Best-effort — the PTY process may already be dead.
            self._pty = None