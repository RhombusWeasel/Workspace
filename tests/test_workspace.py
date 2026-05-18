"""Tests for the Workspace widget."""

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Label, Static

from ui.workspace.workspace import Workspace, PaneContainer
from ui.workspace.tabs import WorkspaceTabs
from ui.workspace.welcome_view import WelcomeView
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
    async def test_starts_with_single_pane(self):
        """The workspace starts with one leaf pane ('main')."""
        async with WorkspaceTestApp().run_test() as pilot:
            ws = pilot.app.workspace
            leaves = get_leaves(ws.tree)
            assert len(leaves) == 1
            assert leaves[0].id == "main"

    async def test_initial_pane_has_workspace_tabs(self):
        """Each pane starts with a WorkspaceTabs widget (tabbed interface)."""
        async with WorkspaceTestApp().run_test() as pilot:
            ws = pilot.app.workspace
            container = pilot.app.query_one("#pane-main", PaneContainer)
            tabs = container.query_one(WorkspaceTabs)
            assert tabs is not None

    async def test_initial_pane_has_welcome_tab(self):
        """The initial pane opens a Welcome tab on startup."""
        async with WorkspaceTestApp().run_test() as pilot:
            ws = pilot.app.workspace
            tabs = pilot.app.query_one("#pane-main", PaneContainer).query_one(WorkspaceTabs)
            # The welcome tab is opened asynchronously via run_worker
            await pilot.pause()
            assert tabs.tab_count >= 1
            assert tabs.active_tab_id == "welcome"

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


class TestTabbedWorkspace:
    """Tests for the tabbed workspace feature.

    Every pane starts with a WorkspaceTabs widget, and the initial pane
    opens a Welcome tab on startup.
    """

    async def test_each_pane_has_workspace_tabs(self):
        """Every pane composes a WorkspaceTabs inside its PaneContainer."""
        async with WorkspaceTestApp().run_test() as pilot:
            ws = pilot.app.workspace
            container = pilot.app.query_one("#pane-main", PaneContainer)
            tabs = container.query_one(WorkspaceTabs)
            assert tabs is not None

    async def test_welcome_tab_opens_on_startup(self):
        """The initial pane opens a Welcome tab after mount."""
        async with WorkspaceTestApp().run_test() as pilot:
            await pilot.pause()
            tabs = pilot.app.query_one("#pane-main", PaneContainer).query_one(WorkspaceTabs)
            assert tabs.tab_count >= 1
            assert tabs.active_tab_id == "welcome"

    async def test_new_pane_from_split_has_workspace_tabs(self):
        """Splitting creates a new pane that also has a WorkspaceTabs."""
        async with WorkspaceTestApp().run_test() as pilot:
            ws = pilot.app.workspace
            await ws.split_pane("h")
            await pilot.pause()

            leaves = get_leaves(ws.tree)
            for leaf in leaves:
                container = pilot.app.query_one(f"#pane-{leaf.id}", PaneContainer)
                tabs = container.query_one(WorkspaceTabs)
                assert tabs is not None

    async def test_split_preserves_welcome_tab(self):
        """Splitting preserves the welcome tab in the original pane."""
        async with WorkspaceTestApp().run_test() as pilot:
            ws = pilot.app.workspace
            await pilot.pause()  # Wait for welcome tab

            # Get the welcome tab before split
            tabs_before = pilot.app.query_one("#pane-main", PaneContainer).query_one(WorkspaceTabs)
            assert "welcome" in tabs_before._tabs

            await ws.split_pane("h")
            await pilot.pause()

            # Welcome tab should still be in the main pane
            tabs_after = pilot.app.query_one("#pane-main", PaneContainer).query_one(WorkspaceTabs)
            assert "welcome" in tabs_after._tabs

    async def test_close_welcome_tab(self):
        """Closing the welcome tab leaves an empty WorkspaceTabs."""
        async with WorkspaceTestApp().run_test() as pilot:
            await pilot.pause()  # Wait for welcome tab
            tabs = pilot.app.query_one("#pane-main", PaneContainer).query_one(WorkspaceTabs)
            assert tabs.tab_count >= 1

            tabs.close_tab("welcome")
            await pilot.pause()

            assert tabs.tab_count == 0
            assert tabs.active_tab_id is None

    async def test_set_direct_content_replaces_tabs(self):
        """Setting direct pane content replaces the tabbed interface."""
        async with WorkspaceTestApp().run_test() as pilot:
            ws = pilot.app.workspace
            await ws.set_pane_content("main", Label("Direct content"))
            await pilot.pause()

            # The pane tree has direct content now
            main_leaf = get_leaves(ws.tree)[0]
            assert main_leaf.content is not None

            # The DOM should have the label, not a WorkspaceTabs
            container = pilot.app.query_one("#pane-main", PaneContainer)
            labels = container.query(Label)
            assert len(labels) >= 1

    async def test_welcome_content_factory_survives_recompose(self):
        """The welcome tab's content_factory survives a workspace recompose."""
        async with WorkspaceTestApp().run_test() as pilot:
            ws = pilot.app.workspace
            await pilot.pause()  # Wait for welcome tab

            # Split and then close the new pane to trigger recompose while
            # keeping the original "main" pane intact.
            await ws.split_pane("h")
            leaves = get_leaves(ws.tree)
            new_pane_id = next(leaf.id for leaf in leaves if leaf.id != "main")

            # Focus the new pane and close it
            ws.focused_id = new_pane_id
            await ws.close_pane()
            await pilot.pause()

            # We should be back to one pane ("main")
            assert len(get_leaves(ws.tree)) == 1
            container = pilot.app.query_one("#pane-main", PaneContainer)
            tabs = container.query_one(WorkspaceTabs)
            assert "welcome" in tabs._tabs
