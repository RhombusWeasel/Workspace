"""Tests for the leader registry (core/leader.py)."""

import pytest


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_leader():
    """Reset the leader registry before every test."""
    from core.leader import leader, reset_leader
    reset_leader()
    yield leader


def _noop():
    """A no-op handler for testing."""
    pass


# ---------------------------------------------------------------------------
# Registration — actions and submenus
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_register_single_action(self, _reset_leader):
        """Registering a simple action creates a leaf node."""
        from core.leader import register_action

        handler = lambda: "done"
        register_action(["a"], "Action A", handler)

        root = _reset_leader.get_root()
        assert "a" in root.children
        node = root.children["a"]
        assert node.label == "Action A"
        assert node.handler is handler
        assert node.children == {}

    def test_register_nested_action(self, _reset_leader):
        """Registering a nested action creates intermediate nodes."""
        from core.leader import register_action

        handler = lambda: "nested"
        register_action(["w", "s", "h"], "Split Horizontal", handler)

        root = _reset_leader.get_root()
        # First level
        assert "w" in root.children
        w = root.children["w"]
        assert w.label == ""
        assert w.handler is None

        # Second level
        assert "s" in w.children
        s = w.children["s"]
        assert s.label == ""
        assert s.handler is None

        # Leaf
        assert "h" in s.children
        h = s.children["h"]
        assert h.label == "Split Horizontal"
        assert h.handler is handler
        assert h.children == {}

    def test_register_action_preserves_existing_subtree(self, _reset_leader):
        """Adding a sibling action does not destroy existing branches."""
        from core.leader import register_action

        h1 = lambda: "a1"
        h2 = lambda: "a2"

        register_action(["w", "s", "h"], "Split H", h1)
        register_action(["w", "s", "v"], "Split V", h2)

        root = _reset_leader.get_root()
        s = root.children["w"].children["s"]
        assert "h" in s.children
        assert "v" in s.children
        assert s.children["h"].handler is h1
        assert s.children["v"].handler is h2

    def test_register_submenu(self, _reset_leader):
        """register_submenu creates an intermediate node with a label but no handler."""
        from core.leader import register_submenu

        register_submenu(["w"], "Workspace")

        root = _reset_leader.get_root()
        w = root.children["w"]
        assert w.label == "Workspace"
        assert w.handler is None
        assert w.children == {}

    def test_register_submenu_then_action_under_it(self, _reset_leader):
        """A submenu can later have actions registered under it."""
        from core.leader import register_submenu, register_action

        register_submenu(["w"], "Workspace")
        handler = lambda: "ok"
        register_action(["w", "s"], "Split", handler)

        root = _reset_leader.get_root()
        w = root.children["w"]
        assert w.label == "Workspace"
        assert "s" in w.children

    def test_register_submenu_with_label_on_nested_action(self, _reset_leader):
        """register_action can provide labels for intermediate nodes too."""
        from core.leader import register_action

        handler = lambda: "done"
        register_action(
            ["w", "s", "h"],
            "Split Horizontal",
            handler,
            labels={"w": "Workspace", "s": "Split Pane"},
        )

        root = _reset_leader.get_root()
        w = root.children["w"]
        assert w.label == "Workspace"
        s = w.children["s"]
        assert s.label == "Split Pane"


# ---------------------------------------------------------------------------
# Conflict detection
# ---------------------------------------------------------------------------


class TestConflicts:
    def test_action_on_existing_action_raises(self, _reset_leader):
        """Registering an action at a path that already has an action raises."""
        from core.leader import register_action

        register_action(["a"], "First", lambda: 1)

        with pytest.raises(ValueError, match="already"):
            register_action(["a"], "Second", lambda: 2)

    def test_action_under_existing_action_raises(self, _reset_leader):
        """Registering a child under a leaf action raises."""
        from core.leader import register_action

        register_action(["a"], "Leaf", lambda: 1)

        with pytest.raises(ValueError, match="action at 'a'"):
            register_action(["a", "b"], "Child", lambda: 2)

    def test_action_over_existing_submenu_raises(self, _reset_leader):
        """Registering an action at a path through a leaf action raises."""
        from core.leader import register_submenu, register_action

        register_submenu(["w"], "Workspace")

        with pytest.raises(ValueError, match="already a submenu"):
            register_action(["w"], "Not OK", lambda: 1)


# ---------------------------------------------------------------------------
# Traversal
# ---------------------------------------------------------------------------


class TestTraversal:
    def test_find_existing_node(self, _reset_leader):
        """find() returns the node at the given path."""
        from core.leader import register_action, find_node

        handler = lambda: "x"
        register_action(["a", "b", "c"], "Deep", handler)

        node = find_node(["a", "b", "c"])
        assert node is not None
        assert node.label == "Deep"
        assert node.handler is handler

    def test_find_intermediate_node(self, _reset_leader):
        """find() works for intermediate nodes too."""
        from core.leader import register_action, find_node

        register_action(
            ["a", "b"], "B", lambda: 1, labels={"a": "A"}
        )

        a = find_node(["a"])
        assert a is not None
        assert a.label == "A"
        assert a.handler is None

    def test_find_nonexistent_path_returns_none(self, _reset_leader):
        """find() returns None for missing paths."""
        from core.leader import find_node

        assert find_node(["nonexistent"]) is None
        assert find_node(["a", "b"]) is None

    def test_find_empty_path_returns_root(self, _reset_leader):
        """find([]) returns the root node."""
        from core.leader import find_node

        root = find_node([])
        assert root is not None
        assert root.label == ""


# ---------------------------------------------------------------------------
# Reset
# ---------------------------------------------------------------------------


class TestReset:
    def test_reset_clears_all_nodes(self, _reset_leader):
        """After reset, the root has no children."""
        from core.leader import register_action, reset_leader

        register_action(["a", "b"], "Test", lambda: None)
        reset_leader()

        root = _reset_leader.get_root()
        assert root.children == {}

    def test_reset_allows_re_registration(self, _reset_leader):
        """After reset, previously-used paths can be registered again."""
        from core.leader import register_action, reset_leader

        register_action(["a"], "First", lambda: 1)
        reset_leader()
        # Should not raise
        register_action(["a"], "Second", lambda: 2)


# ---------------------------------------------------------------------------
# get_root() returns the same object
# ---------------------------------------------------------------------------


class TestGetRoot:
    def test_get_root_returns_root_node(self, _reset_leader):
        """get_root() returns the LeaderNode root."""
        from core.leader import register_action

        register_action(["a"], "Test", lambda: None)
        root = _reset_leader.get_root()
        assert root.label == ""
        assert "a" in root.children


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------


class TestSingleton:
    def test_module_level_leader_is_root(self):
        """leader is the module-level LeaderRegistry."""
        from core.leader import leader
        from core.leader import LeaderRegistry

        assert isinstance(leader, LeaderRegistry)
