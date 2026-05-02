"""Tests for the ChatPanel sidebar widget."""

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Label

from ui.tree.tree import Tree
from ui.tree.tree_row import TreeNode, TreeRow


# ---------------------------------------------------------------------------
# Test app
# ---------------------------------------------------------------------------


class ChatPanelTestApp(App):
    """Minimal app hosting a ChatPanel for testing."""

    CSS = """
    ChatPanel {
        width: 60;
        height: 100%;
    }
    ChatPanel Tree {
        height: 1fr;
    }
    """

    def compose(self) -> ComposeResult:
        from ui.sidebar.panels.chat_panel import ChatPanel
        self.panel = ChatPanel()
        yield self.panel


# ---------------------------------------------------------------------------
# ChatPanel
# ---------------------------------------------------------------------------


class TestChatPanel:
    async def test_has_input_and_tree(self):
        """ChatPanel renders an Input and a Tree."""
        async with ChatPanelTestApp().run_test() as pilot:
            panel = pilot.app.panel
            await pilot.pause()

            # Should have an input
            inputs = panel.query("Input")
            assert len(inputs) == 1

            # Should have a tree
            trees = panel.query(Tree)
            assert len(trees) == 1

    async def test_add_user_message(self):
        """add_message with role='user' adds a node to the tree."""
        async with ChatPanelTestApp().run_test() as pilot:
            panel = pilot.app.panel
            await pilot.pause()

            panel.add_message("user", "Hello, world!")
            await pilot.pause()

            tree = panel.query_one(Tree)
            rows = tree.query(TreeRow)
            user_rows = [r for r in rows if hasattr(r.node, 'label') and "Hello" in r.node.label]
            assert len(user_rows) == 1

    async def test_add_assistant_message(self):
        """add_message with role='assistant' adds a response node."""
        async with ChatPanelTestApp().run_test() as pilot:
            panel = pilot.app.panel
            await pilot.pause()

            panel.add_message("assistant", "Hi there!")
            await pilot.pause()

            tree = panel.query_one(Tree)
            rows = tree.query(TreeRow)
            assistant_rows = [r for r in rows if "Hi there" in r.node.label]
            assert len(assistant_rows) == 1

    async def test_add_thought(self):
        """add_thought creates a child node under the last assistant message."""
        async with ChatPanelTestApp().run_test() as pilot:
            panel = pilot.app.panel
            await pilot.pause()

            panel.add_message("assistant", "Response")
            panel.add_thought("Let me think about this...")
            await pilot.pause()

            tree = panel.query_one(Tree)
            tree.expand_all()
            await pilot.pause()

            rows = tree.query(TreeRow)
            thought_rows = [r for r in rows if "Let me think" in r.node.label]
            assert len(thought_rows) == 1

    async def test_add_tool_result(self):
        """add_tool_result creates a child node under the last assistant message."""
        async with ChatPanelTestApp().run_test() as pilot:
            panel = pilot.app.panel
            await pilot.pause()

            panel.add_message("assistant", "Response")
            panel.add_tool_result("get_weather", {"city": "London"}, "Sunny")
            await pilot.pause()

            tree = panel.query_one(Tree)
            tree.expand_all()
            await pilot.pause()

            rows = tree.query(TreeRow)
            tool_rows = [r for r in rows if "get_weather" in r.node.label]
            assert len(tool_rows) == 1

    async def test_message_tree_structure(self):
        """Full conversation produces correct tree structure."""
        async with ChatPanelTestApp().run_test() as pilot:
            panel = pilot.app.panel
            await pilot.pause()

            panel.add_message("user", "What is 2+2?")
            panel.add_message("assistant", "Let me calculate...")
            panel.add_thought("I should use the calculator tool")
            panel.add_tool_result("calculate", {"expr": "2+2"}, "4")
            panel.add_message("assistant", "The answer is 4.")

            tree = panel.query_one(Tree)
            tree.expand_all()
            await pilot.pause()

            rows = tree.query(TreeRow)
            labels = [r.node.label for r in rows]

            # User message should be present
            assert any("What is 2+2?" in l for l in labels)
            # Thinking should be present
            assert any("calculator" in l for l in labels) or any("I should use" in l for l in labels)
            # Final response should be present
            assert any("answer is 4" in l.lower() for l in labels)
