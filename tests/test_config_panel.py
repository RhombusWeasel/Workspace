"""Tests for the ConfigPanel sidebar tab."""

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Button

from core.config import Config
from ui.tree.tree import Tree
from ui.tree.tree_row import TreeRow, TreeNode


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_edit_button(buttons) -> Button | None:
    """Find an edit button by its id pattern (not label text).

    Config panel edit buttons use Nerd Font icons as labels, so
    we match on the ``-edit`` action_id suffix in the button id
    (format: ``act-{node_id}-{action_id}``).
    """
    for b in buttons:
        if hasattr(b, 'id') and b.id and b.id.endswith('-edit'):
            return b
    return None


# ---------------------------------------------------------------------------
# Autouse — reset registries between tests
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset():
    from ui.sidebar.registry import reset_sidebar_tabs
    reset_sidebar_tabs()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(data: dict, tmp_path) -> Config:
    """Create a Config with given data loaded from a temp file."""
    import json, os

    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir(exist_ok=True)
    cfg_file = cfg_dir / "settings.json"
    cfg_file.write_text(json.dumps(data))
    return Config([str(cfg_file)])


# ---------------------------------------------------------------------------
# ConfigPanel tests
# ---------------------------------------------------------------------------


class TestConfigPanelRegistration:
    def test_registers_as_sidebar_tab(self):
        """Importing the module registers ConfigPanel as a sidebar tab."""
        from ui.sidebar.panels.config_panel import ConfigPanel  # noqa: F401
        from ui.sidebar.registry import get_sidebar_tabs

        tabs = get_sidebar_tabs()
        names = [t.name for t in tabs]
        assert "config" in names

        cfg_tab = [t for t in tabs if t.name == "config"][0]
        assert cfg_tab.side == "left"
        assert cfg_tab.widget_class is ConfigPanel


