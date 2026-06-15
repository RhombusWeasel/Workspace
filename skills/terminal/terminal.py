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

Throttled rendering
-------------------
The upstream ``textual_terminal`` library's ``recv()`` method does a
full O(rows × cols) screen render for **every** stdout message from the
PTY.  A single command can produce dozens of messages (prompt redraw,
ANSI cursor sequences, output lines, another prompt redraw), and each
one blocks the event loop while it iterates every cell.  This starves
the async loop and causes the application to hang.

We replace the upstream ``recv()`` with a throttled version that
drains all pending messages from the queue, feeds the accumulated
output to pyte in one call, then renders **once** per batch.  The
render interval (~16 ms / 60 fps) guarantees the event loop stays
responsive even under heavy terminal output.
"""

from __future__ import annotations

import asyncio
import itertools
import os
import re
import shlex
import signal
from dataclasses import dataclass, field
from typing import Any

from textual.app import ComposeResult
from textual import events
from textual.widget import Widget
from textual_terminal import Terminal as PtyTerminal
from textual_terminal._terminal import TerminalDisplay
import pyte
from pyte.screens import Char
from rich.text import Text
from rich.style import Style

from ui.workspace.tabs import TabState


# Incrementing counter for unique tab IDs.
_tab_counter = itertools.count(1)

# ANSI sequence detector — same regex as upstream textual_terminal.
_RE_ANSI_SEQUENCE = re.compile(r"(\x1b\[\??[\d;]*[a-zA-Z])")
_DECSET_PREFIX = "\x1b[?"

# Target frame interval for throttled rendering (~60 fps).
_RENDER_INTERVAL = 1 / 60


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

    _cleanup_task: asyncio.Task | None = field(default=None)
    """Background task that reaps the PTY child process."""

    def dispose(self) -> None:
        """Stop the PTY process when the tab is permanently closed.

        Uses **non-blocking** process teardown instead of calling
        ``emulator.stop()`` directly.  The upstream ``TerminalEmulator.stop()``
        calls ``os.waitpid(pid, 0)`` synchronously, which **blocks the event
        loop** if the shell doesn't respond to SIGTERM immediately — this
        caused the entire application to hang when closing a terminal tab.

        Instead, we:
        1. Cancel the emulator's internal tasks (``_run``, ``_send_data``).
        2. Send SIGTERM to the child process.
        3. Schedule a background task that polls ``os.waitpid(pid, WNOHANG)``
           every 100 ms and sends SIGKILL after a 2-second timeout.
        4. Reap the zombie once the process exits.
        """
        if self.emulator is not None:
            try:
                _async_stop_emulator(self.emulator)
            except Exception:
                pass
            self.emulator = None

        # Also clear screen/display so stale references don't linger.
        self.screen = None
        self.display = None


def next_terminal_id() -> str:
    """Return a fresh, unique tab ID like ``"term-1"``."""
    return f"term-{next(_tab_counter)}"


# ---------------------------------------------------------------------------
# Throttled recv loop — replaces upstream PtyTerminal.recv()
# ---------------------------------------------------------------------------


async def _throttled_recv(pty: PtyTerminal) -> None:
    """Throttled replacement for ``PtyTerminal.recv()``.

    The upstream method does a full O(rows × cols) screen render for
    **every** stdout message, which blocks the event loop and causes
    hangs under even moderate output.  This version:

    1. Drains **all** pending messages from ``recv_queue`` in one
       batch (non-blocking after the first ``await get()``).
    2. Feeds accumulated stdout to pyte in a single ``stream.feed()``.
    3. Renders **once** per batch.
    4. Sleeps for ``_RENDER_INTERVAL`` (~16 ms) before the next batch.

    This guarantees the event loop stays responsive regardless of how
    fast the PTY produces output.
    """
    try:
        while True:
            # Wait for the first message — this is the only blocking
            # await, so the event loop is free between batches.
            message = await pty.recv_queue.get()

            stdout_chunks: list[str] = []
            setup_requested = False
            disconnect_requested = False

            # Process the first message.
            cmd = message[0]
            if cmd == "setup":
                setup_requested = True
            elif cmd == "stdout":
                stdout_chunks.append(message[1])
            elif cmd == "disconnect":
                disconnect_requested = True

            # Drain any remaining messages that are already queued.
            # This prevents a backlog of pending renders.
            while not pty.recv_queue.empty():
                try:
                    msg = pty.recv_queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                c = msg[0]
                if c == "setup":
                    setup_requested = True
                elif c == "stdout":
                    stdout_chunks.append(msg[1])
                elif c == "disconnect":
                    disconnect_requested = True

            # Handle setup.
            if setup_requested and pty.send_queue is not None:
                await pty.send_queue.put(["set_size", pty.nrow, pty.ncol])

            # Handle disconnect — just return without calling pty.stop().
            # The upstream PtyTerminal.stop() calls emulator.stop() which
            # uses os.waitpid(pid, 0) — a BLOCKING call that freezes the
            # event loop.  Process cleanup is handled by
            # _async_stop_emulator() called from dispose() instead.
            if disconnect_requested:
                return

            # Feed all accumulated stdout to pyte in one call.
            if stdout_chunks:
                all_output = "".join(stdout_chunks)

                # Detect mouse tracking mode changes (same logic as
                # upstream recv).
                for sep_match in _RE_ANSI_SEQUENCE.finditer(all_output):
                    sequence = sep_match.group(0)
                    if sequence.startswith(_DECSET_PREFIX):
                        parameters = sequence.removeprefix(_DECSET_PREFIX).split(";")
                        if "1000h" in parameters:
                            pty.mouse_tracking = True
                        if "1000l" in parameters:
                            pty.mouse_tracking = False

                try:
                    pty.stream.feed(all_output)
                except TypeError as error:
                    from textual import log
                    log.warning("could not feed:", error)

                # Render once for the entire batch.
                _render_screen(pty)

            # Yield to the event loop — keeps the app responsive.
            await asyncio.sleep(_RENDER_INTERVAL)

    except asyncio.CancelledError:
        pass


def _render_screen(pty: PtyTerminal) -> None:
    """Render the pyte screen buffer into a ``TerminalDisplay``.

    This is the same O(rows × cols) rendering logic as upstream
    ``PtyTerminal.recv()``, extracted into a function so it can be
    called from both the throttled recv loop and scrollback
    navigation.
    """
    screen = pty._screen
    lines = []
    last_char: Char
    last_style: Style
    for y in range(screen.lines):
        line_text = Text()
        line = screen.buffer[y]
        style_change_pos: int = 0
        for x in range(screen.columns):
            char: Char = line[x]

            line_text.append(char.data)

            # if style changed, stylize it with rich
            if x > 0:
                last_char = line[x - 1]
                if not pty.char_style_cmp(char, last_char) or x == screen.columns - 1:
                    last_style = pty.char_rich_style(last_char)
                    line_text.stylize(last_style, style_change_pos, x + 1)
                    style_change_pos = x

            if (
                not getattr(screen.cursor, "hidden", False)
                and screen.cursor.x == x
                and screen.cursor.y == y
            ):
                line_text.stylize("reverse", x, x + 1)

        lines.append(line_text)

    pty._display = TerminalDisplay(lines)
    pty.refresh()


# ---------------------------------------------------------------------------
# Async process teardown — replaces blocking TerminalEmulator.stop()
# ---------------------------------------------------------------------------

# How long to wait after SIGTERM before escalating to SIGKILL.
_SIGTERM_TIMEOUT = 2.0

# How often to poll os.waitpid(pid, WNOHANG).
_POLL_INTERVAL = 0.1


def _async_stop_emulator(emulator: Any) -> None:
    """Stop a PTY emulator **without** blocking the event loop.

    The upstream ``TerminalEmulator.stop()`` calls ``os.waitpid(pid, 0)``
    synchronously, which blocks the event loop if the child process
    doesn't exit immediately after SIGTERM.  This function replaces that
    with a non-blocking teardown:

    1. Cancel the emulator's internal asyncio tasks (``_run``, ``_send_data``)
       so they stop reading from / writing to the PTY fd.
    2. Send ``SIGTERM`` to the child process.
    3. Schedule a background ``asyncio.Task`` that polls
       ``os.waitpid(pid, WNOHANG)`` every 100 ms, escalating to
       ``SIGKILL`` after 2 seconds if the process still hasn't exited.
    4. Reap the zombie once the process exits.

    This is safe to call from synchronous code (e.g. ``dispose()``).
    The actual waiting happens in the scheduled task.
    """
    pid = getattr(emulator, "pid", None)
    if pid is None:
        # No process to stop (shouldn't happen, but be safe).
        return

    # Step 1: Cancel internal tasks so they stop reading the PTY fd.
    for task_attr in ("run_task", "send_task"):
        task = getattr(emulator, task_attr, None)
        if task is not None and not task.done():
            task.cancel()

    # Step 2: Send SIGTERM.
    try:
        os.kill(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        # Process already dead — just reap.
        pass

    # Step 3 & 4: Schedule async reaping.
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_reap_process(pid))
    except RuntimeError:
        # No running loop — try to reap synchronously as a fallback.
        try:
            os.waitpid(pid, os.WNOHANG)
        except (ChildProcessError, OSError):
            pass


async def _reap_process(pid: int) -> None:
    """Poll ``os.waitpid(pid, WNOHANG)`` until the process exits.

    Sends ``SIGKILL`` after ``_SIGTERM_TIMEOUT`` seconds if the process
    still hasn't exited.  This ensures zombie processes are always
    reaped without blocking the event loop.
    """
    elapsed = 0.0
    while elapsed < _SIGTERM_TIMEOUT:
        try:
            _, status = os.waitpid(pid, os.WNOHANG)
            if status != 0 or _ == 0:
                # Process exited (status != 0 means it was signalled) or
                # no such child (== 0 with WNOHANG means not exited yet,
                # but if waitpid returns (0, 0) the child is still alive).
                # Actually, waitpid returns (pid, status) when reaped,
                # or (0, 0) when WNOHANG and child still running.
                if _ != 0:
                    return  # Successfully reaped
        except ChildProcessError:
            return  # Already reaped by someone else
        except OSError:
            return

        await asyncio.sleep(_POLL_INTERVAL)
        elapsed += _POLL_INTERVAL

    # Timeout — escalate to SIGKILL.
    try:
        os.kill(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass

    # Wait again after SIGKILL (process *will* exit now).
    try:
        os.waitpid(pid, 0)
    except (ChildProcessError, OSError):
        pass


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
        self._recv_task: asyncio.Task | None = None
        """Our throttled recv task — tracked separately so we can
        cancel/await it properly on unmount."""

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

        # Cancel our throttled recv task and await it properly.
        # We schedule the cleanup as a coroutine since flush_state
        # is synchronous.
        self._cancel_recv_task()

        # Disconnect the old PtyTerminal from the emulator so that
        # the emulator's queues are not read by two recv tasks.
        self._pty.emulator = None
        self._pty.send_queue = None
        self._pty.recv_queue = None
        self._pty.recv_task = None

    def _cancel_recv_task(self) -> None:
        """Cancel the throttled recv task and clear the reference.

        The actual await of the cancellation happens in
        ``_await_recv_cancellation()`` which is scheduled via
        ``call_later`` so it doesn't block the caller.
        """
        if self._recv_task is not None and not self._recv_task.done():
            self._recv_task.cancel()
            # Schedule the await so the task gets properly cleaned up.
            try:
                self.call_later(self._await_recv_cancellation, self._recv_task)
            except Exception:
                pass
        self._recv_task = None
        # Also clear the upstream recv_task reference if it points to
        # our task.
        if self._pty is not None:
            self._pty.recv_task = None

    @staticmethod
    async def _await_recv_cancellation(task: asyncio.Task) -> None:
        """Await a cancelled recv task to ensure it's fully stopped."""
        try:
            await task
        except asyncio.CancelledError:
            pass

    # ------------------------------------------------------------------
    # Compose
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        if self._pty is None:
            self._pty = PtyTerminal(self._command, default_colors="textual")
            # Fresh terminal — replace the default Screen with a
            # ScrollbackScreen so that lines scrolled off the top are
            # preserved in a history buffer.  The user can scroll back
            # through this buffer with the mouse wheel or Shift+Up /
            # Shift+Down.
            # Only set up the scrollback screen for fresh terminals.
            # When adopting an existing emulator, on_mount() will
            # restore state.screen instead.
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

        In both cases, we start our **throttled** recv task instead
        of the upstream one — this prevents the hang caused by the
        upstream recv() doing a full render per message.
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

            # Start our throttled recv loop.
            self._recv_task = asyncio.create_task(_throttled_recv(self._pty))
            self._pty.recv_task = self._recv_task

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
            # The upstream start() creates its own recv_task using
            # recv(), so we need to replace it with our throttled one.
            self._pty.start()
            # Cancel the upstream recv task and replace with ours.
            if self._pty.recv_task is not None and not self._pty.recv_task.done():
                self._pty.recv_task.cancel()
                # Fire-and-forget await — the cancellation will
                # propagate, we just need to ensure it's awaited.
                asyncio.ensure_future(
                    self._await_recv_cancellation(self._pty.recv_task)
                )
            self._recv_task = asyncio.create_task(_throttled_recv(self._pty))
            self._pty.recv_task = self._recv_task

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
        logic as the throttled recv loop but without processing new
        output — just re-renders what's already on the screen.

        When scrolled up, the cursor is hidden (``HistoryScreen``
        sets ``cursor.hidden``) so the cursor highlight is suppressed
        automatically.
        """
        if self._pty is None:
            return

        pty = self._pty
        screen = pty._screen

        # Use the shared render function, but handle the cursor
        # visibility for scrollback mode.
        lines = []
        for y in range(screen.lines):
            line_text = Text()
            line = screen.buffer[y]
            style_change_pos: int = 0
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

        Cleans up: cancels the recv task, unsubscribes from the theme
        signal, and saves the emulator back to state as a safety net.
        """
        if self._pty is not None:
            # Cancel our throttled recv task so it stops reading from
            # the emulator's queue.
            self._cancel_recv_task()

            # Unsubscribe from theme_changed_signal to prevent stale
            # callbacks accumulating after recomposition.
            try:
                self.app.theme_changed_signal.unsubscribe(self._pty)
            except Exception:
                pass

            # Safety net: if flush_state() was not called (e.g. during
            # an unexpected removal), save the emulator back to state
            # so it's not lost.  This prevents orphaned PTY processes.
            if self.state.emulator is None and self._pty.emulator is not None:
                self.state.emulator = self._pty.emulator
                if hasattr(self._pty, "_screen") and self._pty._screen is not None:
                    self.state.screen = self._pty._screen
                if hasattr(self._pty, "_display") and self._pty._display is not None:
                    self.state.display = self._pty._display

        self._pty = None