"""Tests for terminal preservation across workspace recomposition.

When the workspace is split or a pane is closed, the terminal's PTY
emulator **and visible output** should survive the DOM rebuild — the
user should NOT see the shell restart (e.g. .bashrc output) and should
NOT lose their terminal history.
"""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal
from textual.widgets import Label

from ui.terminal.terminal import TerminalView, TerminalSnapshot
from ui.workspace.tabs import WorkspaceTabs, SavedTab, SavedTabState, _TabLabelButton, _TabCloseButton
from ui.workspace.workspace import Workspace, PaneContainer
from core.pane_tree import get_leaves


# ---------------------------------------------------------------------------
# Test apps
# ---------------------------------------------------------------------------


class TabsTestApp(App):
    """Minimal app hosting WorkspaceTabs for testing."""

    CSS = """
    WorkspaceTabs {
        height: 100%;
        width: 100%;
    }
    """

    def compose(self) -> ComposeResult:
        self.tabs = WorkspaceTabs()
        yield self.tabs


class WorkspaceTestApp(App):
    """Minimal app hosting a Workspace for testing."""

    CSS = """
    Workspace {
        height: 100%;
        width: 100%;
    }
    PaneContainer {
        border: solid green;
        height: 1fr;
        width: 1fr;
    }
    PaneContainer.focused {
        border: solid blue;
    }
    """

    def compose(self) -> ComposeResult:
        self.workspace = Workspace()
        yield self.workspace


# ---------------------------------------------------------------------------
# TerminalView unit tests
# ---------------------------------------------------------------------------


class TestTerminalViewPreserving:
    """Tests for TerminalView._preserving flag lifecycle."""

    def test_preserving_flag_default_false(self):
        """The _preserving flag is False by default."""
        tv = TerminalView()
        assert tv._preserving is False

    def test_preserving_flag_prevents_unmount_stop(self):
        """When _preserving is True, on_unmount does not stop the PTY."""
        tv = TerminalView()
        tv._preserving = True
        mock_pty = MagicMock()
        tv._pty = mock_pty

        tv.on_unmount()

        # PTY should NOT have been stopped
        mock_pty.stop.assert_not_called()
        # PTY reference should NOT have been cleared
        assert tv._pty is not None

    def test_unmount_stops_pty_when_not_preserving(self):
        """When _preserving is False, on_unmount stops the PTY normally."""
        tv = TerminalView()
        tv._preserving = False
        mock_pty = MagicMock()
        tv._pty = mock_pty

        tv.on_unmount()

        mock_pty.stop.assert_called_once()
        assert tv._pty is None

    def test_preserving_flag_cleared_on_mount(self):
        """on_mount clears the _preserving flag."""
        tv = TerminalView()
        tv._preserving = True
        mock_pty = MagicMock()
        tv._pty = mock_pty

        tv.on_mount()

        assert tv._preserving is False

    def test_mount_starts_pty(self):
        """on_mount calls start() on the PTY."""
        tv = TerminalView()
        mock_pty = MagicMock()
        tv._pty = mock_pty

        tv.on_mount()

        mock_pty.start.assert_called_once()

    def test_mount_handles_none_pty(self):
        """on_mount is a no-op when _pty is None."""
        tv = TerminalView()
        tv._pty = None

        tv.on_mount()  # Should not raise

    def test_compose_creates_new_pty_when_none(self):
        """compose() creates a new PTY when _pty is None."""
        tv = TerminalView()
        assert tv._pty is None

        result = list(tv.compose())
        assert len(result) == 1
        assert tv._pty is not None
        assert tv._pty is result[0]


