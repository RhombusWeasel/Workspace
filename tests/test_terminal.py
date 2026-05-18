"""Tests for the terminal view and terminal handler."""

from __future__ import annotations

import os

import pytest

from core.events import _handler_registry, reset_handlers
from core.leader import leader, reset_leader
from core.terminal_passthrough import (
    get_terminal_passthrough_keys,
    register_terminal_passthrough,
    reset_terminal_passthrough,
)


# ---------------------------------------------------------------------------
# TerminalView — unit tests (no Textual app needed)
# ---------------------------------------------------------------------------


class TestTerminalView:
    """Tests for :class:`~ui.terminal.terminal.TerminalView`."""

    def test_import(self):
        """TerminalView can be imported."""
        from ui.terminal.terminal import TerminalView
        assert TerminalView is not None

    def test_default_command_uses_shell_env(self, monkeypatch):
        """When no command is given, $SHELL is used."""
        from ui.terminal.terminal import TerminalState, TerminalView

        monkeypatch.setenv("SHELL", "/bin/zsh")
        state = TerminalState()
        tv = TerminalView(state)
        assert tv._command == "/bin/zsh"

    def test_shell_fallback(self, monkeypatch):
        """When $SHELL is unset, falls back to /bin/sh."""
        from ui.terminal.terminal import TerminalState, TerminalView

        monkeypatch.delenv("SHELL", raising=False)
        state = TerminalState()
        tv = TerminalView(state)
        assert tv._command == "/bin/sh"

    def test_custom_command(self):
        """A custom command overrides $SHELL."""
        from ui.terminal.terminal import TerminalState, TerminalView

        state = TerminalState(command="/usr/bin/python3")
        tv = TerminalView(state)
        assert tv._command == "/usr/bin/python3"

    def test_working_directory_wrapping(self, monkeypatch):
        """When a working_directory is given, the command wraps with cd."""
        from ui.terminal.terminal import TerminalState, TerminalView

        monkeypatch.setenv("SHELL", "/bin/bash")
        state = TerminalState(working_directory="/tmp/my project")
        tv = TerminalView(state)
        assert "/tmp/my project" in tv._command
        assert "cd" in tv._command
        assert "exec" in tv._command

    def test_no_working_directory_no_cd(self, monkeypatch):
        """Without a working_directory, the command is just the shell."""
        from ui.terminal.terminal import TerminalState, TerminalView

        monkeypatch.setenv("SHELL", "/bin/bash")
        state = TerminalState()
        tv = TerminalView(state)
        assert tv._command == "/bin/bash"

    def test_working_directory_spaces_quoted(self, monkeypatch):
        """Paths with spaces are properly quoted for shlex.split()."""
        import shlex
        from ui.terminal.terminal import TerminalState, TerminalView

        monkeypatch.setenv("SHELL", "/bin/bash")
        wd = "/tmp/has spaces/and more"
        state = TerminalState(working_directory=wd)
        tv = TerminalView(state)
        # The command must round-trip through shlex.split()
        argv = shlex.split(tv._command)
        assert argv[0] == "/bin/bash"
        assert argv[1] == "-c"
        assert wd in argv[2]

    def test_next_terminal_id_increments(self):
        """next_terminal_id returns unique IDs on each call."""
        from ui.terminal.terminal import next_terminal_id

        id1 = next_terminal_id()
        id2 = next_terminal_id()
        assert id1 != id2
        assert id1.startswith("term-")
        assert id2.startswith("term-")


# ---------------------------------------------------------------------------
# Terminal handler registration
# ---------------------------------------------------------------------------


class TestTerminalHandler:
    """Tests for terminal event handler registration."""

    def setup_method(self):
        reset_handlers()
        reset_leader()
        # Re-register the terminal handler (reset cleared the import-time
        # registration, and Python's import cache won't re-run the decorator).
        from core.events import register_handler
        from ui.terminal.terminal_handler import _on_terminal_open
        register_handler("terminal.open")(_on_terminal_open)

    def test_handler_registered(self):
        """terminal.open handler is registered on import."""
        import ui.terminal.terminal_handler  # noqa: F401
        assert "terminal.open" in _handler_registry

    def test_leader_chords_registered(self):
        """Leader chords for terminal are registered correctly."""
        from ui.terminal.terminal_handler import register_terminal_leader_chords
        register_terminal_leader_chords()

        root = leader.get_root()
        t_node = root.children.get("t")
        assert t_node is not None
        assert t_node.is_submenu is True
        assert t_node.label == "Terminal"

        o_node = t_node.children.get("o")
        assert o_node is not None
        assert o_node.event_type == "terminal.open"

    def test_leader_chords_dont_conflict_with_workspace(self):
        """Terminal chords are separate from workspace chords."""
        from ui.terminal.terminal_handler import register_terminal_leader_chords
        from ui.workspace.workspace import register_workspace_leader_chords

        register_terminal_leader_chords()
        register_workspace_leader_chords()

        root = leader.get_root()
        assert "t" in root.children
        assert "w" in root.children
        # workspace chords still work
        w_node = root.children["w"]
        assert "s" in w_node.children


# ---------------------------------------------------------------------------
# Passthrough registry
# ---------------------------------------------------------------------------


class TestTerminalPassthrough:
    """Tests for the terminal passthrough key registry."""

    def setup_method(self):
        reset_terminal_passthrough()

    def test_register_adds_keys(self):
        """Registering keys adds them to the set."""
        register_terminal_passthrough({"ctrl+q", "ctrl+space"})
        assert "ctrl+q" in get_terminal_passthrough_keys()
        assert "ctrl+space" in get_terminal_passthrough_keys()

    def test_register_merges(self):
        """Multiple registrations merge, not replace."""
        register_terminal_passthrough({"ctrl+q"})
        register_terminal_passthrough({"ctrl+h"})
        keys = get_terminal_passthrough_keys()
        assert "ctrl+q" in keys
        assert "ctrl+h" in keys

    def test_reset_clears(self):
        """Reset clears all registered keys."""
        register_terminal_passthrough({"ctrl+q"})
        reset_terminal_passthrough()
        assert len(get_terminal_passthrough_keys()) == 0

    def test_app_wiring(self):
        """CodyApp.terminal_passthrough_keys includes all registered keys."""
        # Re-register the keys that were cleared by setup_method
        from ui.workspace.workspace import register_workspace_leader_chords
        from ui.terminal.terminal_handler import register_terminal_leader_chords

        # main.py registers ctrl+q and ctrl+space on import
        register_terminal_passthrough({"ctrl+q", "ctrl+space"})
        # workspace.py registers navigation keys on import
        register_terminal_passthrough({"ctrl+h", "ctrl+l", "ctrl+k", "ctrl+j", "ctrl+left", "ctrl+right", "ctrl+up", "ctrl+down"})

        from main import CodyApp
        from bootstrap import Bootstrap
        import os

        bootstrap = Bootstrap(working_directory=os.getcwd())
        context = bootstrap.run()
        app = CodyApp(context)

        passthrough = app.terminal_passthrough_keys
        # App-level keys
        assert "ctrl+q" in passthrough
        assert "ctrl+space" in passthrough
        # Workspace navigation keys
        assert "ctrl+h" in passthrough
        assert "ctrl+l" in passthrough
        assert "ctrl+k" in passthrough
        assert "ctrl+j" in passthrough