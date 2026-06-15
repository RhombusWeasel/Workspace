"""Tests for session persistence — core/session.py and pane tree serialisation.

Tests cover:
1. Pane tree serialisation round-trip (pane_tree_to_dict / pane_tree_from_dict)
2. TabTypeHandler registration and lookup
3. SessionManager save/restore cycle
4. Edge cases: missing chats, missing files, empty sessions
"""

import json
import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from core.pane_tree import (
    LeafPane,
    SplitPane,
    create_leaf,
    pane_tree_from_dict,
    pane_tree_to_dict,
    split,
)
from core.session import (
    SESSION_VERSION,
    TabTypeHandler,
    SessionManager,
    get_tab_type_handler,
    register_tab_type,
    _TAB_TYPE_REGISTRY,
)
from ui.workspace.tabs import TabState


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _setup_tab_handlers():
    """Ensure tab type handlers are registered for each test.

    The side-effect imports that call register_tab_type() only execute
    once per process.  This fixture ensures they're present by
    re-registering them if the registry is empty.
    """
    # Import to trigger registration (idempotent if already done)
    import ui.workspace.welcome_view  # noqa: F401
    import ui.workspace.file_edit_handler  # noqa: F401
    import skills.terminal.terminal_handler  # noqa: F401
    import skills.chat.chat_tab  # noqa: F401
    yield