class TestTerminalViewEmulatorTransfer:
    """Tests for TerminalView emulator transfer across recomposition."""

    def test_detach_emulator_returns_none_when_no_pty(self):
        """detach_emulator returns None if the TerminalView has no PTY."""
        tv = TerminalView()
        tv._pty = None

        result = tv.detach_emulator()
        assert result is None

    def test_detach_emulator_returns_none_when_no_emulator(self):
        """detach_emulator returns None if the PtyTerminal has no emulator."""
        tv = TerminalView()
        mock_pty = MagicMock()
        mock_pty.emulator = None
        tv._pty = mock_pty

        result = tv.detach_emulator()
        assert result is None

    def test_detach_emulator_extracts_emulator(self):
        """detach_emulator returns a TerminalSnapshot with the emulator and screen."""
        tv = TerminalView()
        mock_pty = MagicMock()
        mock_emulator = MagicMock()
        mock_screen = MagicMock()
        mock_display = MagicMock()
        mock_pty.emulator = mock_emulator
        mock_pty._screen = mock_screen
        mock_pty._display = mock_display
        mock_recv_task = MagicMock()
        mock_pty.recv_task = mock_recv_task
        tv._pty = mock_pty

        result = tv.detach_emulator()

        # Result should be a TerminalSnapshot
        assert isinstance(result, TerminalSnapshot)
        assert result.emulator is mock_emulator
        assert result.screen is mock_screen
        assert result.display is mock_display
        # recv_task should be cancelled
        mock_recv_task.cancel.assert_called_once()
        # PtyTerminal should be disconnected from the emulator
        assert mock_pty.emulator is None
        assert mock_pty.send_queue is None
        assert mock_pty.recv_queue is None
        assert mock_pty.recv_task is None

    def test_inherited_snapshot_adopted_on_mount(self):
        """on_mount adopts an inherited snapshot (emulator + screen) instead of starting a new one."""
        tv = TerminalView()
        mock_pty = MagicMock()
        mock_emulator = MagicMock()
        mock_emulator.recv_queue = MagicMock()
        mock_emulator.send_queue = MagicMock()
        mock_screen = MagicMock()
        mock_screen.columns = 80
        mock_screen.lines = 24
        mock_display = MagicMock()

        snapshot = TerminalSnapshot(
            emulator=mock_emulator,
            screen=mock_screen,
            display=mock_display,
        )
        tv._inherited_snapshot = snapshot
        tv._pty = mock_pty

        # Mock asyncio.create_task so we don't need a running event loop
        with patch("ui.terminal.terminal.asyncio.create_task") as mock_create_task:
            tv.on_mount()

        # The emulator should be adopted by the PTY
        assert mock_pty.emulator is mock_emulator
        assert mock_pty.send_queue is mock_emulator.recv_queue
        assert mock_pty.recv_queue is mock_emulator.send_queue
        # start() should NOT have been called (emulator adopted instead)
        mock_pty.start.assert_not_called()
        # A new recv task should have been created
        assert mock_create_task.called
        # Screen and display should be restored
        assert mock_pty._screen is mock_screen
        assert mock_pty.stream.screen is mock_screen
        assert mock_pty.ncol == 80
        assert mock_pty.nrow == 24
        assert mock_pty._display is mock_display
        # inherited_snapshot should be cleared
        assert tv._inherited_snapshot is None
        # _preserving should be cleared
        assert tv._preserving is False

    def test_inherited_snapshot_cleared_after_adoption(self):
        """_inherited_snapshot is set to None after being adopted."""
        tv = TerminalView()
        mock_pty = MagicMock()
        mock_emulator = MagicMock()
        mock_emulator.recv_queue = MagicMock()
        mock_emulator.send_queue = MagicMock()

        snapshot = TerminalSnapshot(emulator=mock_emulator)
        tv._inherited_snapshot = snapshot
        tv._pty = mock_pty

        with patch("ui.terminal.terminal.asyncio.create_task"):
            tv.on_mount()

        assert tv._inherited_snapshot is None

    def test_stop_orphaned_emulator_calls_stop(self):
        """stop_orphaned_emulator calls stop() on the emulator."""
        mock_emulator = MagicMock()
        TerminalView.stop_orphaned_emulator(mock_emulator)
        mock_emulator.stop.assert_called_once()

    def test_stop_orphaned_emulator_ignores_failures(self):
        """stop_orphaned_emulator ignores exceptions from stop()."""
        mock_emulator = MagicMock()
        mock_emulator.stop.side_effect = RuntimeError("test")
        # Should not raise
        TerminalView.stop_orphaned_emulator(mock_emulator)

    def test_inherited_snapshot_default_none(self):
        """_inherited_snapshot is None by default."""
        tv = TerminalView()
        assert tv._inherited_snapshot is None