class TestConfigPanelRendering:
    async def test_renders_tree_with_config_data(self, tmp_path):
        """ConfigPanel shows config keys as a tree."""
        from ui.sidebar.panels.config_panel import ConfigPanel
        cfg = _make_config(
            {"session": {"provider": "ollama", "model": "llama3"},
             "ui": {"theme": "haxor"}},
            tmp_path,
        )

        class TestApp(App):
            CSS = "ConfigPanel { width: 40; height: 100%; }"

            def compose(self):
                self.panel = ConfigPanel()
                self.panel.set_config(cfg)
                yield self.panel

        async with TestApp().run_test() as pilot:
            await pilot.pause()

            panel = pilot.app.panel
            tree = panel.query_one(Tree)
            assert tree is not None

            # Root node should be "Configuration"
            assert tree.root.label == "Configuration"

            # Should have branch nodes for "session" and "ui"
            assert any("session" in c.label for c in tree.root.children)
            assert any("ui" in c.label for c in tree.root.children)

    async def test_leaf_nodes_show_key_and_value(self, tmp_path):
        """Leaf config entries show as 'key: value' labels."""
        from ui.sidebar.panels.config_panel import ConfigPanel
        cfg = _make_config({"timeout": 30, "debug": False}, tmp_path)

        class TestApp(App):
            CSS = "ConfigPanel { width: 40; height: 100%; }"

            def compose(self):
                self.panel = ConfigPanel()
                self.panel.set_config(cfg)
                yield self.panel

        async with TestApp().run_test() as pilot:
            await pilot.pause()

            panel = pilot.app.panel
            tree = panel.query_one(Tree)

            # Find leaf node labels — they should contain key: value
            # Expand all branches so leaves are visible
            tree.expand_all()
            await pilot.pause()

            visible_rows = tree.query(TreeRow)
            labels = [r.node.label for r in visible_rows]
            assert any("timeout" in l and "30" in l for l in labels)
            assert any("debug" in l and "False" in l for l in labels)

    async def test_nested_dicts_become_branch_nodes(self, tmp_path):
        """Nested dict config keys become expandable branch nodes."""
        from ui.sidebar.panels.config_panel import ConfigPanel
        cfg = _make_config(
            {"a": {"b": {"c": "deep"}}},
            tmp_path,
        )

        class TestApp(App):
            CSS = "ConfigPanel { width: 40; height: 100%; }"

            def compose(self):
                self.panel = ConfigPanel()
                self.panel.set_config(cfg)
                yield self.panel

        async with TestApp().run_test() as pilot:
            await pilot.pause()

            panel = pilot.app.panel
            tree = panel.query_one(Tree)

            # Root has one child: "a" (branch)
            assert len(tree.root.children) == 1
            a_node = tree.root.children[0]
            assert "a" in a_node.label
            assert len(a_node.children) == 1  # "b" branch

            b_node = a_node.children[0]
            assert "b" in b_node.label
            assert len(b_node.children) == 1  # "c: deep" leaf

            c_node = b_node.children[0]
            assert "c" in c_node.label and "deep" in c_node.label

    async def test_list_values_are_expandable_branches(self, tmp_path):
        """List values become branch nodes with indexed children."""
        from ui.sidebar.panels.config_panel import ConfigPanel
        cfg = _make_config({"allowed_hosts": ["localhost", "127.0.0.1"]}, tmp_path)

        class TestApp(App):
            CSS = "ConfigPanel { width: 40; height: 100%; }"

            def compose(self):
                self.panel = ConfigPanel()
                self.panel.set_config(cfg)
                yield self.panel

        async with TestApp().run_test() as pilot:
            await pilot.pause()

            panel = pilot.app.panel
            tree = panel.query_one(Tree)
            tree.expand_all()
            await pilot.pause()

            rows = tree.query(TreeRow)
            labels = [r.node.label for r in rows]
            # List node shows key and item count
            assert any("allowed_hosts" in l and "[2]" in l for l in labels), f"labels: {labels}"
            # Scalar items inside the list show as indexed leaves
            assert any("[0]" in l and "localhost" in l for l in labels), f"labels: {labels}"
            assert any("[1]" in l and "127.0.0.1" in l for l in labels), f"labels: {labels}"

    async def test_boolean_values_preserved(self, tmp_path):
        """Boolean values are shown correctly and not confused with strings."""
        from ui.sidebar.panels.config_panel import ConfigPanel
        cfg = _make_config({"flag": True}, tmp_path)

        class TestApp(App):
            CSS = "ConfigPanel { width: 40; height: 100%; }"

            def compose(self):
                self.panel = ConfigPanel()
                self.panel.set_config(cfg)
                yield self.panel

        async with TestApp().run_test() as pilot:
            await pilot.pause()

            panel = pilot.app.panel
            tree = panel.query_one(Tree)
            tree.expand_all()
            await pilot.pause()

            rows = tree.query(TreeRow)
            labels = [r.node.label for r in rows]
            assert any("True" in l for l in labels)

    async def test_null_values_displayed(self, tmp_path):
        """None values are shown as 'None'."""
        from ui.sidebar.panels.config_panel import ConfigPanel
        cfg = _make_config({"optional": None}, tmp_path)

        class TestApp(App):
            CSS = "ConfigPanel { width: 40; height: 100%; }"

            def compose(self):
                self.panel = ConfigPanel()
                self.panel.set_config(cfg)
                yield self.panel

        async with TestApp().run_test() as pilot:
            await pilot.pause()

            panel = pilot.app.panel
            tree = panel.query_one(Tree)
            tree.expand_all()
            await pilot.pause()

            rows = tree.query(TreeRow)
            labels = [r.node.label for r in rows]
            assert any("None" in l for l in labels)

    async def test_empty_config_shows_empty_message(self, tmp_path):
        """When config has no data, show a placeholder message."""
        from ui.sidebar.panels.config_panel import ConfigPanel
        cfg = _make_config({}, tmp_path)

        class TestApp(App):
            CSS = "ConfigPanel { width: 40; height: 100%; }"

            def compose(self):
                self.panel = ConfigPanel()
                self.panel.set_config(cfg)
                yield self.panel

        async with TestApp().run_test() as pilot:
            await pilot.pause()

            panel = pilot.app.panel
            tree = panel.query_one(Tree)
            # Root exists but has no children
            assert tree.root.label == "Configuration"

    async def test_edit_auto_persists_changes(self, tmp_path):
        """Editing a value automatically persists it to the config file."""
        from ui.sidebar.panels.config_panel import ConfigPanel
        from textual.widgets import Input
        cfg = _make_config({"editable": "before"}, tmp_path)

        class TestApp(App):
            CSS = "ConfigPanel { width: 40; height: 100%; }"

            def compose(self):
                self.panel = ConfigPanel()
                self.panel.set_config(cfg)
                yield self.panel

        async with TestApp().run_test() as pilot:
            await pilot.pause()

            panel = pilot.app.panel
            tree = panel.query_one(Tree)
            tree.expand_all()
            await pilot.pause()

            all_btns = list(panel.query("Button"))
            edit_btn = _find_edit_button(all_btns)
            edit_btn.press()
            await pilot.pause()

            screen = pilot.app.screen
            modal_input = screen.query_one("#modal-input", Input)
            modal_input.value = "after"
            ok_btn = screen.query_one("#btn-ok", Button)
            ok_btn.press()
            await pilot.pause()

            # Value should be persisted to the config file
            cfg2 = Config(cfg._paths)
            assert cfg2.get("editable") == "after"

    async def test_set_config_rebuilds_tree(self, tmp_path):
        """Calling set_config with a different config replaces the tree data."""
        from ui.sidebar.panels.config_panel import ConfigPanel

        cfg1 = _make_config({"first": "value1"}, tmp_path)
        cfg2 = _make_config({"second": "value2"}, tmp_path)

        class TestApp(App):
            CSS = "ConfigPanel { width: 40; height: 100%; }"

            def compose(self):
                self.panel = ConfigPanel()
                self.panel.set_config(cfg1)
                yield self.panel

        async with TestApp().run_test() as pilot:
            await pilot.pause()

            panel = pilot.app.panel

            # First config
            tree = panel.query_one(Tree)
            tree.expand_all()
            await pilot.pause()
            rows1 = tree.query(TreeRow)
            labels1 = [r.node.label for r in rows1]
            assert any("first" in l for l in labels1)

            # Switch config
            panel.set_config(cfg2)
            await pilot.pause()

            tree2 = panel.query_one(Tree)
            tree2.expand_all()
            await pilot.pause()
            rows2 = tree2.query(TreeRow)
            labels2 = [r.node.label for r in rows2]
            assert any("second" in l for l in labels2)
            assert not any("first" in l for l in labels2)


