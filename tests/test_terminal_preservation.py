"""Tests for TabState architecture and terminal preservation across workspace
recomposition.

When the workspace is split or a pane is closed, tab state should survive
the DOM rebuild — the user should NOT see the shell restart (e.g. .bashrc
output) and should NOT lose their terminal history.  The TabState model
ensures this by keeping state in a persistent object owned by the tab slot,
not by the widget.
"""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal
from textual.widgets import Label

from plugins.terminal.terminal import TerminalState, TerminalView, next_terminal_id
from ui.workspace.tabs import TabState, WorkspaceTabs, SavedTab, SavedTabState, _TabLabelButton, _TabCloseButton
from plugins.database.query_editor import QueryEditorState
from ui.workspace.file_editor import FileEditorState
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
# TabState base class tests
# ---------------------------------------------------------------------------


class TestTabState:
    """Tests for the TabState base class."""

    def test_dispose_is_noop(self):
        """TabState.dispose() is a no-op in the base class."""
        state = TabState()
        # Should not raise
        state.dispose()

    def test_subclass_dispose(self):
        """Subclasses can override dispose() for cleanup."""
        cleaned = []

        class MyState(TabState):
            def dispose(self):
                cleaned.append(True)

        state = MyState()
        state.dispose()
        assert cleaned == [True]


# ---------------------------------------------------------------------------
# TerminalState tests
# ---------------------------------------------------------------------------


class TestTerminalState:
    """Tests for TerminalState dataclass."""

    def test_terminal_state_defaults(self):
        """TerminalState has None defaults for command and working_directory."""
        state = TerminalState()
        assert state.command is None
        assert state.working_directory is None
        assert state.emulator is None
        assert state.screen is None
        assert state.display is None

    def test_terminal_state_with_command(self):
        """TerminalState stores command and working directory."""
        state = TerminalState(command="/bin/bash", working_directory="/tmp")
        assert state.command == "/bin/bash"
        assert state.working_directory == "/tmp"

    def test_terminal_state_dispose_stops_emulator(self):
        """TerminalState.dispose() stops the emulator."""
        mock_emulator = MagicMock()
        state = TerminalState(command="/bin/bash", emulator=mock_emulator)
        state.dispose()
        mock_emulator.stop.assert_called_once()
        assert state.emulator is None

    def test_terminal_state_dispose_ignores_exceptions(self):
        """TerminalState.dispose() ignores exceptions from emulator.stop()."""
        mock_emulator = MagicMock()
        mock_emulator.stop.side_effect = RuntimeError("boom")
        state = TerminalState(command="/bin/bash", emulator=mock_emulator)
        # Should not raise
        state.dispose()
        assert state.emulator is None

    def test_terminal_state_dispose_with_no_emulator(self):
        """TerminalState.dispose() is safe when emulator is None."""
        state = TerminalState(command="/bin/bash")
        # Should not raise
        state.dispose()


# ---------------------------------------------------------------------------
# TerminalView unit tests
# ---------------------------------------------------------------------------