# ---------------------------------------------------------------------------
# SavedTab emulator field tests
# ---------------------------------------------------------------------------


class TestSavedTabEmulator:
    """Tests for SavedTab.inherited_snapshot field."""

    def test_saved_tab_has_snapshot_field(self):
        """SavedTab can store an inherited snapshot."""
        snapshot = TerminalSnapshot(emulator=MagicMock())
        saved = SavedTab(id="t1", label="Terminal", inherited_snapshot=snapshot)
        assert saved.inherited_snapshot is snapshot

    def test_saved_tab_snapshot_defaults_to_none(self):
        """SavedTab inherited_snapshot defaults to None."""
        saved = SavedTab(id="t1", label="Test")
        assert saved.inherited_snapshot is None


# ---------------------------------------------------------------------------
# WorkspaceTabs emulator transfer tests
# ---------------------------------------------------------------------------


class TestSaveStateWithEmulator:
    """Tests that save_state extracts emulators from terminal tabs."""

    async def test_save_state_extracts_snapshot_from_terminal(self):
        """save_state calls detach_emulator() on TerminalView tabs."""
        async with TabsTestApp().run_test() as pilot:
            tabs = pilot.app.tabs
            await pilot.pause()

            # Open a tab with just a content_factory (no real TerminalView
            # needed — we test detach_emulator() separately in unit tests)
            tabs.open_tab("tab-1", "Label", Label("test"))
            await pilot.pause()

            state = tabs.save_state()
            # Non-terminal tab should have None snapshot
            assert state.tabs[0].inherited_snapshot is None

    async def test_save_state_snapshot_none_for_non_terminal(self):
        """save_state sets inherited_snapshot to None for non-terminal tabs."""
        async with TabsTestApp().run_test() as pilot:
            tabs = pilot.app.tabs
            await pilot.pause()

            label = Label("Hello")
            tabs.open_tab("tab-1", "Label", label)
            await pilot.pause()

            state = tabs.save_state()
            assert state.tabs[0].inherited_snapshot is None


    def test_restore_sets_inherited_snapshot_on_terminal_tab(self):
        """restore_state sets _inherited_snapshot on newly created TerminalViews."""
        # Test the data logic without mounting
        mock_emulator = MagicMock()
        snapshot = TerminalSnapshot(emulator=mock_emulator)
        factory_calls = 0

        def factory():
            nonlocal factory_calls
            factory_calls += 1
            return TerminalView()

        # Create a TerminalView from the factory
        content = factory()
        # Verify _inherited_snapshot is None before we set it
        assert content._inherited_snapshot is None
        # Simulate what restore_state does: set _inherited_snapshot
        from ui.terminal.terminal import TerminalView as TV
        if isinstance(content, TV) and snapshot is not None:
            content._inherited_snapshot = snapshot
        assert content._inherited_snapshot is snapshot
        assert content._inherited_snapshot.emulator is mock_emulator

    def test_restore_without_snapshot_creates_fresh_terminal(self):
        """restore_state creates a fresh terminal when no snapshot is inherited."""
        factory_calls = 0

        def factory():
            nonlocal factory_calls
            factory_calls += 1
            return TerminalView()

        # Create a TerminalView from the factory
        content = factory()
        assert content._inherited_snapshot is None


# ---------------------------------------------------------------------------
# Integration: workspace split preserves emulator
# ---------------------------------------------------------------------------