class TestConfigPanelEditing:
    async def test_edit_button_on_leaf_nodes(self, tmp_path):
        """Each leaf node has an Edit button (shown as a Nerd Font icon)."""
        from ui.sidebar.panels.config_panel import ConfigPanel
        cfg = _make_config({"key": "val"}, tmp_path)

        class TestApp(App):
            CSS = "ConfigPanel { width: 40; height: 100%; }"

            def compose(self):
                self.panel = ConfigPanel()
                self.panel.set_config(cfg)
                yield self.panel

        async with TestApp().run_test() as pilot:
            await pilot.pause()

            panel = pilot.app.panel
            tree = panel.query_one(Tree)
            tree.expand_all()
            await pilot.pause()

            action_rows = [r for r in tree.query(TreeRow) if r.node.buttons]
            assert len(action_rows) == 1  # one leaf with Edit button
            row = action_rows[0]
            buttons = row.query(Button)
            # Button uses an icon label; verify by action_id in the button id.
            btn_ids = {b.id for b in buttons if b.id}
            assert any(bid.endswith("-edit") for bid in btn_ids)

    async def test_edit_opens_modal_with_current_value(self, tmp_path):
        """Pressing Edit on a leaf node opens an InputModal pre-filled with the value."""
        from ui.sidebar.panels.config_panel import ConfigPanel
        cfg = _make_config({"host": "localhost"}, tmp_path)

        class TestApp(App):
            CSS = "ConfigPanel { width: 40; height: 100%; }"

            def compose(self):
                self.panel = ConfigPanel()
                self.panel.set_config(cfg)
                yield self.panel

        async with TestApp().run_test() as pilot:
            await pilot.pause()

            panel = pilot.app.panel
            tree = panel.query_one(Tree)
            tree.expand_all()
            await pilot.pause()

            # Click the Edit button on the leaf row
            all_btns = list(panel.query("Button"))
            edit_btn = _find_edit_button(all_btns)
            assert edit_btn is not None
            edit_btn.press()
            await pilot.pause()

            # An InputModal should be visible now
            from ui.widgets.input_modal import InputModal
            # The pushed screen itself is the InputModal
            assert isinstance(pilot.app.screen, InputModal)

            # The input should be pre-filled with the current value
            from textual.widgets import Input
            modal_input = pilot.app.screen.query_one("#modal-input", Input)
            assert modal_input.value == "localhost"

    async def test_edit_updates_config_value(self, tmp_path):
        """Submitting a new value via the edit modal updates Config.set()."""
        from ui.sidebar.panels.config_panel import ConfigPanel
        cfg = _make_config({"port": 8080}, tmp_path)

        class TestApp(App):
            CSS = "ConfigPanel { width: 40; height: 100%; }"

            def compose(self):
                self.panel = ConfigPanel()
                self.panel.set_config(cfg)
                yield self.panel

        async with TestApp().run_test() as pilot:
            await pilot.pause()

            panel = pilot.app.panel
            tree = panel.query_one(Tree)
            tree.expand_all()
            await pilot.pause()

            # Press Edit
            all_btns = list(panel.query("Button"))
            edit_btn = _find_edit_button(all_btns)
            edit_btn.press()
            await pilot.pause()

            # Type a new value and submit
            from ui.widgets.input_modal import InputModal
            from textual.widgets import Input
            # The pushed screen IS the InputModal — query its children directly
            screen = pilot.app.screen
            modal_input = screen.query_one("#modal-input", Input)
            modal_input.value = "9090"
            # Simulate submit via the OK button
            ok_btn = screen.query_one("#btn-ok", Button)
            ok_btn.press()
            await pilot.pause()

            # Config should be updated (type coerced from int original)
            assert cfg.get("port") == 9090

            # Give the worker time to rebuild the tree after the edit
            await pilot.pause()

            # Tree should be rebuilt showing new value
            tree2 = panel.query_one(Tree)
            tree2.expand_all()
            await pilot.pause()
            rows = tree2.query(TreeRow)
            labels = [r.node.label for r in rows]
            assert any("9090" in l for l in labels)

    async def test_edit_cancel_does_not_change_value(self, tmp_path):
        """Cancelling the edit modal leaves the value unchanged."""
        from ui.sidebar.panels.config_panel import ConfigPanel
        cfg = _make_config({"name": "original"}, tmp_path)

        class TestApp(App):
            CSS = "ConfigPanel { width: 40; height: 100%; }"

            def compose(self):
                self.panel = ConfigPanel()
                self.panel.set_config(cfg)
                yield self.panel

        async with TestApp().run_test() as pilot:
            await pilot.pause()

            panel = pilot.app.panel
            tree = panel.query_one(Tree)
            tree.expand_all()
            await pilot.pause()

            all_btns = list(panel.query("Button"))
            edit_btn = _find_edit_button(all_btns)
            edit_btn.press()
            await pilot.pause()

            # Cancel
            from ui.widgets.input_modal import InputModal
            # The pushed screen IS the InputModal — query its children directly
            screen = pilot.app.screen
            cancel_btn = screen.query_one("#btn-cancel", Button)
            cancel_btn.press()
            await pilot.pause()

            # Value unchanged
            assert cfg.get("name") == "original"

    async def test_edit_on_nested_key(self, tmp_path):
        """Editing a nested key uses the correct dot-path for Config.set()."""
        from ui.sidebar.panels.config_panel import ConfigPanel
        cfg = _make_config(
            {"database": {"host": "db.local", "port": 5432}},
            tmp_path,
        )

        class TestApp(App):
            CSS = "ConfigPanel { width: 40; height: 100%; }"

            def compose(self):
                self.panel = ConfigPanel()
                self.panel.set_config(cfg)
                yield self.panel

        async with TestApp().run_test() as pilot:
            await pilot.pause()

            panel = pilot.app.panel
            tree = panel.query_one(Tree)
            tree.expand_all()
            await pilot.pause()

            # Find the Edit button for the port leaf
            # There should be two leaf rows with buttons: host and port
            action_rows = [r for r in tree.query(TreeRow) if r.node.buttons]
            assert len(action_rows) == 2

            # Press Edit on the port row
            port_row = [r for r in action_rows if "port" in r.node.label][0]
            port_btns = list(port_row.query(Button))
            port_edit = _find_edit_button(port_btns)
            port_edit.press()
            await pilot.pause()

            from ui.widgets.input_modal import InputModal
            from textual.widgets import Input
            # The pushed screen IS the InputModal — query its children directly
            screen = pilot.app.screen
            modal_input = screen.query_one("#modal-input", Input)
            modal_input.value = "9999"
            ok_btn = screen.query_one("#btn-ok", Button)
            ok_btn.press()
            await pilot.pause()

            # The nested key should be updated via dot-path (type coerced from int original)
            assert cfg.get("database.port") == 9999

    async def test_type_coercion_boolean_input(self, tmp_path):
        """Input 'true' or 'false' should be coerced to Python bool."""
        from ui.sidebar.panels.config_panel import ConfigPanel
        cfg = _make_config({"enabled": True}, tmp_path)

        class TestApp(App):
            CSS = "ConfigPanel { width: 40; height: 100%; }"

            def compose(self):
                self.panel = ConfigPanel()
                self.panel.set_config(cfg)
                yield self.panel

        async with TestApp().run_test() as pilot:
            await pilot.pause()

            panel = pilot.app.panel
            tree = panel.query_one(Tree)
            tree.expand_all()
            await pilot.pause()

            all_btns = list(panel.query("Button"))
            edit_btn = _find_edit_button(all_btns)
            edit_btn.press()
            await pilot.pause()

            from ui.widgets.input_modal import InputModal
            from textual.widgets import Input
            # The pushed screen IS the InputModal — query its children directly
            screen = pilot.app.screen
            modal_input = screen.query_one("#modal-input", Input)
            modal_input.value = "false"
            ok_btn = screen.query_one("#btn-ok", Button)
            ok_btn.press()
            await pilot.pause()

            # Should be actual bool False, not string "false"
            assert cfg.get("enabled") is False
            assert isinstance(cfg.get("enabled"), bool)

    async def test_type_coercion_number_input(self, tmp_path):
        """Numeric string input should be coerced to int/float if original was numeric."""
        from ui.sidebar.panels.config_panel import ConfigPanel
        cfg = _make_config({"count": 42, "ratio": 3.14}, tmp_path)

        class TestApp(App):
            CSS = "ConfigPanel { width: 40; height: 100%; }"

            def compose(self):
                self.panel = ConfigPanel()
                self.panel.set_config(cfg)
                yield self.panel

        async with TestApp().run_test() as pilot:
            await pilot.pause()

            panel = pilot.app.panel
            tree = panel.query_one(Tree)
            tree.expand_all()
            await pilot.pause()

            action_rows = list(tree.query(TreeRow))
            count_row = [r for r in action_rows if "count" in r.node.label][0]
            count_btns = list(count_row.query(Button))
            count_edit = _find_edit_button(count_btns)
            count_edit.press()
            await pilot.pause()

            from ui.widgets.input_modal import InputModal
            from textual.widgets import Input
            # The pushed screen IS the InputModal — query its children directly
            screen = pilot.app.screen
            modal_input = screen.query_one("#modal-input", Input)
            modal_input.value = "100"
            ok_btn = screen.query_one("#btn-ok", Button)
            ok_btn.press()
            await pilot.pause()

            assert cfg.get("count") == 100
            assert isinstance(cfg.get("count"), int)

    async def test_type_coercion_null_input(self, tmp_path):
        """Input 'null' or 'None' should set value to Python None."""
        from ui.sidebar.panels.config_panel import ConfigPanel
        cfg = _make_config({"maybe": "something"}, tmp_path)

        class TestApp(App):
            CSS = "ConfigPanel { width: 40; height: 100%; }"

            def compose(self):
                self.panel = ConfigPanel()
                self.panel.set_config(cfg)
                yield self.panel

        async with TestApp().run_test() as pilot:
            await pilot.pause()

            panel = pilot.app.panel
            tree = panel.query_one(Tree)
            tree.expand_all()
            await pilot.pause()

            all_btns = list(panel.query("Button"))
            edit_btn = _find_edit_button(all_btns)
            edit_btn.press()
            await pilot.pause()

            from ui.widgets.input_modal import InputModal
            from textual.widgets import Input
            # The pushed screen IS the InputModal — query its children directly
            screen = pilot.app.screen
            modal_input = screen.query_one("#modal-input", Input)
            modal_input.value = "null"
            ok_btn = screen.query_one("#btn-ok", Button)
            ok_btn.press()
            await pilot.pause()

            assert cfg.get("maybe") is None


