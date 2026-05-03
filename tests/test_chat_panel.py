"""Tests for the ChatPanel sidebar widget.

Covers the restructured tree where each assistant response is a **branch**
node (not a flat sibling), and response text uses a :class:`Markdown` widget
for streaming.
"""

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Label, Markdown, Static

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
# Helpers
# ---------------------------------------------------------------------------


async def _settle(pilot, n: int = 2) -> None:
    """Let async DOM removals / mounts settle."""
    for _ in range(n):
        await pilot.pause()


# ---------------------------------------------------------------------------
# ChatPanel
# ---------------------------------------------------------------------------


class TestChatPanel:
    async def test_has_input_and_tree(self):
        """ChatPanel renders an Input and a Tree."""
        async with ChatPanelTestApp().run_test() as pilot:
            panel = pilot.app.panel
            await pilot.pause()

            inputs = panel.query("Input")
            assert len(inputs) == 1

            trees = panel.query(Tree)
            assert len(trees) == 1

    async def test_add_user_message_creates_leaf(self):
        """add_message with role='user' adds a leaf node under root."""
        async with ChatPanelTestApp().run_test() as pilot:
            panel = pilot.app.panel
            await pilot.pause()

            panel.add_message("user", "Hello, world!")
            await _settle(pilot)

            tree = panel.query_one(Tree)
            rows = tree.query(TreeRow)
            user_rows = [r for r in rows if hasattr(r.node, 'label')
                         and "Hello" in r.node.label]
            assert len(user_rows) == 1

    async def test_add_assistant_creates_branch_node(self):
        """add_message with role='assistant' creates a branch node
        (has children with markdown widget)."""
        async with ChatPanelTestApp().run_test() as pilot:
            panel = pilot.app.panel
            await pilot.pause()

            resp_id = panel.add_message("assistant", "Hi there!")
            await _settle(pilot)

            tree = panel.query_one(Tree)

            # Verify the response node exists and has children
            assert resp_id in tree._node_map
            resp_node = tree._node_map[resp_id]
            assert len(resp_node.children) > 0

            # One of those children should be a markdown widget
            md_widgets = tree.query(Markdown)
            assert len(md_widgets) >= 1

    async def test_response_branch_contains_markdown(self):
        """An assistant response includes a Markdown widget child for
        streaming content."""
        async with ChatPanelTestApp().run_test() as pilot:
            panel = pilot.app.panel
            await pilot.pause()

            panel.add_message("user", "Hello")
            resp_id = panel.add_message("assistant", "Hi there!")
            await _settle(pilot)

            tree = panel.query_one(Tree)

            # Find the response node
            resp_node = tree._node_map[resp_id]

            # Should have a child with a Markdown widget
            content_children = [
                c for c in resp_node.children
                if c.content is not None and isinstance(c.content, Markdown)
            ]
            assert len(content_children) == 1

    async def test_add_thought(self):
        """add_thought creates a child node under the last response branch."""
        async with ChatPanelTestApp().run_test() as pilot:
            panel = pilot.app.panel
            await pilot.pause()

            panel.add_message("user", "What is 2+2?")
            panel.add_message("assistant", "Let me think...")
            panel.add_thought("I should calculate this carefully")
            await _settle(pilot)

            tree = panel.query_one(Tree)
            tree.expand_all()
            await _settle(pilot)

            rows = tree.query(TreeRow)
            thought_rows = [r for r in rows if "I should calculate" in r.node.label]
            assert len(thought_rows) == 1

    async def test_add_tool_result(self):
        """add_tool_result creates a child node under the last response branch."""
        async with ChatPanelTestApp().run_test() as pilot:
            panel = pilot.app.panel
            await pilot.pause()

            panel.add_message("user", "Weather?")
            panel.add_message("assistant", "Checking...")
            panel.add_tool_result("get_weather", {"city": "London"}, "Sunny, 22°C")
            await _settle(pilot)

            tree = panel.query_one(Tree)
            tree.expand_all()
            await _settle(pilot)

            rows = tree.query(TreeRow)
            tool_rows = [r for r in rows if "get_weather" in r.node.label]
            assert len(tool_rows) == 1

    async def test_conversation_tree_structure(self):
        """Full conversation produces correct branch-based tree structure.

        Expected:
        root
        ├── 👤 User: "What is 2+2?"
        ├── 💭 Response (branch)
        │   ├── 💡 Thinking: "using calculator"
        │   ├── 🔧 Tool: calculate → 4
        │   └── 📝 [Markdown widget]
        ├── 👤 User: "Thanks!"
        ├── 💭 Response (branch)
        │   └── 📝 [Markdown widget]
        """
        async with ChatPanelTestApp().run_test() as pilot:
            panel = pilot.app.panel
            await pilot.pause()

            # Turn 1
            panel.add_message("user", "What is 2+2?")
            panel.add_message("assistant", "Let me calculate...")
            panel.add_thought("I should use the calculator tool")
            panel.add_tool_result("calculate", {"expr": "2+2"}, "4")

            # Turn 2
            panel.add_message("user", "Thanks!")
            panel.add_message("assistant", "You're welcome!")

            await _settle(pilot)

            tree = panel.query_one(Tree)
            tree.expand_all()
            await _settle(pilot)

            # Verify root children: user leaf, response branch, user leaf, response branch
            root_node = tree._node_map["chat-root"]
            assert len(root_node.children) == 4  # 2 users + 2 responses

            # First child is user
            assert root_node.children[0].data.get("role") == "user"
            assert "What is 2+2?" in root_node.children[0].label

            # Second child is response branch
            assert root_node.children[1].data.get("role") == "assistant"
            assert len(root_node.children[1].children) >= 1

            # Third child is user
            assert root_node.children[2].data.get("role") == "user"
            assert "Thanks!" in root_node.children[2].label

            # Fourth child is response branch
            assert root_node.children[3].data.get("role") == "assistant"
            assert len(root_node.children[3].children) >= 1

    async def test_streaming_markdown_update(self):
        """update_response_text updates the Markdown widget's content."""
        async with ChatPanelTestApp().run_test() as pilot:
            panel = pilot.app.panel
            await pilot.pause()

            panel.add_message("user", "Hello")
            resp_id = panel.add_message("assistant", "…")
            await _settle(pilot)

            # Stream partial update
            await panel.update_response_text("Hello")
            await _settle(pilot)

            tree = panel.query_one(Tree)
            markdowns = tree.query(Markdown)
            assert len(markdowns) == 1

            # Stream more
            await panel.update_response_text("Hello there, how can I help?")
            await _settle(pilot)

            # Markdown widget should reflect the update
            md = markdowns[0]
            assert md._markdown is not None

    async def test_last_assistant_id_cleared_after_new_user(self):
        """After a new user message, last_assistant_id tracks correctly."""
        async with ChatPanelTestApp().run_test() as pilot:
            panel = pilot.app.panel
            await pilot.pause()

            panel.add_message("user", "Q1")
            resp_id = panel.add_message("assistant", "A1")
            assert panel.last_assistant_id == resp_id

            # New user message does NOT change last_assistant_id
            panel.add_message("user", "Q2")
            assert panel.last_assistant_id == resp_id  # unchanged by user

            # New assistant message updates it
            resp_id2 = panel.add_message("assistant", "A2")
            assert panel.last_assistant_id == resp_id2

    async def test_multiple_turns_independent_branches(self):
        """Each response is an independent branch — toggling one
        does not affect others."""
        async with ChatPanelTestApp().run_test() as pilot:
            panel = pilot.app.panel
            await pilot.pause()

            panel.add_message("user", "Q1")
            r1 = panel.add_message("assistant", "A1")
            panel.add_thought("thinking 1")

            panel.add_message("user", "Q2")
            r2 = panel.add_message("assistant", "A2")
            panel.add_thought("thinking 2")

            await _settle(pilot)

            tree = panel.query_one(Tree)

            # Both response branches should be independently expandable
            assert tree.is_expanded(r1)
            assert tree.is_expanded(r2)

            # Collapse r1 only
            tree.collapse_node(r1)
            await _settle(pilot)

            assert not tree.is_expanded(r1)
            assert tree.is_expanded(r2)
