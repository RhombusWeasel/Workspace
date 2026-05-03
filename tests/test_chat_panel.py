"""Tests for the ChatPanel sidebar widget.

Covers the simplified chat panel where each assistant response is a leaf
node with a :class:`Markdown` content widget for streaming.  Thoughts and
tool calls are folded into the markdown text instead of creating separate
tree nodes.
"""

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Input, Label, Markdown, Static

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

    async def test_add_assistant_creates_markdown_leaf(self):
        """add_message with role='assistant' creates a leaf node with a
        Markdown content widget."""
        async with ChatPanelTestApp().run_test() as pilot:
            panel = pilot.app.panel
            await pilot.pause()

            resp_id = panel.add_message("assistant", "Hi there!")
            await _settle(pilot)

            tree = panel.query_one(Tree)

            # The response node exists and has no children (it IS the leaf)
            assert resp_id in tree._node_map
            resp_node = tree._node_map[resp_id]
            assert len(resp_node.children) == 0

            # The response node's content is a Markdown widget
            assert resp_node.content is not None
            assert isinstance(resp_node.content, Markdown)

            # Markdown widget is rendered in the tree
            md_widgets = tree.query(Markdown)
            assert len(md_widgets) == 1

    async def test_add_thought(self):
        """add_thought updates the markdown widget with thinking text."""
        async with ChatPanelTestApp().run_test() as pilot:
            panel = pilot.app.panel
            await pilot.pause()

            panel.add_message("user", "What is 2+2?")
            panel.add_message("assistant", "Let me think...")
            await _settle(pilot)

            panel.add_thought("I should calculate this carefully")
            await _settle(pilot)

            tree = panel.query_one(Tree)
            # Should have only 4 rows: root, user, response (no separate thought row)
            rows = tree.query(TreeRow)
            assert len(rows) == 3  # root + user + response

            # Markdown should contain the thinking text
            md = tree.query_one(Markdown)
            assert "I should calculate" in (md._markdown or "")

    async def test_add_tool_result(self):
        """add_tool_result updates the markdown widget with tool info."""
        async with ChatPanelTestApp().run_test() as pilot:
            panel = pilot.app.panel
            await pilot.pause()

            panel.add_message("user", "Weather?")
            panel.add_message("assistant", "Checking...")
            await _settle(pilot)

            panel.add_tool_result("get_weather", {"city": "London"}, "Sunny, 22°C")
            await _settle(pilot)

            tree = panel.query_one(Tree)
            rows = tree.query(TreeRow)
            assert len(rows) == 3  # root + user + response

            # Markdown should contain the tool info
            md = tree.query_one(Markdown)
            assert "get_weather" in (md._markdown or "")

    async def test_conversation_tree_structure(self):
        """Full conversation produces correct tree structure.

        Expected:
        root
        ├── 👤 User: "What is 2+2?"
        ├── 💭 Response (leaf with Markdown widget)
        ├── 👤 User: "Thanks!"
        ├── 💭 Response (leaf with Markdown widget)
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

            # Verify root children: user, response, user, response
            root_node = tree._node_map["chat-root"]
            assert len(root_node.children) == 4  # 2 users + 2 responses

            # First child is user (leaf, no content widget)
            assert root_node.children[0].data.get("role") == "user"
            assert "What is 2+2?" in root_node.children[0].label
            assert root_node.children[0].content is None

            # Second child is response (leaf with markdown content)
            assert root_node.children[1].data.get("role") == "assistant"
            assert root_node.children[1].content is not None
            assert isinstance(root_node.children[1].content, Markdown)

            # Third child is user
            assert root_node.children[2].data.get("role") == "user"
            assert "Thanks!" in root_node.children[2].label

            # Fourth child is response
            assert root_node.children[3].data.get("role") == "assistant"
            assert isinstance(root_node.children[3].content, Markdown)

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

            md = markdowns[0]
            assert md._markdown is not None
            assert "Hello there" in md._markdown

    async def test_last_assistant_id_tracks_current_response(self):
        """last_assistant_id tracks the most recent assistant response."""
        async with ChatPanelTestApp().run_test() as pilot:
            panel = pilot.app.panel
            await pilot.pause()

            panel.add_message("user", "Q1")
            resp_id = panel.add_message("assistant", "A1")
            assert panel.last_assistant_id == resp_id

            # User doesn't change it
            panel.add_message("user", "Q2")
            assert panel.last_assistant_id == resp_id

            # New assistant updates it
            resp_id2 = panel.add_message("assistant", "A2")
            assert panel.last_assistant_id == resp_id2


class TestChatPanelStreaming:
    async def test_full_streaming_flow(self):
        """Simulates the full streaming cycle: user submits → agent yields
        chunks → markdown updates incrementally."""
        chunks = [
            type('C', (), {'thinking': 'Let me', 'content': '', 'tool_calls': None})(),
            type('C', (), {'thinking': ' think', 'content': '', 'tool_calls': None})(),
            type('C', (), {'thinking': '', 'content': 'Hello', 'tool_calls': None})(),
            type('C', (), {'thinking': '', 'content': ' world', 'tool_calls': None})(),
            type('C', (), {'thinking': '', 'content': '!', 'tool_calls': None})(),
        ]

        class FakeAgent:
            def __init__(self, chunks):
                self._chunks = chunks
            async def stream_chat(self, history, user_text, tools=None):
                for chunk in self._chunks:
                    yield chunk

        async with ChatPanelTestApp().run_test() as pilot:
            panel = pilot.app.panel
            panel.set_agent(FakeAgent(chunks))
            await pilot.pause()

            # Submit via Input
            inp = panel.query_one(Input)
            inp.value = 'Hello?'
            inp.post_message(Input.Submitted(inp, 'Hello?'))
            await _settle(pilot, n=10)

            # Verify tree structure
            tree = panel.query_one(Tree)
            rows = tree.query(TreeRow)
            # Should have: root, user msg, response
            assert len(rows) == 3

            # Verify Markdown widget received the final accumulated text
            md = tree.query_one(Markdown)
            assert md._markdown is not None
            # Content should include 'Hello world!' (final accumulated content)
            # and thinking should be folded in as prefix
            assert 'Hello world!' in md._markdown
            assert 'Let me think' in md._markdown

    async def test_streaming_with_tool_calls(self):
        """Streaming with tool calls: intermediate content is replaced
        by tool info, then final content streams."""
        chunks = [
            type('C', (), {'thinking': '', 'content': 'Let me check', 'tool_calls': None})(),
            type('C', (), {
                'thinking': '', 'content': '',
                'tool_calls': [type('TC', (), {'name': 'get_weather', 'arguments': {'city': 'London'}})()]
            })(),
            type('C', (), {'thinking': '', 'content': 'The weather', 'tool_calls': None})(),
            type('C', (), {'thinking': '', 'content': ' is sunny', 'tool_calls': None})(),
        ]

        class FakeAgent:
            def __init__(self, chunks):
                self._chunks = chunks
            async def stream_chat(self, history, user_text, tools=None):
                for chunk in self._chunks:
                    yield chunk

        async with ChatPanelTestApp().run_test() as pilot:
            panel = pilot.app.panel
            panel.set_agent(FakeAgent(chunks))
            await pilot.pause()

            inp = panel.query_one(Input)
            inp.value = 'Weather?'
            inp.post_message(Input.Submitted(inp, 'Weather?'))
            await _settle(pilot, n=10)

            tree = panel.query_one(Tree)
            md = tree.query_one(Markdown)
            # Final content should include the tool info and response
            assert 'get_weather' in md._markdown
            assert 'The weather is sunny' in md._markdown
            # Intermediate 'Let me check' should be replaced by tool calls
            # (not present in final markdown)