class TestConfigPanelAppContext:
    """Test that ConfigPanel populates the tree when config is wired
    from AppContext during on_mount (the real-app lifecycle).

    Previous bug: on_mount() called set_config(), which checked
    is_mounted before rebuilding.  During on_mount(), is_mounted
    is False, so _rebuild() was never called and the tree stayed
    empty.
    """

    async def test_config_from_app_context_shows_tree(self, tmp_path):
        """Config wired via AppContext in on_mount() should populate the tree."""
        from context import AppContext
        from ui.sidebar.panels.config_panel import ConfigPanel
        cfg = _make_config(
            {"session": {"provider": "ollama", "model": "deepseek"},
             "ui": {"theme": "haxor"}},
            tmp_path,
        )

        class TestApp(App):
            CSS = "ConfigPanel { width: 40; height: 100%; }"

            def __init__(self, context):
                self.context = context
                context.app = self
                super().__init__()

            def compose(self):
                # NOTE: do NOT call set_config() here — imitate real app
                # where the panel gets its config from AppContext.on_mount()
                yield ConfigPanel()

        ctx = AppContext(config=cfg)

        async with TestApp(ctx).run_test() as pilot:
            await pilot.pause()

            panel = pilot.app.query_one(ConfigPanel)
            tree = panel.query_one(Tree)
            tree.expand_all()
            await pilot.pause()

            # Root node exists
            assert tree.root.label == "Configuration"
            # Config data should appear as children (not just an empty root)
            assert len(tree.root.children) > 0
            # Should have branch nodes for top-level keys
            branch_labels = [c.label for c in tree.root.children]
            assert any("session" in l for l in branch_labels)
            assert any("ui" in l for l in branch_labels)


