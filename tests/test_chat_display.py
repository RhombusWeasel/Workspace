"""Tests for the ChatDisplay widget.

ChatDisplay wraps a Tree and provides a streaming API:
add_user_message, begin_assistant_turn, update_section, finalize_turn.
"""

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Markdown

from ui.chat.chat_display import ChatDisplay
from ui.tree.tree import Tree
from ui.tree.tree_row import TreeNode, TreeRow


# ---------------------------------------------------------------------------
# Test app
# ---------------------------------------------------------------------------


class ChatDisplayTestApp(App):
    """Minimal app hosting a ChatDisplay."""

    CSS = """
    ChatDisplay {
        width: 60;
        height: 100%;
    }
    ChatDisplay Tree {
        height: 1fr;
    }
    """

    def compose(self) -> ComposeResult:
        self._chat_display = ChatDisplay()
        yield self._chat_display


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _settle(pilot, n: int = 2) -> None:
    for _ in range(n):
        await pilot.pause()


# ---------------------------------------------------------------------------
# ChatDisplay — basic structure
# ---------------------------------------------------------------------------


class TestChatDisplay:
    async def test_contains_tree_widget(self):
        """ChatDisplay composes a Tree widget."""
        async with ChatDisplayTestApp().run_test() as pilot:
            await pilot.pause()
            trees = pilot.app._chat_display.query(Tree)
            assert len(trees) == 1

    async def test_tree_root_is_conversation(self):
        """The Tree root node is labelled 'Conversation'."""
        async with ChatDisplayTestApp().run_test() as pilot:
            await pilot.pause()
            tree = pilot.app._chat_display.query_one(Tree)
            root = tree._node_map["chat-display-root"]
            assert root.label == "Conversation"


# ---------------------------------------------------------------------------
# add_user_message
# ---------------------------------------------------------------------------


class TestAddUserMessage:
    async def test_creates_user_leaf_in_tree(self):
        """add_user_message creates a leaf node in the tree root."""
        async with ChatDisplayTestApp().run_test() as pilot:
            await pilot.pause()

            node_id = pilot.app._chat_display.add_user_message("Hello, world!")
            await _settle(pilot)

            tree = pilot.app._chat_display.query_one(Tree)
            node = tree._node_map.get(node_id)
            assert node is not None
            assert "Hello" in node.label

    async def test_user_node_has_role_data(self):
        """User message node stores role='user' in data."""
        async with ChatDisplayTestApp().run_test() as pilot:
            await pilot.pause()

            node_id = pilot.app._chat_display.add_user_message("Hi")
            await _settle(pilot)

            tree = pilot.app._chat_display.query_one(Tree)
            node = tree._node_map[node_id]
            assert node.data["role"] == "user"

    async def test_returns_unique_ids(self):
        """Each call returns a unique node ID."""
        async with ChatDisplayTestApp().run_test() as pilot:
            await pilot.pause()

            id1 = pilot.app._chat_display.add_user_message("One")
            id2 = pilot.app._chat_display.add_user_message("Two")
            assert id1 != id2

    async def test_adds_to_root_children(self):
        """User messages are appended to the root node's children."""
        async with ChatDisplayTestApp().run_test() as pilot:
            await pilot.pause()

            pilot.app._chat_display.add_user_message("Msg A")
            pilot.app._chat_display.add_user_message("Msg B")
            await _settle(pilot)

            tree = pilot.app._chat_display.query_one(Tree)
            root = tree._node_map["chat-display-root"]
            assert len(root.children) == 2


# ---------------------------------------------------------------------------
# begin_assistant_turn
# ---------------------------------------------------------------------------


