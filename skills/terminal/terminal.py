"""Terminal view — embedded terminal emulator for workspace panes.

Wraps :class:`textual_terminal.Terminal` with lifecycle management
(start on mount, stop on unmount), working directory context, and
integration with the :class:`~ui.workspace.tabs.WorkspaceTabs` system.

Opened via the ``terminal.open`` WorkspaceEvent (typically triggered by
the leader chord ``Ctrl+Space t o``).

Tab state is managed by :class:`TerminalState`, which owns the PTY
emulator, pyte screen, and rendered display.  When the workspace is
reorganised (split / close), the ``TerminalState`` object survives
the DOM rebuild unchanged — the fresh ``TerminalView`` reads from and
writes to the same state object.  No snapshot extraction or injection
is needed.

Scrollback support
------------------
A ``pyte.HistoryScreen`` replaces the default ``Screen`` so lines
that scroll off the top are preserved in a history buffer.  The user
can scroll back through this buffer with the mouse wheel or
``Shift+Up``/``Shift+Down``.  When new output arrives the view
automatically scrolls back to the bottom — this is handled by
``HistoryScreen.before_event`` which calls ``next_page`` until the
position reaches the bottom.
"""

from __future__ import annotations

import asyncio
import itertools
import os
import shlex
from dataclasses import dataclass, field
from typing import Any

from textual.app import ComposeResult
from textual import events
from textual.widget import Widget
from textual_terminal import Terminal as PtyTerminal
from textual_terminal._terminal import TerminalDisplay
import pyte

from ui.workspace.tabs import TabState


# Incrementing counter for unique tab IDs.
_tab_counter = itertools.count(1)


# ---------------------------------------------------------------------------
# Scrollback screen — pyte HistoryScreen with set_margins fix
# ---------------------------------------------------------------------------


class ScrollbackScreen(pyte.HistoryScreen):
    """A pyte HistoryScreen that preserves lines scrolled off the top.

    Extends ``pyte.HistoryScreen`` with the ``set_margins`` fix from
    ``TerminalPyteScreen`` (required for TERM=linux compatibility) and
    a default history of 10 000 lines.
    """

    def set_margins(self, *args, **kwargs):
        kwargs.pop("private", None)
        return super().set_margins(*args, **kwargs)


