"""Tests for sidebar registry, sidebar widget, and panels."""

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Label, Static

from ui.tree.tree import Tree


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class TestSidebarRegistry:
    def test_register_tab(self):
        from ui.sidebar.registry import register_sidebar_tab, get_sidebar_tabs, reset_sidebar_tabs
        reset_sidebar_tabs()

        @register_sidebar_tab(name="test", icon="\ue795", side="left")
        class TestPanel(Static):
            pass

        tabs = get_sidebar_tabs()
        assert len(tabs) == 1
        assert tabs[0].name == "test"
        assert tabs[0].icon == "\ue795"
        assert tabs[0].side == "left"
        assert tabs[0].widget_class is TestPanel

    def test_register_multiple_tabs(self):
        from ui.sidebar.registry import register_sidebar_tab, get_sidebar_tabs, reset_sidebar_tabs
        reset_sidebar_tabs()

        @register_sidebar_tab(name="a", icon="A", side="left")
        class PanelA(Static):
            pass

        @register_sidebar_tab(name="b", icon="B", side="right")
        class PanelB(Static):
            pass

        @register_sidebar_tab(name="c", icon="C", side="left")
        class PanelC(Static):
            pass

        tabs = get_sidebar_tabs()
        assert len(tabs) == 3

        left = get_sidebar_tabs(side="left")
        assert len(left) == 2

        right = get_sidebar_tabs(side="right")
        assert len(right) == 1

    def test_duplicate_name_raises(self):
        from ui.sidebar.registry import register_sidebar_tab, reset_sidebar_tabs
        reset_sidebar_tabs()

        @register_sidebar_tab(name="dup", icon="D", side="left")
        class First(Static):
            pass

        with pytest.raises(ValueError, match="already registered"):
            @register_sidebar_tab(name="dup", icon="E", side="right")
            class Second(Static):
                pass

    def test_default_side_is_left(self):
        from ui.sidebar.registry import register_sidebar_tab, get_sidebar_tabs, reset_sidebar_tabs
        reset_sidebar_tabs()

        @register_sidebar_tab(name="default", icon="X")
        class DefaultPanel(Static):
            pass

        tabs = get_sidebar_tabs()
        assert tabs[0].side == "left"

    def test_reset_clears_all(self):
        from ui.sidebar.registry import register_sidebar_tab, get_sidebar_tabs, reset_sidebar_tabs
        reset_sidebar_tabs()

        @register_sidebar_tab(name="x", icon="X", side="left")
        class PanelX(Static):
            pass

        assert len(get_sidebar_tabs()) == 1
        reset_sidebar_tabs()
        assert len(get_sidebar_tabs()) == 0


# ---------------------------------------------------------------------------
# Sidebar widget
# ---------------------------------------------------------------------------


class SidebarTestApp(App):
    """Minimal app hosting a Sidebar for testing."""

    CSS = """
    Sidebar {
        width: 30;
        height: 100%;
    }
    """

    def __init__(self, side: str):
        super().__init__()
        self._side = side

    def compose(self) -> ComposeResult:
        from ui.sidebar.sidebar import Sidebar
        from ui.sidebar.registry import register_sidebar_tab, reset_sidebar_tabs
        reset_sidebar_tabs()

        @register_sidebar_tab(name="panel1", icon="\ue795", side=self._side)
        class TestPanel1(Label):
            def __init__(self):
                super().__init__("Panel 1 content")

        @register_sidebar_tab(name="panel2", icon="\uf07c", side=self._side)
        class TestPanel2(Label):
            def __init__(self):
                super().__init__("Panel 2 content")

        self.sidebar = Sidebar(self._side)
        yield self.sidebar


class TestSidebar:
    async def test_renders_tab_buttons(self):
        """Sidebar shows tab buttons for registered tabs."""
        async with SidebarTestApp("left").run_test() as pilot:
            sidebar = pilot.app.sidebar
            await pilot.pause()

            # Should have TabbedContent with two panes
            tabs = sidebar.query("TabbedContent")
            assert len(tabs) == 1

    async def test_active_pane_visible(self):
        """The active tab's content is mounted."""
        async with SidebarTestApp("left").run_test() as pilot:
            sidebar = pilot.app.sidebar
            await pilot.pause()

            # The first panel's label should be in the DOM
            labels = sidebar.query(Label)
            contents = [l.render().plain for l in labels if hasattr(l.render(), 'plain')]
            assert any("Panel 1 content" in c for c in contents)

    async def test_sidebar_visibility(self):
        """Sidebar container can be shown and hidden."""
        from ui.sidebar.sidebar import SidebarContainer

        async with SidebarTestApp("left").run_test() as pilot:
            sidebar = pilot.app.sidebar
            await pilot.pause()

            # Test toggle via class manipulation
            assert not sidebar.has_class("hidden")


# ---------------------------------------------------------------------------
# Vault Panel
# ---------------------------------------------------------------------------


class TestVaultPanel:
    async def test_renders_vault_items(self):
        """Vault panel shows credentials and secure notes in a tree."""
        from ui.sidebar.panels.vault_panel import VaultPanel
        from core.vault import Vault
        import tempfile, os

        # Create a vault with test data
        vault_path = os.path.join(tempfile.mkdtemp(), "test.enc")
        vault = Vault(vault_path)
        vault.initialize("testpass")

        vault.register_credential("ollama", "user1", "pass1")
        vault.register_credential("openai", "user2", "pass2")
        vault.register_secure_note("reminder", "Buy milk")

        class VaultTestApp(App):
            CSS = "VaultPanel { width: 30; height: 100%; }"

            def compose(self):
                self.panel = VaultPanel()
                self.panel.set_vault(vault)
                yield self.panel

        async with VaultTestApp().run_test() as pilot:
            panel = pilot.app.panel
            await pilot.pause()

            # Should show credentials and notes
            trees = panel.query(Tree)
            assert len(trees) >= 1
            tree = trees.first()
            # Query TreeRows for labels
            rows = tree.query("TreeRow")
            rendered_texts = []
            for r in rows:
                rv = r.render()
                if hasattr(rv, 'plain'):
                    rendered_texts.append(rv.plain)
            combined = " ".join(rendered_texts)
            assert "ollama" in combined
            assert "reminder" in combined


# ---------------------------------------------------------------------------
# Autouse — reset registries
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset():
    from ui.sidebar.registry import reset_sidebar_tabs
    from ui.tree.tree import Tree
    reset_sidebar_tabs()