class TestBeginAssistantTurn:
    async def test_creates_assistant_branch_node(self):
        """begin_assistant_turn creates a branch node."""
        async with ChatDisplayTestApp().run_test() as pilot:
            await pilot.pause()

            asst_id = pilot.app._chat_display.begin_assistant_turn()
            await _settle(pilot)

            tree = pilot.app._chat_display.query_one(Tree)
            node = tree._node_map.get(asst_id)
            assert node is not None
            assert node.data["role"] == "assistant"
            assert node.data["type"] == "branch"

    async def test_has_three_section_children(self):
        """Assistant branch has three children: thinking, tools, response."""
        async with ChatDisplayTestApp().run_test() as pilot:
            await pilot.pause()

            asst_id = pilot.app._chat_display.begin_assistant_turn()
            await _settle(pilot)

            tree = pilot.app._chat_display.query_one(Tree)
            asst_node = tree._node_map[asst_id]
            assert len(asst_node.children) == 3

            sections = {c.data.get("section") for c in asst_node.children}
            assert sections == {"thinking", "tools", "response"}

    async def test_each_section_has_markdown_leaf(self):
        """Each section branch has one leaf child holding a Markdown widget."""
        async with ChatDisplayTestApp().run_test() as pilot:
            await pilot.pause()

            asst_id = pilot.app._chat_display.begin_assistant_turn()
            await _settle(pilot)

            tree = pilot.app._chat_display.query_one(Tree)
            asst_node = tree._node_map[asst_id]

            for section_branch in asst_node.children:
                assert len(section_branch.children) == 1
                leaf = section_branch.children[0]
                assert isinstance(leaf.content, Markdown)

    async def test_multiple_turns_are_independent(self):
        """Multiple assistant turns create distinct branch nodes and Markdowns."""
        async with ChatDisplayTestApp().run_test() as pilot:
            await pilot.pause()

            id1 = pilot.app._chat_display.begin_assistant_turn()
            id2 = pilot.app._chat_display.begin_assistant_turn()
            await _settle(pilot)

            tree = pilot.app._chat_display.query_one(Tree)
            node1 = tree._node_map[id1]
            node2 = tree._node_map[id2]

            # Children should point to different Markdown instances.
            leaf1 = node1.children[2].children[0].content
            leaf2 = node2.children[2].children[0].content
            assert leaf1 is not leaf2


# ---------------------------------------------------------------------------
# update_section
# ---------------------------------------------------------------------------


class TestUpdateSection:
    async def test_update_thinking(self):
        """update_section('thinking', ...) updates the thinking Markdown."""
        async with ChatDisplayTestApp().run_test() as pilot:
            await pilot.pause()

            asst_id = pilot.app._chat_display.begin_assistant_turn()
            await _settle(pilot)

            await pilot.app._chat_display.update_section("thinking", "I need to think...")
            await _settle(pilot)

            tree = pilot.app._chat_display.query_one(Tree)
            asst_node = tree._node_map[asst_id]
            thought_branch = asst_node.children[0]
            md = thought_branch.children[0].content
            assert "I need to think..." in (md._markdown or "")

    async def test_update_tools(self):
        """update_section('tools', ...) updates the tools Markdown."""
        async with ChatDisplayTestApp().run_test() as pilot:
            await pilot.pause()

            asst_id = pilot.app._chat_display.begin_assistant_turn()
            await _settle(pilot)

            await pilot.app._chat_display.update_section(
                "tools", "🔧 `read_file(path='x.txt')`"
            )
            await _settle(pilot)

            tree = pilot.app._chat_display.query_one(Tree)
            asst_node = tree._node_map[asst_id]
            tools_branch = asst_node.children[1]
            md = tools_branch.children[0].content
            assert "read_file" in (md._markdown or "")

    async def test_update_response(self):
        """update_section('response', ...) updates the response Markdown."""
        async with ChatDisplayTestApp().run_test() as pilot:
            await pilot.pause()

            asst_id = pilot.app._chat_display.begin_assistant_turn()
            await _settle(pilot)

            await pilot.app._chat_display.update_section("response", "The answer is 42.")
            await _settle(pilot)

            tree = pilot.app._chat_display.query_one(Tree)
            asst_node = tree._node_map[asst_id]
            resp_branch = asst_node.children[2]
            md = resp_branch.children[0].content
            assert "The answer is 42." in (md._markdown or "")

    async def test_update_replaces_content(self):
        """Multiple update_section calls replace content (accumulation happens in the caller)."""
        async with ChatDisplayTestApp().run_test() as pilot:
            await pilot.pause()

            pilot.app._chat_display.begin_assistant_turn()
            await _settle(pilot)

            await pilot.app._chat_display.update_section("response", "Hello")
            await pilot.app._chat_display.update_section("response", " world!")
            await _settle(pilot)

            section_md = pilot.app._chat_display._section_md.get("response")
            assert section_md is not None
            # Last update wins — display replaces, caller accumulates.
            assert " world!" in (section_md._markdown or "")

    async def test_update_marks_section_active(self):
        """update_section adds the section to _active_sections tracking."""
        async with ChatDisplayTestApp().run_test() as pilot:
            await pilot.pause()

            pilot.app._chat_display.begin_assistant_turn()

            await pilot.app._chat_display.update_section("thinking", "Hmm")
            assert "thinking" in pilot.app._chat_display._active_sections

            await pilot.app._chat_display.update_section("response", "OK")
            assert "response" in pilot.app._chat_display._active_sections

            assert "tools" not in pilot.app._chat_display._active_sections

    async def test_update_invalid_section_raises(self):
        """update_section with unknown section name raises ValueError."""
        async with ChatDisplayTestApp().run_test() as pilot:
            await pilot.pause()

            pilot.app._chat_display.begin_assistant_turn()

            with pytest.raises(ValueError, match="Unknown section"):
                await pilot.app._chat_display.update_section("nope", "text")


