"""Tests for the ChatDisplay widget.

ChatDisplay wraps a Tree and provides a streaming API:
add_user_message, begin_assistant_turn, add_section, update_section,
finalize_turn.
"""

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Markdown

from skills.chat.chat_display import ChatDisplay
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
    async def test_creates_user_branch_in_tree(self):
        """add_user_message creates a branch node with a Markdown leaf."""
        async with ChatDisplayTestApp().run_test() as pilot:
            await pilot.pause()

            node_id = pilot.app._chat_display.add_user_message("Hello, world!")
            await _settle(pilot)

            tree = pilot.app._chat_display.query_one(Tree)
            node = tree._node_map.get(node_id)
            assert node is not None
            # It's now a branch with a Markdown child
            assert len(node.children) == 1
            leaf = node.children[0]
            assert isinstance(leaf.content, Markdown)

    async def test_user_branch_has_dual_labels(self):
        """User branch shows truncated label by default, short label when expanded."""
        async with ChatDisplayTestApp().run_test() as pilot:
            await pilot.pause()

            node_id = pilot.app._chat_display.add_user_message("Hello, world!")
            await _settle(pilot)

            tree = pilot.app._chat_display.query_one(Tree)
            node = tree._node_map[node_id]
            # Collapsed label contains the message preview
            assert "Hello" in node.label
            # Expanded label is just "User"
            assert node.label_expanded is not None
            assert "User" in node.label_expanded

    async def test_user_branch_has_role_data(self):
        """User message branch stores role='user' in data."""
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

    async def test_user_branch_auto_expanded(self):
        """User message branches are expanded by default."""
        async with ChatDisplayTestApp().run_test() as pilot:
            await pilot.pause()

            node_id = pilot.app._chat_display.add_user_message("Hello")
            await _settle(pilot)

            tree = pilot.app._chat_display.query_one(Tree)
            assert tree.is_expanded(node_id)


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

    async def test_starts_with_no_section_children(self):
        """Assistant branch starts with no section children (lazy creation)."""
        async with ChatDisplayTestApp().run_test() as pilot:
            await pilot.pause()

            asst_id = pilot.app._chat_display.begin_assistant_turn()
            await _settle(pilot)

            tree = pilot.app._chat_display.query_one(Tree)
            asst_node = tree._node_map[asst_id]
            assert len(asst_node.children) == 0

    async def test_multiple_turns_are_independent(self):
        """Multiple assistant turns create distinct branch nodes."""
        async with ChatDisplayTestApp().run_test() as pilot:
            await pilot.pause()

            id1 = pilot.app._chat_display.begin_assistant_turn()
            id2 = pilot.app._chat_display.begin_assistant_turn()
            await _settle(pilot)

            tree = pilot.app._chat_display.query_one(Tree)
            assert id1 != id2
            assert tree._node_map[id1] is not tree._node_map[id2]


# ---------------------------------------------------------------------------
# add_section
# ---------------------------------------------------------------------------