class TestConfigPanelListRendering:
    """Tests for the config panel rendering lists and dicts-in-lists."""

    async def test_list_becomes_branch_with_count(self, tmp_path):
        """A list config value becomes a branch node showing the item count."""
        from ui.sidebar.panels.config_panel import ConfigPanel
        cfg = _make_config({"ports": [80, 443, 8080]}, tmp_path)

        class TestApp(App):
            CSS = "ConfigPanel { width: 40; height: 100%; }"

            def compose(self):
                self.panel = ConfigPanel()
                self.panel.set_config(cfg)
                yield self.panel

        async with TestApp().run_test() as pilot:
            await pilot.pause()

            panel = pilot.app.panel
            tree = panel.query_one(Tree)
            tree.expand_all()
            await pilot.pause()

            # List node shows key and count
            list_node = tree.root.children[0]
            assert "ports" in list_node.label
            assert "[3]" in list_node.label
            # List has 3 leaf children (one per scalar item)
            assert len(list_node.children) == 3

    async def test_list_of_scalar_items_are_editable_leaves(self, tmp_path):
        """Scalar list items appear as editable leaf nodes with [N] indices."""
        from ui.sidebar.panels.config_panel import ConfigPanel
        cfg = _make_config({"colors": ["red", "green", "blue"]}, tmp_path)

        class TestApp(App):
            CSS = "ConfigPanel { width: 40; height: 100%; }"

            def compose(self):
                self.panel = ConfigPanel()
                self.panel.set_config(cfg)
                yield self.panel

        async with TestApp().run_test() as pilot:
            await pilot.pause()

            panel = pilot.app.panel
            tree = panel.query_one(Tree)
            tree.expand_all()
            await pilot.pause()

            list_node = tree.root.children[0]
            child_labels = [c.label for c in list_node.children]
            assert any("[0]" in l and "red" in l for l in child_labels)
            assert any("[1]" in l and "green" in l for l in child_labels)
            assert any("[2]" in l and "blue" in l for l in child_labels)

            # Scalar items have Edit buttons
            for child in list_node.children:
                assert len(child.buttons) > 0, f"Leaf '{child.label}' has no edit button"

    async def test_list_of_dicts_uses_name_or_id_heading(self, tmp_path):
        """Dict items in a list use 'name' or 'id' for the branch label."""
        from ui.sidebar.panels.config_panel import ConfigPanel
        cfg = _make_config(
            {"connections": [
                {"id": "abc1", "name": "My DB", "provider_type": "sqlite"},
                {"id": "def2", "name": "Other DB", "provider_type": "sqlite"},
            ]},
            tmp_path,
        )

        class TestApp(App):
            CSS = "ConfigPanel { width: 40; height: 100%; }"

            def compose(self):
                self.panel = ConfigPanel()
                self.panel.set_config(cfg)
                yield self.panel

        async with TestApp().run_test() as pilot:
            await pilot.pause()

            panel = pilot.app.panel
            tree = panel.query_one(Tree)
            tree.expand_all()
            await pilot.pause()

            # Top-level list node
            list_node = tree.root.children[0]
            assert "connections" in list_node.label
            assert "[2]" in list_node.label

            # Dict items should use 'name' as heading
            child_labels = [c.label for c in list_node.children]
            assert any("[0]" in l and "My DB" in l for l in child_labels)
            assert any("[1]" in l and "Other DB" in l for l in child_labels)

    async def test_list_of_dicts_expands_nested_fields(self, tmp_path):
        """Dict items inside a list are fully expandable."""
        from ui.sidebar.panels.config_panel import ConfigPanel
        cfg = _make_config(
            {"servers": [{"host": "db.local", "port": 5432}]},
            tmp_path,
        )

        class TestApp(App):
            CSS = "ConfigPanel { width: 40; height: 100%; }"

            def compose(self):
                self.panel = ConfigPanel()
                self.panel.set_config(cfg)
                yield self.panel

        async with TestApp().run_test() as pilot:
            await pilot.pause()

            panel = pilot.app.panel
            tree = panel.query_one(Tree)
            tree.expand_all()
            await pilot.pause()

            # Drill down: root → servers → [0] → host / port
            servers_node = tree.root.children[0]
            item_node = servers_node.children[0]
            field_labels = [c.label for c in item_node.children]
            assert any("host" in l and "db.local" in l for l in field_labels)
            assert any("port" in l and "5432" in l for l in field_labels)

    async def test_empty_list_shows_zero_count(self, tmp_path):
        """An empty list renders as a branch with [0]."""
        from ui.sidebar.panels.config_panel import ConfigPanel
        cfg = _make_config({"connections": []}, tmp_path)

        class TestApp(App):
            CSS = "ConfigPanel { width: 40; height: 100%; }"

            def compose(self):
                self.panel = ConfigPanel()
                self.panel.set_config(cfg)
                yield self.panel

        async with TestApp().run_test() as pilot:
            await pilot.pause()

            panel = pilot.app.panel
            tree = panel.query_one(Tree)
            tree.expand_all()
            await pilot.pause()

            list_node = tree.root.children[0]
            assert "connections" in list_node.label
            assert "[0]" in list_node.label
            assert len(list_node.children) == 0

    async def test_nested_dict_inside_list_inside_dict(self, tmp_path):
        """Deep nesting: dict → list → dict → dict."""
        from ui.sidebar.panels.config_panel import ConfigPanel
        cfg = _make_config(
            {"db": {"connections": [{"params": {"path": "/data/db.sqlite"}}]}},
            tmp_path,
        )

        class TestApp(App):
            CSS = "ConfigPanel { width: 40; height: 100%; }"

            def compose(self):
                self.panel = ConfigPanel()
                self.panel.set_config(cfg)
                yield self.panel

        async with TestApp().run_test() as pilot:
            await pilot.pause()

            panel = pilot.app.panel
            tree = panel.query_one(Tree)
            tree.expand_all()
            await pilot.pause()

            # Drill down: root → db → connections → [0] → params → path
            db_node = tree.root.children[0]
            conn_node = db_node.children[0]  # connections list
            item_node = conn_node.children[0]  # [0] dict
            params_node = item_node.children[0]  # params dict
            path_leaf = params_node.children[0]  # path: /data/db.sqlite
            assert "path" in path_leaf.label
            assert "/data/db.sqlite" in path_leaf.label

    async def test_dict_without_name_or_id_uses_item_index(self, tmp_path):
        """Dict items without 'name' or 'id' fall back to 'item N' label."""
        from ui.sidebar.panels.config_panel import ConfigPanel
        cfg = _make_config(
            {"items": [{"x": 1, "y": 2}]},
            tmp_path,
        )

        class TestApp(App):
            CSS = "ConfigPanel { width: 40; height: 100%; }"

            def compose(self):
                self.panel = ConfigPanel()
                self.panel.set_config(cfg)
                yield self.panel

        async with TestApp().run_test() as pilot:
            await pilot.pause()

            panel = pilot.app.panel
            tree = panel.query_one(Tree)
            tree.expand_all()
            await pilot.pause()

            # The dict item should use fallback label 'item 0'
            items_node = tree.root.children[0]
            item_label = items_node.children[0].label
            assert "item 0" in item_label