class TestTerminalView:
    """Tests for TerminalView with the new TabState model."""

    def test_terminal_view_receives_state(self):
        """TerminalView.__init__ accepts a TerminalState parameter."""
        state = TerminalState(command="/bin/bash")
        tv = TerminalView(state)
        assert tv.state is state
        assert tv.state.command == "/bin/bash"

    def test_terminal_view_builds_command_with_working_dir(self):
        """TerminalView builds a cd+exec command when working_directory is set."""
        state = TerminalState(command="/bin/bash", working_directory="/tmp")
        tv = TerminalView(state)
        # Should contain cd and exec
        assert "cd" in tv._command
        assert "/bin/bash" in tv._command

    def test_flush_state_captures_emulator(self):
        """TerminalView.flush_state() writes emulator back to state."""
        state = TerminalState(command="/bin/bash")
        tv = TerminalView(state)
        mock_pty = MagicMock()
        mock_emulator = MagicMock()
        mock_pty.emulator = mock_emulator
        mock_pty._screen = MagicMock()
        mock_pty._display = MagicMock()
        mock_recv_task = MagicMock()
        mock_pty.recv_task = mock_recv_task
        tv._pty = mock_pty

        tv.flush_state()

        assert state.emulator is mock_emulator
        assert state.screen is mock_pty._screen
        assert state.display is mock_pty._display
        # recv_task should be cancelled
        mock_recv_task.cancel.assert_called_once()
        # Pty should be disconnected from emulator
        assert mock_pty.emulator is None
        assert mock_pty.send_queue is None
        assert mock_pty.recv_queue is None

    def test_flush_state_noop_when_no_pty(self):
        """TerminalView.flush_state() is safe when _pty is None."""
        state = TerminalState(command="/bin/bash")
        tv = TerminalView(state)
        tv._pty = None
        # Should not raise
        tv.flush_state()

    def test_on_mount_adopts_existing_emulator(self):
        """on_mount adopts the emulator from state.emulator when present."""
        mock_emulator = MagicMock()
        mock_emulator.recv_queue = MagicMock()
        mock_emulator.send_queue = MagicMock()
        mock_screen = MagicMock()
        mock_screen.columns = 80
        mock_screen.lines = 24
        mock_display = MagicMock()

        state = TerminalState(
            command="/bin/bash",
            emulator=mock_emulator,
            screen=mock_screen,
            display=mock_display,
        )
        tv = TerminalView(state)
        mock_pty = MagicMock()
        tv._pty = mock_pty

        with patch("plugins.terminal.terminal.asyncio.create_task"):
            tv.on_mount()

        # The emulator should be adopted by the PTY
        assert mock_pty.emulator is mock_emulator
        assert mock_pty.send_queue is mock_emulator.recv_queue
        assert mock_pty.recv_queue is mock_emulator.send_queue
        # start() should NOT have been called (emulator adopted instead)
        mock_pty.start.assert_not_called()
        # Screen and display should be restored
        assert mock_pty._screen is mock_screen
        assert mock_pty.stream.attach.called
        mock_pty.stream.attach.assert_called_with(mock_screen)
        assert mock_pty.ncol == 80
        assert mock_pty.nrow == 24
        assert mock_pty._display is mock_display

    def test_on_mount_starts_fresh_when_no_emulator(self):
        """on_mount starts a new shell when state has no emulator."""
        state = TerminalState(command="/bin/bash")
        tv = TerminalView(state)
        mock_pty = MagicMock()
        tv._pty = mock_pty

        tv.on_mount()

        # start() should be called for a fresh terminal
        mock_pty.start.assert_called_once()

    def test_stream_attach_uses_listener_not_screen(self):
        """pyte.Stream uses .listener (not .screen) for processing.

        This test verifies that on_mount uses stream.attach() to
        properly re-attach the pyte stream to the saved screen.
        Setting stream.screen would create a useless attribute
        without changing where stream.feed() sends output.
        """
        import pyte

        # Create a pyte Stream with one screen
        screen_a = pyte.Screen(80, 24)
        stream = pyte.Stream(screen_a)
        stream.feed("ScreenA")

        # Verify stream.listener is the active screen
        assert stream.listener is screen_a
        assert screen_a.display[0].startswith("ScreenA")

        # Create another screen and use attach() (the fix)
        screen_b = pyte.Screen(80, 24)
        stream.attach(screen_b)
        stream.feed("ScreenB")

        # Output now goes to screen_b (via listener), not screen_a
        assert stream.listener is screen_b
        assert screen_b.display[0].startswith("ScreenB")
        assert not screen_a.display[0].startswith("ScreenB")

    def test_on_unmount_does_not_stop_pty(self):
        """on_unmount does not stop the PTY — lifecycle is managed by state."""
        state = TerminalState(command="/bin/bash")
        tv = TerminalView(state)
        mock_pty = MagicMock()
        tv._pty = mock_pty

        tv.on_unmount()

        # PTY should NOT have been stopped (managed by TerminalState.dispose)
        mock_pty.stop.assert_not_called()
        # PTY reference is cleared
        assert tv._pty is None


# ---------------------------------------------------------------------------
# QueryEditorState tests
# ---------------------------------------------------------------------------


class TestQueryEditorState:
    """Tests for QueryEditorState dataclass."""

    def test_state_roundtrip(self):
        """QueryEditorState captures all editor state fields."""
        from plugins.database.core.db_connections import QueryResult

        result = QueryResult(
            columns=["id", "name"],
            rows=[(1, "Alice"), (2, "Bob")],
            total_count=2,
            has_more=False,
        )

        state = QueryEditorState(
            connection_id="abc123",
            query_text="SELECT * FROM users WHERE id > 0;",
            last_result=result,
            current_query="SELECT * FROM users WHERE id > 0;",
            current_offset=0,
            page_size=100,
        )

        assert state.connection_id == "abc123"
        assert state.query_text == "SELECT * FROM users WHERE id > 0;"
        assert state.last_result is not None
        assert state.last_result.columns == ["id", "name"]
        assert len(state.last_result.rows) == 2
        assert state.current_query == "SELECT * FROM users WHERE id > 0;"
        assert state.current_offset == 0
        assert state.page_size == 100

    def test_state_default_values(self):
        """QueryEditorState optional fields default correctly."""
        state = QueryEditorState(connection_id="test")

        assert state.query_text == ""
        assert state.last_result is None
        assert state.current_query == ""
        assert state.current_offset == 0
        assert state.page_size == 200

    def test_state_with_pagination(self):
        """QueryEditorState pagination state roundtrips correctly."""
        from plugins.database.core.db_connections import QueryResult

        result = QueryResult(
            columns=["id"],
            rows=[(i,) for i in range(200)],
            total_count=500,
            has_more=True,
        )

        state = QueryEditorState(
            connection_id="conn1",
            query_text="SELECT * FROM big_table;",
            last_result=result,
            current_query="SELECT * FROM big_table;",
            current_offset=200,
            page_size=200,
        )

        assert state.current_offset == 200
        assert state.last_result.has_more is True
        assert state.last_result.total_count == 500

    def test_state_dispose_is_noop(self):
        """QueryEditorState.dispose() is a no-op (connections are pooled)."""
        state = QueryEditorState(connection_id="test")
        # Should not raise
        state.dispose()