class TestAddSection:
    async def test_adds_thinking_section(self):
        """add_section('thinking') creates a thinking section branch."""
        async with ChatDisplayTestApp().run_test() as pilot:
            await pilot.pause()

            asst_id = pilot.app._chat_display.begin_assistant_turn()
            section_id = pilot.app._chat_display.add_section("thinking")
            await _settle(pilot)

            tree = pilot.app._chat_display.query_one(Tree)
            asst_node = tree._node_map[asst_id]
            assert len(asst_node.children) == 1
            assert asst_node.children[0].data["section"] == "thinking"

    async def test_adds_tools_section(self):
        """add_section('tools') creates a tools section branch."""
        async with ChatDisplayTestApp().run_test() as pilot:
            await pilot.pause()

            asst_id = pilot.app._chat_display.begin_assistant_turn()
            section_id = pilot.app._chat_display.add_section("tools")
            await _settle(pilot)

            tree = pilot.app._chat_display.query_one(Tree)
            asst_node = tree._node_map[asst_id]
            assert len(asst_node.children) == 1
            assert asst_node.children[0].data["section"] == "tools"

    async def test_adds_response_section(self):
        """add_section('response') creates a response section branch."""
        async with ChatDisplayTestApp().run_test() as pilot:
            await pilot.pause()

            asst_id = pilot.app._chat_display.begin_assistant_turn()
            section_id = pilot.app._chat_display.add_section("response")
            await _settle(pilot)

            tree = pilot.app._chat_display.query_one(Tree)
            asst_node = tree._node_map[asst_id]
            assert len(asst_node.children) == 1
            assert asst_node.children[0].data["section"] == "response"

    async def test_returns_unique_section_ids(self):
        """Each add_section call returns a unique section ID."""
        async with ChatDisplayTestApp().run_test() as pilot:
            await pilot.pause()

            pilot.app._chat_display.begin_assistant_turn()
            id1 = pilot.app._chat_display.add_section("thinking")
            id2 = pilot.app._chat_display.add_section("tools")
            id3 = pilot.app._chat_display.add_section("response")
            assert id1 != id2 != id3

    async def test_section_has_markdown_leaf(self):
        """Each section branch has one leaf child holding a Markdown widget."""
        async with ChatDisplayTestApp().run_test() as pilot:
            await pilot.pause()

            pilot.app._chat_display.begin_assistant_turn()
            section_id = pilot.app._chat_display.add_section("thinking")
            await _settle(pilot)

            tree = pilot.app._chat_display.query_one(Tree)
            section_branch = tree._node_map[section_id]
            assert len(section_branch.children) == 1
            leaf = section_branch.children[0]
            assert isinstance(leaf.content, Markdown)

    async def test_multiple_sections_of_same_type(self):
        """Multiple sections of the same type can be added sequentially."""
        async with ChatDisplayTestApp().run_test() as pilot:
            await pilot.pause()

            asst_id = pilot.app._chat_display.begin_assistant_turn()
            s1 = pilot.app._chat_display.add_section("thinking")
            s2 = pilot.app._chat_display.add_section("tools")
            s3 = pilot.app._chat_display.add_section("thinking")
            await _settle(pilot)

            tree = pilot.app._chat_display.query_one(Tree)
            asst_node = tree._node_map[asst_id]
            assert len(asst_node.children) == 3
            # First and third are thinking, second is tools.
            assert asst_node.children[0].data["section"] == "thinking"
            assert asst_node.children[1].data["section"] == "tools"
            assert asst_node.children[2].data["section"] == "thinking"

    async def test_add_section_invalid_type_raises(self):
        """add_section with an unknown type raises ValueError."""
        async with ChatDisplayTestApp().run_test() as pilot:
            await pilot.pause()

            pilot.app._chat_display.begin_assistant_turn()
            with pytest.raises(ValueError, match="Unknown section type"):
                pilot.app._chat_display.add_section("nope")

    async def test_add_section_without_turn_raises(self):
        """add_section before begin_assistant_turn raises RuntimeError."""
        async with ChatDisplayTestApp().run_test() as pilot:
            await pilot.pause()

            with pytest.raises(RuntimeError, match="No active assistant turn"):
                pilot.app._chat_display.add_section("thinking")


# ---------------------------------------------------------------------------
# update_section
# ---------------------------------------------------------------------------


