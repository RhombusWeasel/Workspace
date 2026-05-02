"""Tests for the Workspace widget."""

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Label, Static

from ui.workspace.workspace import Workspace, PaneContainer
from core.pane_tree import get_leaves


# ---------------------------------------------------------------------------
# Minimal test app that mounts a Workspace
# ---------------------------------------------------------------------------


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
# Tests
# ---------------------------------------------------------------------------


class TestWorkspaceInitialState:
    async def test_starts_with_one_empty_pane(self):
        async with WorkspaceTestApp().run_test() as pilot:
            ws = pilot.app.workspace
            leaves = get_leaves(ws.tree)
            assert len(leaves) == 1
            assert leaves[0].id == "main"

    async def test_focused_id_is_main(self):
        async with WorkspaceTestApp().run_test() as pilot:
            ws = pilot.app.workspace
            assert ws.focused_id == "main"

    async def test_main_pane_has_focus_style(self):
        async with WorkspaceTestApp().run_test() as pilot:
            ws = pilot.app.workspace
            container = pilot.app.query_one("#pane-main", PaneContainer)
            assert container.focused is True


class TestSplit:
    async def test_split_horizontal_creates_two_panes(self):
        async with WorkspaceTestApp().run_test() as pilot:
            ws = pilot.app.workspace
            await ws.split_pane("h")
            leaves = get_leaves(ws.tree)
            assert len(leaves) == 2

    async def test_split_vertical_creates_two_panes(self):
        async with WorkspaceTestApp().run_test() as pilot:
            ws = pilot.app.workspace
            await ws.split_pane("v")
            leaves = get_leaves(ws.tree)
            assert len(leaves) == 2

    async def test_split_preserves_original_content(self):
        async with WorkspaceTestApp().run_test() as pilot:
            ws = pilot.app.workspace
            label = Label("hello")
            await ws.set_pane_content("main", label)
            await ws.split_pane("h")

            leaves = get_leaves(ws.tree)
            # Original leaf still has "main" id and its content
            main = next(leaf for leaf in leaves if leaf.id == "main")
            assert main.content is label

    async def test_split_adds_new_empty_pane(self):
        async with WorkspaceTestApp().run_test() as pilot:
            ws = pilot.app.workspace
            await ws.split_pane("h")

            leaves = get_leaves(ws.tree)
            ids = {leaf.id for leaf in leaves}
            assert "main" in ids
            # The new pane has a different id
            assert len(ids - {"main"}) == 1

    async def test_focus_stays_on_original_after_split(self):
        async with WorkspaceTestApp().run_test() as pilot:
            ws = pilot.app.workspace
            await ws.split_pane("h")
            assert ws.focused_id == "main"

    async def test_can_split_recursively(self):
        async with WorkspaceTestApp().run_test() as pilot:
            ws = pilot.app.workspace
            await ws.split_pane("h")
            await ws.split_pane("h")
            leaves = get_leaves(ws.tree)
            assert len(leaves) == 3


class TestClose:
    async def test_close_reduces_pane_count(self):
        async with WorkspaceTestApp().run_test() as pilot:
            ws = pilot.app.workspace
            await ws.split_pane("h")
            assert len(get_leaves(ws.tree)) == 2
            await ws.close_pane()
            assert len(get_leaves(ws.tree)) == 1

    async def test_close_last_pane_leaves_empty_workspace(self):
        async with WorkspaceTestApp().run_test() as pilot:
            ws = pilot.app.workspace
            await ws.close_pane()
            leaves = get_leaves(ws.tree)
            assert len(leaves) == 1
            assert leaves[0].content is None

    async def test_focus_moves_after_close(self):
        async with WorkspaceTestApp().run_test() as pilot:
            ws = pilot.app.workspace
            await ws.split_pane("h")
            leaves = get_leaves(ws.tree)
            other_id = next(leaf.id for leaf in leaves if leaf.id != "main")

            # Focus the other pane
            ws.focused_id = other_id
            await ws.close_pane()

            # Focus should now be on "main"
            assert ws.focused_id == "main"

    async def test_close_nested_pane_collapses_correctly(self):
        async with WorkspaceTestApp().run_test() as pilot:
            ws = pilot.app.workspace
            await ws.split_pane("h")
            await ws.split_pane("h")  # 3 leaves
            assert len(get_leaves(ws.tree)) == 3
            await ws.close_pane()
            assert len(get_leaves(ws.tree)) == 2