@pytest.fixture
def tmp_session_path():
    """Return a temporary session file path."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield os.path.join(tmpdir, ".agents", "session.json")


@pytest.fixture
def mock_ctx():
    """Return a minimal AppContext mock."""
    ctx = MagicMock()
    ctx.working_directory = "/tmp/test"
    return ctx


# ---------------------------------------------------------------------------
# Pane tree serialisation
# ---------------------------------------------------------------------------


class TestPaneTreeSerialisation:
    """Tests for pane_tree_to_dict / pane_tree_from_dict."""

    def test_single_leaf(self):
        leaf = create_leaf("abc123")
        d = pane_tree_to_dict(leaf)
        assert d == {"type": "leaf", "id": "abc123"}

    def test_roundtrip_single_leaf(self):
        leaf = create_leaf("abc123")
        restored = pane_tree_from_dict(pane_tree_to_dict(leaf))
        assert isinstance(restored, LeafPane)
        assert restored.id == "abc123"
        assert restored.content is None

    def test_split_tree(self):
        tree = split(create_leaf("main"), "main", "h", 0.5, "right")
        d = pane_tree_to_dict(tree)
        assert d["type"] == "split"
        assert d["direction"] == "h"
        assert d["ratio"] == 0.5
        assert len(d["children"]) == 2
        assert d["children"][0]["type"] == "leaf"
        assert d["children"][0]["id"] == "main"
        assert d["children"][1]["type"] == "leaf"
        assert d["children"][1]["id"] == "right"

    def test_roundtrip_split(self):
        tree = split(create_leaf("main"), "main", "h", 0.6, "right1")
        tree = split(tree, "right1", "v", 0.7, "bottom")
        d = pane_tree_to_dict(tree)
        restored = pane_tree_from_dict(d)
        assert isinstance(restored, SplitPane)
        assert restored.direction == "h"
        assert restored.ratio == 0.6
        assert isinstance(restored.children[0], LeafPane)
        assert restored.children[0].id == "main"
        assert isinstance(restored.children[1], SplitPane)
        assert restored.children[1].direction == "v"
        assert restored.children[1].ratio == 0.7

    def test_unknown_type_raises(self):
        with pytest.raises(ValueError, match="Unknown pane type"):
            pane_tree_from_dict({"type": "unknown", "id": "x"})

    def test_content_not_serialised(self):
        """Leaf content (widgets) must not appear in serialised output."""
        leaf = LeafPane(id="x", content=MagicMock())
        d = pane_tree_to_dict(leaf)
        assert "content" not in d

    def test_roundtrip_preserves_ids(self):
        tree = split(create_leaf("a1"), "a1", "v", 0.3, "b2")
        tree = split(tree, "b2", "h", 0.75, "c3")
        restored = pane_tree_from_dict(pane_tree_to_dict(tree))

        from core.pane_tree import get_leaves
        original_ids = {l.id for l in get_leaves(tree)}
        restored_ids = {l.id for l in get_leaves(restored)}
        assert original_ids == restored_ids


# ---------------------------------------------------------------------------
# TabTypeHandler registry
# ---------------------------------------------------------------------------


class TestTabTypeRegistry:
    """Tests for register_tab_type and get_tab_type_handler."""

    def test_register_and_lookup(self):
        handler = TabTypeHandler(
            tab_type="test",
            serialise=lambda s: {},
            deserialise=lambda d, ctx: TabState(),
            content_factory=lambda s: None,
        )
        register_tab_type(handler)
        assert get_tab_type_handler("test") is handler

    def test_lookup_missing_returns_none(self):
        assert get_tab_type_handler("nonexistent") is None

    def test_register_duplicate_overwrites(self):
        h1 = TabTypeHandler(
            tab_type="dup",
            serialise=lambda s: {"v": 1},
            deserialise=lambda d, ctx: TabState(),
            content_factory=lambda s: None,
        )
        h2 = TabTypeHandler(
            tab_type="dup",
            serialise=lambda s: {"v": 2},
            deserialise=lambda d, ctx: TabState(),
            content_factory=lambda s: None,
        )
        register_tab_type(h1)
        register_tab_type(h2)
        assert get_tab_type_handler("dup") is h2

    def test_welcome_handler(self):
        """Verify the welcome handler registered in welcome_view.py."""
        import ui.workspace.welcome_view  # noqa: F401 — side-effect import
        handler = get_tab_type_handler("welcome")
        assert handler is not None
        state = handler.deserialise({}, MagicMock())
        assert isinstance(state, TabState)

    def test_file_editor_handler(self):
        """Verify the file_editor handler registered in file_edit_handler.py."""
        import ui.workspace.file_edit_handler  # noqa: F401
        handler = get_tab_type_handler("file_editor")
        assert handler is not None
        # Serialise a file editor state
        from ui.workspace.file_editor import FileEditorState
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".py", delete=False) as f:
            f.write(b"print('hello')\n")
            f.flush()
            state = FileEditorState(f.name)
            data = handler.serialise(state)
            assert data["filepath"] == f.name
            # Deserialise should work
            restored = handler.deserialise(data, MagicMock())
            assert isinstance(restored, FileEditorState)
            assert restored.filepath == f.name
            os.unlink(f.name)

    def test_file_editor_handler_missing_file(self):
        """Deserialising a file editor for a non-existent file returns None."""
        import ui.workspace.file_edit_handler  # noqa: F401
        handler = get_tab_type_handler("file_editor")
        result = handler.deserialise({"filepath": "/nonexistent/file.py"}, MagicMock())
        assert result is None

    def test_terminal_handler(self):
        """Verify the terminal handler registered in terminal_handler.py."""
        import skills.terminal.terminal_handler  # noqa: F401
        handler = get_tab_type_handler("terminal")
        assert handler is not None
        ctx = MagicMock()
        ctx.working_directory = "/home/user"
        state = handler.deserialise({"command": None, "working_directory": "/home/user"}, ctx)
        from skills.terminal.terminal import TerminalState
        assert isinstance(state, TerminalState)
        assert state.working_directory == "/home/user"
        data = handler.serialise(state)
        assert data["working_directory"] == "/home/user"

    def test_chat_handler(self):
        """Verify the chat handler registered in chat_tab.py."""
        import skills.chat.chat_tab  # noqa: F401
        handler = get_tab_type_handler("chat")
        assert handler is not None
        ctx = MagicMock()
        state = handler.deserialise({"chat_id": "abc123", "agent_id": None}, ctx)
        from skills.chat.chat_tab import ChatTabState
        assert isinstance(state, ChatTabState)
        assert state._chat_id == "abc123"
        assert state._agent_id is None


# ---------------------------------------------------------------------------
# SessionManager save/restore
# ---------------------------------------------------------------------------


class TestSessionManagerSave:
    """Tests for SessionManager.save()."""

    def test_save_creates_file(self, tmp_session_path, mock_ctx):
        mgr = SessionManager(tmp_session_path, mock_ctx)
        workspace = MagicMock()
        workspace.tree = create_leaf("main")
        workspace.focused_id = "main"
        workspace.get_leaf_ids.return_value = ["main"]
        workspace.app.query_one.side_effect = Exception("no DOM")

        # Should not raise even if DOM queries fail
        mgr.save(workspace, left_sidebar_hidden=False, right_sidebar_hidden=True)

        assert os.path.exists(tmp_session_path)
        with open(tmp_session_path) as f:
            data = json.load(f)
        assert data["version"] == SESSION_VERSION
        assert data["focused_pane_id"] == "main"
        assert data["sidebar"]["left_hidden"] is False
        assert data["sidebar"]["right_hidden"] is True

    def test_save_empty_workspace(self, tmp_session_path, mock_ctx):
        mgr = SessionManager(tmp_session_path, mock_ctx)
        workspace = MagicMock()
        workspace.tree = create_leaf("main")
        workspace.focused_id = "main"
        workspace.get_leaf_ids.return_value = ["main"]
        workspace.app.query_one.side_effect = Exception("no DOM")

        mgr.save(workspace, left_sidebar_hidden=True, right_sidebar_hidden=True)

        with open(tmp_session_path) as f:
            data = json.load(f)
        assert data["pane_tree"]["type"] == "leaf"
        assert data["pane_tree"]["id"] == "main"
        assert data["tabs_by_pane"] == {"main": []}

    def test_save_split_workspace(self, tmp_session_path, mock_ctx):
        mgr = SessionManager(tmp_session_path, mock_ctx)
        tree = split(create_leaf("left"), "left", "h", 0.5, "right")
        workspace = MagicMock()
        workspace.tree = tree
        workspace.focused_id = "left"
        workspace.get_leaf_ids.return_value = ["left", "right"]
        workspace.app.query_one.side_effect = Exception("no DOM")

        mgr.save(workspace, left_sidebar_hidden=False, right_sidebar_hidden=False)

        with open(tmp_session_path) as f:
            data = json.load(f)
        assert data["pane_tree"]["type"] == "split"
        assert data["pane_tree"]["direction"] == "h"


class TestSessionManagerRestore:
    """Tests for SessionManager.restore()."""

    def test_has_session_false_when_no_file(self, tmp_session_path, mock_ctx):
        mgr = SessionManager(tmp_session_path, mock_ctx)
        assert mgr.has_session is False

    def test_has_session_true_when_file_exists(self, tmp_session_path, mock_ctx):
        # Write a minimal session file
        os.makedirs(os.path.dirname(tmp_session_path), exist_ok=True)
        with open(tmp_session_path, "w") as f:
            json.dump({"version": SESSION_VERSION, "pane_tree": {"type": "leaf", "id": "main"}}, f)
        mgr = SessionManager(tmp_session_path, mock_ctx)
        assert mgr.has_session is True

    def test_restore_returns_false_when_no_file(self, tmp_session_path, mock_ctx):
        mgr = SessionManager(tmp_session_path, mock_ctx)
        workspace = MagicMock()
        left = MagicMock()
        right = MagicMock()
        assert mgr.restore(workspace, left, right) is False

    def test_restore_returns_false_on_corrupt_file(self, tmp_session_path, mock_ctx):
        os.makedirs(os.path.dirname(tmp_session_path), exist_ok=True)
        with open(tmp_session_path, "w") as f:
            f.write("NOT JSON")
        mgr = SessionManager(tmp_session_path, mock_ctx)
        workspace = MagicMock()
        left = MagicMock()
        right = MagicMock()
        assert mgr.restore(workspace, left, right) is False

    def test_restore_returns_false_on_version_mismatch(self, tmp_session_path, mock_ctx):
        os.makedirs(os.path.dirname(tmp_session_path), exist_ok=True)
        with open(tmp_session_path, "w") as f:
            json.dump({"version": 999, "pane_tree": {"type": "leaf", "id": "main"}}, f)
        mgr = SessionManager(tmp_session_path, mock_ctx)
        workspace = MagicMock()
        left = MagicMock()
        right = MagicMock()
        assert mgr.restore(workspace, left, right) is False


# ---------------------------------------------------------------------------
# Handler name resolution (_find_handler)
# ---------------------------------------------------------------------------


class TestHandlerNameResolution:
    """Tests for SessionManager._find_handler()."""

    def test_chat_tab_state_resolves(self, mock_ctx, tmp_session_path):
        from skills.chat.chat_tab import ChatTabState
        import skills.chat.chat_tab  # noqa — registers handler
        mgr = SessionManager(tmp_session_path, mock_ctx)
        handler = mgr._find_handler(ChatTabState(ctx=mock_ctx))
        assert handler is not None
        assert handler.tab_type == "chat"

    def test_terminal_state_resolves(self, mock_ctx, tmp_session_path):
        from skills.terminal.terminal import TerminalState
        import skills.terminal.terminal_handler  # noqa — registers handler
        mgr = SessionManager(tmp_session_path, mock_ctx)
        handler = mgr._find_handler(TerminalState())
        assert handler is not None
        assert handler.tab_type == "terminal"

    def test_file_editor_state_resolves(self, mock_ctx, tmp_session_path):
        from ui.workspace.file_editor import FileEditorState
        import ui.workspace.file_edit_handler  # noqa — registers handler
        mgr = SessionManager(tmp_session_path, mock_ctx)
        handler = mgr._find_handler(FileEditorState("/tmp/test.py"))
        assert handler is not None
        assert handler.tab_type == "file_editor"

    def test_plain_tab_state_returns_none(self, mock_ctx, tmp_session_path):
        mgr = SessionManager(tmp_session_path, mock_ctx)
        handler = mgr._find_handler(TabState())
        # "TabState" → strip "State" → "Tab" → strip "Tab" → "" → not in registry
        # But welcome is registered as "welcome", not ""
        assert handler is None  # plain TabState has no registered handler by name

    def test_welcome_tab_state_resolves(self, mock_ctx, tmp_session_path):
        import ui.workspace.welcome_view  # noqa — registers handler
        mgr = SessionManager(tmp_session_path, mock_ctx)
        # Welcome uses plain TabState, which resolves to "" and won't match "welcome"
        # This is expected — welcome is registered as "welcome" but TabState class name
        # doesn't resolve to "welcome". The welcome handler will be looked up by
        # the tab_type stored in the session file, not by _find_handler.
        handler = mgr._find_handler(TabState())
        assert handler is None  # As designed — welcome uses explicit tab_type in session data


# ---------------------------------------------------------------------------
# Round-trip: save → load → save produces same data
# ---------------------------------------------------------------------------


class TestSessionRoundTrip:
    """End-to-end test: serialise a pane tree, save, load, and verify."""

    def test_roundtrip_json(self, tmp_session_path, mock_ctx):
        tree = split(create_leaf("main"), "main", "h", 0.6, "right")
        d = pane_tree_to_dict(tree)

        # Simulate save/load cycle
        json_str = json.dumps(d)
        loaded = json.loads(json_str)
        restored = pane_tree_from_dict(loaded)

        assert isinstance(restored, SplitPane)
        assert restored.direction == "h"
        assert restored.ratio == 0.6
        assert isinstance(restored.children[0], LeafPane)
        assert restored.children[0].id == "main"
        assert isinstance(restored.children[1], LeafPane)
        assert restored.children[1].id == "right"

    def test_version_field_preserved(self, tmp_session_path, mock_ctx):
        mgr = SessionManager(tmp_session_path, mock_ctx)
        workspace = MagicMock()
        workspace.tree = create_leaf("main")
        workspace.focused_id = "main"
        workspace.get_leaf_ids.return_value = ["main"]
        workspace.app.query_one.side_effect = Exception("no DOM")

        mgr.save(workspace, left_sidebar_hidden=True, right_sidebar_hidden=True)

        with open(tmp_session_path) as f:
            data = json.load(f)
        assert data["version"] == SESSION_VERSION