class TestUpdateSection:
    async def test_update_thinking(self):
        """update_section updates the thinking section's Markdown."""
        async with ChatDisplayTestApp().run_test() as pilot:
            await pilot.pause()

            pilot.app._chat_display.begin_assistant_turn()
            section_id = pilot.app._chat_display.add_section("thinking")
            await _settle(pilot)

            await pilot.app._chat_display.update_section(section_id, "I need to think...")
            await _settle(pilot)

            tree = pilot.app._chat_display.query_one(Tree)
            section_branch = tree._node_map[section_id]
            md = section_branch.children[0].content
            assert "I need to think..." in (md._markdown or "")

    async def test_update_tools(self):
        """update_section updates the tools section's Markdown."""
        async with ChatDisplayTestApp().run_test() as pilot:
            await pilot.pause()

            pilot.app._chat_display.begin_assistant_turn()
            section_id = pilot.app._chat_display.add_section("tools")
            await _settle(pilot)

            await pilot.app._chat_display.update_section(
                section_id, "🔧 `read_file(path='x.txt')`"
            )
            await _settle(pilot)

            tree = pilot.app._chat_display.query_one(Tree)
            section_branch = tree._node_map[section_id]
            md = section_branch.children[0].content
            assert "read_file" in (md._markdown or "")

    async def test_update_response(self):
        """update_section updates the response section's Markdown."""
        async with ChatDisplayTestApp().run_test() as pilot:
            await pilot.pause()

            pilot.app._chat_display.begin_assistant_turn()
            section_id = pilot.app._chat_display.add_section("response")
            await _settle(pilot)

            await pilot.app._chat_display.update_section(
                section_id, "The answer is 42."
            )
            await _settle(pilot)

            tree = pilot.app._chat_display.query_one(Tree)
            section_branch = tree._node_map[section_id]
            md = section_branch.children[0].content
            assert "The answer is 42." in (md._markdown or "")

    async def test_update_replaces_content(self):
        """Multiple update_section calls replace content (accumulation happens in the caller)."""
        async with ChatDisplayTestApp().run_test() as pilot:
            await pilot.pause()

            pilot.app._chat_display.begin_assistant_turn()
            section_id = pilot.app._chat_display.add_section("response")
            await _settle(pilot)

            await pilot.app._chat_display.update_section(section_id, "Hello")
            await pilot.app._chat_display.update_section(section_id, " world!")
            await _settle(pilot)

            md = pilot.app._chat_display._section_md.get(section_id)
            assert md is not None
            # Last update wins — display replaces, caller accumulates.
            assert " world!" in (md._markdown or "")

    async def test_update_unknown_section_id_no_ops(self):
        """update_section with an unknown section ID does nothing."""
        async with ChatDisplayTestApp().run_test() as pilot:
            await pilot.pause()

            pilot.app._chat_display.begin_assistant_turn()
            # Should not raise.
            await pilot.app._chat_display.update_section("nonexistent-id", "text")


# ---------------------------------------------------------------------------
# finalize_turn
# ---------------------------------------------------------------------------


class TestFinalizeTurn:
    async def test_removes_empty_section_children(self):
        """Sections that never received content are removed from the tree."""
        async with ChatDisplayTestApp().run_test() as pilot:
            await pilot.pause()

            asst_id = pilot.app._chat_display.begin_assistant_turn()
            # Add sections: only response gets content.
            s_think = pilot.app._chat_display.add_section("thinking")
            s_resp = pilot.app._chat_display.add_section("response")
            await _settle(pilot)

            await pilot.app._chat_display.update_section(s_resp, "Hello!")
            pilot.app._chat_display.finalize_turn()
            await _settle(pilot)

            tree = pilot.app._chat_display.query_one(Tree)
            asst_node = tree._node_map[asst_id]
            sections = {c.data["section"] for c in asst_node.children}
            assert sections == {"response"}
            assert "thinking" not in sections

    async def test_keeps_all_when_all_have_content(self):
        """When all sections have content, none are removed."""
        async with ChatDisplayTestApp().run_test() as pilot:
            await pilot.pause()

            asst_id = pilot.app._chat_display.begin_assistant_turn()
            s1 = pilot.app._chat_display.add_section("thinking")
            s2 = pilot.app._chat_display.add_section("tools")
            s3 = pilot.app._chat_display.add_section("response")
            await _settle(pilot)

            await pilot.app._chat_display.update_section(s1, "Hmm")
            await pilot.app._chat_display.update_section(s2, "🔧 tool()")
            await pilot.app._chat_display.update_section(s3, "Done.")
            pilot.app._chat_display.finalize_turn()
            await _settle(pilot)

            tree = pilot.app._chat_display.query_one(Tree)
            asst_node = tree._node_map[asst_id]
            sections = {c.data["section"] for c in asst_node.children}
            assert sections == {"thinking", "tools", "response"}

    async def test_handles_no_sections(self):
        """When no sections were added, the assistant branch stays empty."""
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
        """finalize_turn clears _section_md and _active_asst_id."""
        async with ChatDisplayTestApp().run_test() as pilot:
            await pilot.pause()

            pilot.app._chat_display.begin_assistant_turn()
            s = pilot.app._chat_display.add_section("response")
            await pilot.app._chat_display.update_section(s, "OK")
            pilot.app._chat_display.finalize_turn()

            assert pilot.app._chat_display._section_md == {}
            assert pilot.app._chat_display._active_asst_id is None