SCROLLBACK_LINES = 10_000
"""Number of lines kept in the scrollback buffer."""


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

    Scrollback
    ###########

    The terminal supports scrollback via ``pyte.HistoryScreen``.
    Mouse wheel and keyboard shortcuts allow scrolling through
    history.  When a program enables mouse tracking (e.g. ``less``,
    ``vim``), scroll events are forwarded to the program instead.

    Keyboard shortcuts when the terminal has focus:

    - ``Shift+Up`` — scroll up through history
    - ``Shift+Down`` — scroll down towards the bottom
    - ``PageUp`` — scroll up one page
    - ``PageDown`` — scroll down one page
    - ``Shift+Home`` — jump to the top of history
    - ``Shift+End`` — jump to the bottom of history
    - ``Escape`` or any other key — exit scrollback and return to
      the live terminal

    Parameters
    ----------
    state:
        The :class:`TerminalState` for this tab.  Provides the command,
        working directory, and (after first mount) the live emulator.
    """

    # Shift+Up/Down for scrollback; Escape and Ctrl+F1 release focus
    # (the latter are handled by PtyTerminal).
    SCROLL_KEYS = frozenset({"shift+up", "shift+down", "pageup", "pagedown", "shift+home", "shift+end"})

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
        # Replace the default Screen with a ScrollbackScreen so that
        # lines scrolled off the top are preserved in a history buffer.
        # The user can scroll back through this buffer with the mouse
        # wheel or Shift+Up / Shift+Down.
        self._pty._screen = ScrollbackScreen(
            self._pty.ncol, self._pty.nrow, history=SCROLLBACK_LINES,
        )
        self._pty.stream = pyte.Stream(self._pty._screen)
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
                self._pty.stream.attach(self.state.screen)
                self._pty.ncol = self.state.screen.columns
                self._pty.nrow = self.state.screen.lines
            if self.state.display is not None:
                self._pty._display = self.state.display

            # Start receiving output from the emulator.
            self._pty.recv_task = asyncio.create_task(self._pty.recv())

            # Send the current pane size to the emulator so the
            # shell process receives SIGWINCH and redraws correctly.
            # Without this, the PTY still thinks it's the old size
            # after a workspace split.
            try:
                size = self._pty.size
                if size and self._pty.send_queue is not None:
                    asyncio.create_task(
                        self._pty.send_queue.put(
                            ["set_size", size.height, size.width]
                        )
                    )
            except Exception:
                pass

            # Trigger a repaint so the restored display is shown.
            self._pty.refresh()
        else:
            # Fresh terminal — spawn a new shell process.
            self._pty.start()

        # Focus the terminal so the user can type immediately.
        self._focus_terminal()

    def _focus_terminal(self) -> None:
        """Focus the embedded PTY terminal widget.

        Called on mount and when the tab becomes active after a
        tab switch, so the user can start typing without needing
        to click the terminal area first.
        """
        if self._pty is not None:
            self._pty.focus()

    # ------------------------------------------------------------------
    # Scrollback
    # ------------------------------------------------------------------

    def _scroll_up(self) -> None:
        """Scroll the terminal view up through the scrollback history."""
        if self._pty is None:
            return
        screen = self._pty._screen
        if not isinstance(screen, pyte.HistoryScreen):
            return
        # Only scroll up if there is history above the current view.
        if screen.history.position > screen.lines:
            screen.prev_page()
            self._refresh_scroll_display()

    def _scroll_down(self) -> None:
        """Scroll the terminal view down towards the bottom."""
        if self._pty is None:
            return
        screen = self._pty._screen
        if not isinstance(screen, pyte.HistoryScreen):
            return
        # Only scroll down if we're not already at the bottom.
        if screen.history.position < screen.history.size:
            screen.next_page()
            self._refresh_scroll_display()

    def _scroll_to_bottom(self) -> None:
        """Jump to the bottom of the scrollback history."""
        if self._pty is None:
            return
        screen = self._pty._screen
        if not isinstance(screen, pyte.HistoryScreen):
            return
        while screen.history.position < screen.history.size:
            screen.next_page()
        self._refresh_scroll_display()

    @property
    def is_scrolled_up(self) -> bool:
        """Whether the terminal is currently showing scrollback history."""
        if self._pty is None:
            return False
        screen = self._pty._screen
        if not isinstance(screen, pyte.HistoryScreen):
            return False
        return screen.history.position < screen.history.size

    def _refresh_scroll_display(self) -> None:
        """Re-render the terminal display from the current screen buffer.

        Called after a scroll operation (prev_page / next_page) so
        the user can see the scrolled content.  Uses the same rendering
        logic as ``PtyTerminal.recv()`` but without processing new
        output — just re-renders what's already on the screen.

        When scrolled up, the cursor is hidden (``HistoryScreen``
        sets ``cursor.hidden``) so the cursor highlight is suppressed
        automatically.
        """
        if self._pty is None:
            return
        from pyte.screens import Char
        from rich.text import Text

        pty = self._pty
        screen = pty._screen
        lines = []
        for y in range(screen.lines):
            line_text = Text()
            line = screen.buffer[y]
            style_change_pos = 0
            for x in range(screen.columns):
                char: Char = line[x]
                line_text.append(char.data)
                if x > 0:
                    last_char: Char = line[x - 1]
                    if not pty.char_style_cmp(char, last_char) or x == screen.columns - 1:
                        last_style = pty.char_rich_style(last_char)
                        line_text.stylize(last_style, style_change_pos, x + 1)
                        style_change_pos = x

                # Only highlight the cursor when it is in the visible
                # area (HistoryScreen hides it when scrolled up).
                if (
                    not getattr(screen.cursor, "hidden", False)
                    and screen.cursor.x == x
                    and screen.cursor.y == y
                ):
                    line_text.stylize("reverse", x, x + 1)

            lines.append(line_text)

        pty._display = TerminalDisplay(lines)
        pty.refresh()

    # ------------------------------------------------------------------
    # Input handlers
    # ------------------------------------------------------------------

    async def on_key(self, event: events.Key) -> None:
        """Handle keyboard input for scrollback navigation.

        When scrolled up through history, we intercept scroll keys
        (Shift+Up, Shift+Down, PageUp, PageDown, Shift+Home, Shift+End)
        to navigate the scrollback buffer.  Any other key exits scrollback
        mode and returns to the live terminal.

        When not scrolled up, all keys are left for PtyTerminal to handle.
        """
        if self._pty is None or self._pty.emulator is None:
            return

        key = event.key

        # If scrolled up and the user presses a non-scroll key,
        # exit scrollback by jumping to the bottom.  Don't forward
        # the key to the PTY so the user stays in scrollback mode.
        if self.is_scrolled_up:
            if key in self.SCROLL_KEYS:
                # Still in scrollback — handle navigation.
                if key == "shift+up" or key == "pageup":
                    self._scroll_up()
                elif key == "shift+down" or key == "pagedown":
                    self._scroll_down()
                elif key == "shift+home":
                    # Jump to top: scroll all the way up
                    screen = self._pty._screen
                    if isinstance(screen, pyte.HistoryScreen):
                        while screen.history.position > screen.lines:
                            screen.prev_page()
                        self._refresh_scroll_display()
                elif key == "shift+end":
                    self._scroll_to_bottom()
                event.stop()
                return
            else:
                # Exit scrollback — jump to bottom, then let the key
                # fall through to PtyTerminal for normal processing.
                self._scroll_to_bottom()
                # Don't stop the event so PtyTerminal can process it.
                return

    async def on_mouse_scroll_down(
        self, event: events.MouseScrollDown
    ) -> None:
        """Handle mouse scroll-down in the terminal.

        If the terminal program has enabled mouse tracking, forwards the
        scroll to the PTY.  Otherwise, scrolls down through scrollback
        history.
        """
        if self._pty is None:
            return
        if self._pty.emulator is None:
            return
        if self._pty.mouse_tracking:
            # Terminal program wants raw scroll events.
            event.stop()
            await self._pty.send_queue.put(
                ["scroll", "down", event.x, event.y]
            )
            return
        # No mouse tracking — use scroll for scrollback.
        self._scroll_down()

    async def on_mouse_scroll_up(
        self, event: events.MouseScrollUp
    ) -> None:
        """Handle mouse scroll-up in the terminal.

        If the terminal program has enabled mouse tracking, forwards the
        scroll to the PTY.  Otherwise, scrolls up through scrollback
        history.
        """
        if self._pty is None:
            return
        if self._pty.emulator is None:
            return
        if self._pty.mouse_tracking:
            event.stop()
            await self._pty.send_queue.put(
                ["scroll", "up", event.x, event.y]
            )
            return
        # No mouse tracking — use scroll for scrollback.
        self._scroll_up()

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