# ---------------------------------------------------------------------------
# FileEditorState tests
# ---------------------------------------------------------------------------


class TestFileEditorState:
    """Tests for FileEditorState."""

    def test_state_stores_filepath(self):
        """FileEditorState stores the filepath."""
        state = FileEditorState("/path/to/file.py")
        assert state.filepath == "/path/to/file.py"

    def test_state_dispose_is_noop(self):
        """FileEditorState.dispose() is a no-op (content lives on disk)."""
        state = FileEditorState("/path/to/file.py")
        # Should not raise
        state.dispose()


# ---------------------------------------------------------------------------
# SavedTab / WorkspaceTabs state transfer tests
# ---------------------------------------------------------------------------


class TestSavedTabWithState:
    """Tests for SavedTab with TabState objects (replacing snapshots)."""

    def test_saved_tab_has_state_field(self):
        """SavedTab stores a TabState object."""
        state = TerminalState(command="/bin/bash")
        saved = SavedTab(id="t1", label="Terminal", state=state)
        assert saved.state is state

    def test_saved_tab_with_query_editor_state(self):
        """SavedTab stores a QueryEditorState."""
        state = QueryEditorState(connection_id="abc", query_text="SELECT 1;")
        saved = SavedTab(id="q1", label="Query", state=state)
        assert saved.state is state
        assert saved.state.connection_id == "abc"


class TestWorkspaceTabsStateTransfer:
    """Tests that save_state / restore_state transfer TabState objects."""

    async def test_save_state_calls_flush_state(self):
        """save_state calls flush_state() on widgets that have it."""
        # We need to test with a real widget that has flush_state.
        # TerminalView has flush_state().
        state = TerminalState(command="/bin/bash")
        tv = TerminalView(state)
        mock_pty = MagicMock()
        mock_emulator = MagicMock()
        mock_pty.emulator = mock_emulator
        mock_pty._screen = MagicMock()
        mock_pty._display = MagicMock()
        mock_pty.recv_task = MagicMock()
        tv._pty = mock_pty

        async with TabsTestApp().run_test() as pilot:
            tabs = pilot.app.tabs
            await pilot.pause()

            tabs.open_tab("term-1", "Terminal", state=state, content=tv)
            await pilot.pause()

            saved_state = tabs.save_state()
            # flush_state should have written the emulator to state
            assert state.emulator is mock_emulator

    async def test_restore_state_passes_state_to_factory(self):
        """restore_state passes the state object to the content factory."""
        factory_calls = []

        def factory(s: TabState) -> Label:
            factory_calls.append(s)
            return Label("test")

        state = TabState()

        async with TabsTestApp().run_test() as pilot:
            tabs = pilot.app.tabs
            await pilot.pause()

            tabs.open_tab("tab-1", "Label", state=state, content_factory=factory)
            await pilot.pause()

            saved = tabs.save_state()
            tabs.restore_state(saved)

            # Factory should have been called with the state object
            assert len(factory_calls) >= 1
            assert factory_calls[-1] is state

    async def test_cleanup_orphaned_states(self):
        """_cleanup_orphaned_states disposes state for closed-pane tabs."""
        async with WorkspaceTestApp().run_test() as pilot:
            ws = pilot.app.workspace
            await pilot.pause()

            mock_emulator = MagicMock()
            state = TerminalState(command="/bin/bash", emulator=mock_emulator)

            saved_tab = SavedTab(
                id="term-1",
                label="Terminal",
                state=state,
            )

            saved_dict = {"closed-pane": SavedTabState(tabs=[saved_tab], active_id="term-1")}
            restored = {"main"}

            ws._cleanup_orphaned_states(saved_dict, restored)

            # Emulator should have been stopped
            mock_emulator.stop.assert_called_once()

    async def test_cleanup_does_not_affect_restored_states(self):
        """_cleanup_orphaned_states skips panes that were restored."""
        async with WorkspaceTestApp().run_test() as pilot:
            ws = pilot.app.workspace
            await pilot.pause()

            mock_emulator = MagicMock()
            state = TerminalState(command="/bin/bash", emulator=mock_emulator)

            saved_tab = SavedTab(
                id="term-1",
                label="Terminal",
                state=state,
            )

            saved_dict = {"main": SavedTabState(tabs=[saved_tab], active_id="term-1")}
            restored = {"main"}

            ws._cleanup_orphaned_states(saved_dict, restored)

            # Emulator should NOT have been stopped (pane was restored)
            mock_emulator.stop.assert_not_called()


# ---------------------------------------------------------------------------
# Integration: workspace split preserves state
# ---------------------------------------------------------------------------


class TestStatePreservationAcrossSplit:
    """Integration tests for state preservation during workspace split."""

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