# ---------------------------------------------------------------------------
# Sequential section layout
# ---------------------------------------------------------------------------


class TestSequentialSections:
    async def test_thinking_tools_response_sequence(self):
        """A typical flow: thinking → tools → response."""
        async with ChatDisplayTestApp().run_test() as pilot:
            await pilot.pause()

            asst_id = pilot.app._chat_display.begin_assistant_turn()
            s1 = pilot.app._chat_display.add_section("thinking")
            s2 = pilot.app._chat_display.add_section("tools")
            s3 = pilot.app._chat_display.add_section("response")
            await _settle(pilot)

            tree = pilot.app._chat_display.query_one(Tree)
            asst_node = tree._node_map[asst_id]
            assert len(asst_node.children) == 3
            assert asst_node.children[0].data["section"] == "thinking"
            assert asst_node.children[1].data["section"] == "tools"
            assert asst_node.children[2].data["section"] == "response"

    async def test_thinking_tools_thinking_response_sequence(self):
        """Multi-round: thinking → tools → more thinking → response."""
        async with ChatDisplayTestApp().run_test() as pilot:
            await pilot.pause()

            asst_id = pilot.app._chat_display.begin_assistant_turn()
            s1 = pilot.app._chat_display.add_section("thinking")
            s2 = pilot.app._chat_display.add_section("tools")
            s3 = pilot.app._chat_display.add_section("thinking")
            s4 = pilot.app._chat_display.add_section("response")
            await _settle(pilot)

            tree = pilot.app._chat_display.query_one(Tree)
            asst_node = tree._node_map[asst_id]
            assert len(asst_node.children) == 4
            section_types = [c.data["section"] for c in asst_node.children]
            assert section_types == ["thinking", "tools", "thinking", "response"]

            # Each section has its own Markdown widget.
            for child in asst_node.children:
                assert len(child.children) == 1
                assert isinstance(child.children[0].content, Markdown)


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
            pilot.app._chat_display.begin_assistant_turn()
            s1 = pilot.app._chat_display.add_section("thinking")
            s2 = pilot.app._chat_display.add_section("response")
            await pilot.app._chat_display.update_section(s1, "Let me calculate")
            await pilot.app._chat_display.update_section(s2, "The answer is 4.")
            pilot.app._chat_display.finalize_turn()

            # Turn 2: tools + response
            pilot.app._chat_display.add_user_message("Read file")
            pilot.app._chat_display.begin_assistant_turn()
            s3 = pilot.app._chat_display.add_section("tools")
            s4 = pilot.app._chat_display.add_section("response")
            await pilot.app._chat_display.update_section(s3, "🔧 `read_file()`")
            await pilot.app._chat_display.update_section(s4, "Done.")
            pilot.app._chat_display.finalize_turn()

            await _settle(pilot)

            tree = pilot.app._chat_display.query_one(Tree)
            root = tree._node_map["chat-display-root"]
            assert len(root.children) == 4  # user1, asst1, user2, asst2

            # User branches each have a Markdown leaf child.
            u1 = root.children[0]
            assert u1.data["role"] == "user"
            assert len(u1.children) == 1
            assert isinstance(u1.children[0].content, Markdown)

            u2 = root.children[2]
            assert u2.data["role"] == "user"
            assert len(u2.children) == 1
            assert isinstance(u2.children[0].content, Markdown)

            # Turn 1 assistant sections
            a1 = root.children[1]
            a1_sections = {c.data["section"] for c in a1.children}
            assert a1_sections == {"thinking", "response"}

            # Turn 2 assistant sections
            a2 = root.children[3]
            a2_sections = {c.data["section"] for c in a2.children}
            assert a2_sections == {"tools", "response"}