# ---------------------------------------------------------------------------
# finalize_turn
# ---------------------------------------------------------------------------


class TestFinalizeTurn:
    async def test_removes_empty_section_children(self):
        """Sections that never received content are removed from the tree."""
        async with ChatDisplayTestApp().run_test() as pilot:
            await pilot.pause()

            asst_id = pilot.app._chat_display.begin_assistant_turn()
            await _settle(pilot)

            # Only response gets content.
            await pilot.app._chat_display.update_section("response", "Hello!")
            pilot.app._chat_display.finalize_turn()
            await _settle(pilot)

            tree = pilot.app._chat_display.query_one(Tree)
            asst_node = tree._node_map[asst_id]
            sections = {c.data["section"] for c in asst_node.children}
            assert sections == {"response"}
            assert "thinking" not in sections
            assert "tools" not in sections

    async def test_keeps_all_when_all_active(self):
        """When all three sections have content, none are removed."""
        async with ChatDisplayTestApp().run_test() as pilot:
            await pilot.pause()

            asst_id = pilot.app._chat_display.begin_assistant_turn()
            await _settle(pilot)

            await pilot.app._chat_display.update_section("thinking", "Hmm")
            await pilot.app._chat_display.update_section("tools", "🔧 tool()")
            await pilot.app._chat_display.update_section("response", "Done.")
            pilot.app._chat_display.finalize_turn()
            await _settle(pilot)

            tree = pilot.app._chat_display.query_one(Tree)
            asst_node = tree._node_map[asst_id]
            sections = {c.data["section"] for c in asst_node.children}
            assert sections == {"thinking", "tools", "response"}

    async def test_handles_no_active_sections(self):
        """When no sections received content, all children are removed."""
        async with ChatDisplayTestApp().run_test() as pilot:
            await pilot.pause()

            asst_id = pilot.app._chat_display.begin_assistant_turn()
            await _settle(pilot)

            pilot.app._chat_display.finalize_turn()
            await _settle(pilot)

            tree = pilot.app._chat_display.query_one(Tree)
            asst_node = tree._node_map[asst_id]
            assert len(asst_node.children) == 0

    async def test_resets_internal_state(self):
        """finalize_turn clears _section_md and _active_sections."""
        async with ChatDisplayTestApp().run_test() as pilot:
            await pilot.pause()

            pilot.app._chat_display.begin_assistant_turn()
            await pilot.app._chat_display.update_section("response", "OK")
            pilot.app._chat_display.finalize_turn()

            assert pilot.app._chat_display._section_md == {}
            assert pilot.app._chat_display._active_sections == set()


# ---------------------------------------------------------------------------
# Conversation tree structure
# ---------------------------------------------------------------------------


class TestConversationTree:
    async def test_multi_turn_structure(self):
        """Multiple turns produce the expected tree structure."""
        async with ChatDisplayTestApp().run_test() as pilot:
            await pilot.pause()

            # Turn 1: thinking + response
            pilot.app._chat_display.add_user_message("What is 2+2?")
            asst1 = pilot.app._chat_display.begin_assistant_turn()
            await pilot.app._chat_display.update_section("thinking", "Let me calculate")
            await pilot.app._chat_display.update_section("response", "The answer is 4.")
            pilot.app._chat_display.finalize_turn()

            # Turn 2: tools + response
            pilot.app._chat_display.add_user_message("Read file")
            asst2 = pilot.app._chat_display.begin_assistant_turn()
            await pilot.app._chat_display.update_section("tools", "🔧 `read_file()`")
            await pilot.app._chat_display.update_section("response", "Done.")
            pilot.app._chat_display.finalize_turn()

            await _settle(pilot)

            tree = pilot.app._chat_display.query_one(Tree)
            root = tree._node_map["chat-display-root"]
            assert len(root.children) == 4  # user1, asst1, user2, asst2

            # Turn 1 sections
            a1 = root.children[1]
            a1_sections = {c.data["section"] for c in a1.children}
            assert a1_sections == {"thinking", "response"}

            # Turn 2 sections
            a2 = root.children[3]
            a2_sections = {c.data["section"] for c in a2.children}
            assert a2_sections == {"tools", "response"}