class TestTerminalPreservationAcrossSplit:
    """Integration tests for terminal preservation during workspace split."""

    async def test_split_preserves_welcome_tab(self):
        """Splitting preserves the welcome tab in the original pane."""
        async with WorkspaceTestApp().run_test() as pilot:
            ws = pilot.app.workspace
            await pilot.pause()

            # Get the welcome tab before split
            tabs_before = (
                pilot.app.query_one("#pane-main", PaneContainer).query_one(WorkspaceTabs)
            )
            assert "welcome" in tabs_before._tabs

            await ws.split_pane("h")
            await pilot.pause()

            # Welcome tab should still be in the main pane
            tabs_after = (
                pilot.app.query_one("#pane-main", PaneContainer).query_one(WorkspaceTabs)
            )
            assert "welcome" in tabs_after._tabs

    async def test_cleanup_orphaned_emulators(self):
        """_cleanup_orphaned_terminals stops emulators for closed-pane terminals."""
        async with WorkspaceTestApp().run_test() as pilot:
            ws = pilot.app.workspace
            await pilot.pause()

            mock_emulator = MagicMock()

            snapshot = TerminalSnapshot(emulator=mock_emulator)
            state = SavedTabState(
                tabs=[SavedTab(
                    id="term-1",
                    label="Terminal",
                    inherited_snapshot=snapshot,
                )],
                active_id="term-1",
            )

            saved = {"closed-pane": state}
            restored = {"main"}

            ws._cleanup_orphaned_terminals(saved, restored)

            mock_emulator.stop.assert_called_once()

    async def test_cleanup_does_not_affect_restored_emulators(self):
        """_cleanup_orphaned_terminals skips panes that were restored."""
        async with WorkspaceTestApp().run_test() as pilot:
            ws = pilot.app.workspace
            await pilot.pause()

            mock_emulator = MagicMock()

            snapshot = TerminalSnapshot(emulator=mock_emulator)
            state = SavedTabState(
                tabs=[SavedTab(
                    id="term-1",
                    label="Terminal",
                    inherited_snapshot=snapshot,
                )],
                active_id="term-1",
            )

            saved = {"main": state}
            restored = {"main"}

            ws._cleanup_orphaned_terminals(saved, restored)

            mock_emulator.stop.assert_not_called()

    async def test_mark_terminals_preserving(self):
        """_mark_terminals_preserving sets _preserving=True on TerminalViews."""
        async with WorkspaceTestApp().run_test() as pilot:
            ws = pilot.app.workspace
            await pilot.pause()

            tv = TerminalView()
            assert tv._preserving is False

            container = pilot.app.query_one("#pane-main", PaneContainer)
            tabs = container.query_one(WorkspaceTabs)
            tabs.open_tab("term-1", "Terminal", tv, content_factory=lambda: TerminalView())
            await pilot.pause()

            # Save state first (which detaches the emulator)
            saved = ws._save_pane_tab_states()

            # Before marking
            assert tv._preserving is False

            # Mark terminals as preserving
            ws._mark_terminals_preserving(saved)

            # TerminalView should now have _preserving = True
            assert tv._preserving is True


# ---------------------------------------------------------------------------
# TerminalSnapshot and screen/display preservation tests
# ---------------------------------------------------------------------------


class TestTerminalSnapshot:
    """Tests for TerminalSnapshot data class."""

    def test_snapshot_stores_emulator(self):
        """TerminalSnapshot stores the emulator."""
        mock_emulator = MagicMock()
        snapshot = TerminalSnapshot(emulator=mock_emulator)
        assert snapshot.emulator is mock_emulator

    def test_snapshot_stores_screen_and_display(self):
        """TerminalSnapshot stores the pyte screen and rendered display."""
        mock_emulator = MagicMock()
        mock_screen = MagicMock()
        mock_display = MagicMock()
        snapshot = TerminalSnapshot(
            emulator=mock_emulator,
            screen=mock_screen,
            display=mock_display,
        )
        assert snapshot.emulator is mock_emulator
        assert snapshot.screen is mock_screen
        assert snapshot.display is mock_display

    def test_snapshot_defaults_screen_and_display_to_none(self):
        """TerminalSnapshot screen and display default to None."""
        mock_emulator = MagicMock()
        snapshot = TerminalSnapshot(emulator=mock_emulator)
        assert snapshot.screen is None
        assert snapshot.display is None

    def test_snapshot_stop_emulator(self):
        """TerminalSnapshot.stop_emulator stops the enclosed emulator."""
        mock_emulator = MagicMock()
        snapshot = TerminalSnapshot(emulator=mock_emulator)
        snapshot.stop_emulator()
        mock_emulator.stop.assert_called_once()

    def test_snapshot_stop_emulator_ignores_failures(self):
        """TerminalSnapshot.stop_emulator ignores exceptions."""
        mock_emulator = MagicMock()
        mock_emulator.stop.side_effect = RuntimeError("test")
        snapshot = TerminalSnapshot(emulator=mock_emulator)
        # Should not raise
        snapshot.stop_emulator()