class TestNavigate:
    async def test_navigate_left_right_in_h_split(self):
        async with WorkspaceTestApp().run_test() as pilot:
            ws = pilot.app.workspace
            await ws.split_pane("h")
            leaves = get_leaves(ws.tree)
            right_id = next(leaf.id for leaf in leaves if leaf.id != "main")

            # Navigate right
            ws.navigate("right")
            assert ws.focused_id == right_id

            # Navigate left
            ws.navigate("left")
            assert ws.focused_id == "main"

    async def test_navigate_up_down_in_v_split(self):
        async with WorkspaceTestApp().run_test() as pilot:
            ws = pilot.app.workspace
            await ws.split_pane("v")
            leaves = get_leaves(ws.tree)
            bottom_id = next(leaf.id for leaf in leaves if leaf.id != "main")

            ws.navigate("down")
            assert ws.focused_id == bottom_id

            ws.navigate("up")
            assert ws.focused_id == "main"

    async def test_navigate_no_op_at_edge(self):
        async with WorkspaceTestApp().run_test() as pilot:
            ws = pilot.app.workspace
            # Single pane — no neighbors in any direction
            ws.navigate("left")
            assert ws.focused_id == "main"
            ws.navigate("right")
            assert ws.focused_id == "main"
            ws.navigate("up")
            assert ws.focused_id == "main"
            ws.navigate("down")
            assert ws.focused_id == "main"

    async def test_navigate_updates_focus_styles(self):
        async with WorkspaceTestApp().run_test() as pilot:
            ws = pilot.app.workspace
            await ws.split_pane("h")
            await pilot.pause()

            ws.navigate("right")
            await pilot.pause()

            # New focused container has the focused class
            focused_id = ws.focused_id
            container = ws.query_one(f"#pane-{focused_id}", PaneContainer)
            assert container.focused is True

            # Original lost focus
            orig = ws.query_one("#pane-main", PaneContainer)
            assert orig.focused is False

    async def test_navigate_posts_event(self):
        async with WorkspaceTestApp().run_test() as pilot:
            ws = pilot.app.workspace
            await ws.split_pane("h")
            await pilot.pause()

            ws.navigate("right")
            assert ws.focused_id != "main"


class TestClickFocus:
    async def test_click_changes_focus(self):
        async with WorkspaceTestApp().run_test() as pilot:
            ws = pilot.app.workspace
            await ws.split_pane("h")
            await pilot.pause()

            leaves = get_leaves(ws.tree)
            right_id = next(leaf.id for leaf in leaves if leaf.id != "main")

            # Click the right pane via simulated message
            ws.on_pane_container_pane_focus(PaneContainer.PaneFocus(right_id))
            await pilot.pause()
            assert ws.focused_id == right_id


class TestSetContent:
    async def test_set_content_mounts_widget(self):
        async with WorkspaceTestApp().run_test() as pilot:
            ws = pilot.app.workspace
            label = Label("Hello, World!")
            await ws.set_pane_content("main", label)

            await pilot.pause()

            # The content should be in the pane tree
            main = get_leaves(ws.tree)[0]
            assert main.content is label

            # The label should be mounted in the DOM
            labels = ws.query(Label)
            assert len(labels) == 1
            rendered = labels.first().render()
            assert "Hello, World!" in rendered.plain

    async def test_set_content_replaces_previous(self):
        async with WorkspaceTestApp().run_test() as pilot:
            ws = pilot.app.workspace
            await ws.set_pane_content("main", Label("first"))
            await ws.set_pane_content("main", Label("second"))

            await pilot.pause()

            labels = ws.query(Label)
            assert len(labels) == 1
            rendered = labels.first().render()
            assert "second" in rendered.plain

    async def test_set_content_does_nothing_for_invalid_id(self):
        async with WorkspaceTestApp().run_test() as pilot:
            ws = pilot.app.workspace
            await ws.set_pane_content("nonexistent", Label("ghost"))

            # Should not raise, and no label mounted
            labels = ws.query(Label)
            assert len(labels) == 0


class TestLeaderActions:
    async def test_action_split_horizontal(self):
        async with WorkspaceTestApp().run_test() as pilot:
            ws = pilot.app.workspace
            await ws.action_split_horizontal()
            assert len(get_leaves(ws.tree)) == 2

    async def test_action_split_vertical(self):
        async with WorkspaceTestApp().run_test() as pilot:
            ws = pilot.app.workspace
            await ws.action_split_vertical()
            assert len(get_leaves(ws.tree)) == 2

    async def test_action_close_pane(self):
        async with WorkspaceTestApp().run_test() as pilot:
            ws = pilot.app.workspace
            await ws.split_pane("h")
            await ws.action_close_pane()
            assert len(get_leaves(ws.tree)) == 1

    async def test_action_navigate(self):
        async with WorkspaceTestApp().run_test() as pilot:
            ws = pilot.app.workspace
            await ws.split_pane("h")
            leaves = get_leaves(ws.tree)
            right_id = next(leaf.id for leaf in leaves if leaf.id != "main")

            ws.action_navigate_right()
            assert ws.focused_id == right_id

            ws.action_navigate_left()
            assert ws.focused_id == "main"


class TestGetLeafIds:
    async def test_returns_ids_of_all_leaves(self):
        async with WorkspaceTestApp().run_test() as pilot:
            ws = pilot.app.workspace
            assert ws.get_leaf_ids() == ["main"]

            await ws.split_pane("h")
            ids = ws.get_leaf_ids()
            assert "main" in ids
            assert len(ids) == 2