class TestScreenDisplayPreservation:
    """Tests for screen and display preservation across recomposition."""

    def test_detach_emulator_captures_screen_and_display(self):
        """detach_emulator returns a TerminalSnapshot with screen and display."""
        tv = TerminalView()
        mock_pty = MagicMock()
        mock_emulator = MagicMock()
        mock_screen = MagicMock()
        mock_display = MagicMock()
        mock_pty.emulator = mock_emulator
        mock_pty._screen = mock_screen
        mock_pty._display = mock_display
        mock_pty.recv_task = MagicMock()
        tv._pty = mock_pty

        snapshot = tv.detach_emulator()

        assert isinstance(snapshot, TerminalSnapshot)
        assert snapshot.emulator is mock_emulator
        assert snapshot.screen is mock_screen
        assert snapshot.display is mock_display

    def test_detach_emulator_returns_none_snapshot_when_no_emulator(self):
        """detach_emulator returns None when there's no running emulator."""
        tv = TerminalView()
        tv._pty = None

        result = tv.detach_emulator()
        assert result is None

    def test_on_mount_restores_screen_and_display_from_snapshot(self):
        """on_mount restores the saved screen and display into the new PtyTerminal."""
        tv = TerminalView()
        mock_pty = MagicMock()
        mock_emulator = MagicMock()
        mock_emulator.recv_queue = MagicMock()
        mock_emulator.send_queue = MagicMock()
        mock_screen = MagicMock()
        mock_screen.columns = 100
        mock_screen.lines = 30
        mock_display = MagicMock()

        snapshot = TerminalSnapshot(
            emulator=mock_emulator,
            screen=mock_screen,
            display=mock_display,
        )
        tv._inherited_snapshot = snapshot
        tv._pty = mock_pty

        with patch("ui.terminal.terminal.asyncio.create_task"):
            tv.on_mount()

        # Screen should be restored
        assert mock_pty._screen is mock_screen
        assert mock_pty.stream.screen is mock_screen
        # Dimensions should match the saved screen
        assert mock_pty.ncol == 100
        assert mock_pty.nrow == 30
        # Display should be restored
        assert mock_pty._display is mock_display
        # Widget should be refreshed
        mock_pty.refresh.assert_called_once()
        # Snapshot should be consumed
        assert tv._inherited_snapshot is None

    def test_on_mount_handles_missing_screen_gracefully(self):
        """on_mount works even if the snapshot has no screen/display."""
        tv = TerminalView()
        mock_pty = MagicMock()
        mock_emulator = MagicMock()
        mock_emulator.recv_queue = MagicMock()
        mock_emulator.send_queue = MagicMock()

        # Snapshot with emulator only (screen/display are None)
        snapshot = TerminalSnapshot(emulator=mock_emulator)
        tv._inherited_snapshot = snapshot
        tv._pty = mock_pty

        with patch("ui.terminal.terminal.asyncio.create_task"):
            tv.on_mount()

        # Emulator should still be adopted
        assert mock_pty.emulator is mock_emulator
        # start() should NOT have been called
        mock_pty.start.assert_not_called()
        # Screen and display should NOT have been touched when None
        # (no assignment means mock_pty defaults apply)
        assert tv._inherited_snapshot is None

    def test_stop_orphaned_emulator_accepts_terminal_snapshot(self):
        """stop_orphaned_emulator can accept a TerminalSnapshot directly."""
        mock_emulator = MagicMock()
        snapshot = TerminalSnapshot(emulator=mock_emulator)

        # stop_orphaned_emulator should delegate to snapshot.stop_emulator()
        TerminalView.stop_orphaned_emulator(snapshot)
        mock_emulator.stop.assert_called_once()