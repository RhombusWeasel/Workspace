"""Tests for the ChatDisplay widget — clear, system messages, and section types.

Extends the existing test suite with coverage for the new methods.
"""

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Markdown

from ui.chat.chat_display import ChatDisplay
from ui.tree.tree import Tree
from ui.tree.tree_row import TreeNode


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
# System messages
# ---------------------------------------------------------------------------


class TestSystemMessage:
    async def test_add_system_message_creates_branch(self):
        """add_system_message creates a branch in the tree."""
        async with ChatDisplayTestApp().run_test() as pilot:
            await pilot.pause()

            node_id = pilot.app._chat_display.add_system_message("Chat cleared.")
            await _settle(pilot)

            tree = pilot.app._chat_display.query_one(Tree)
            node = tree._node_map.get(node_id)
            assert node is not None

    async def test_system_message_role_data(self):
        """System message branch stores role='system' in data."""
        async with ChatDisplayTestApp().run_test() as pilot:
            await pilot.pause()

            node_id = pilot.app._chat_display.add_system_message("Hello system")
            await _settle(pilot)

            tree = pilot.app._chat_display.query_one(Tree)
            node = tree._node_map[node_id]
            assert node.data["role"] == "system"

    async def test_system_message_has_markdown_leaf(self):
        """System message branch has a Markdown child with the text."""
        async with ChatDisplayTestApp().run_test() as pilot:
            await pilot.pause()

            node_id = pilot.app._chat_display.add_system_message("Done!")
            await _settle(pilot)

            tree = pilot.app._chat_display.query_one(Tree)
            node = tree._node_map[node_id]
            assert len(node.children) == 1
            md = node.children[0].content
            assert isinstance(md, Markdown)
            assert "Done!" in (md._markdown or "")

    async def test_system_message_auto_expanded(self):
        """System message branches are expanded by default."""
        async with ChatDisplayTestApp().run_test() as pilot:
            await pilot.pause()

            node_id = pilot.app._chat_display.add_system_message("Test")
            await _settle(pilot)

            tree = pilot.app._chat_display.query_one(Tree)
            assert tree.is_expanded(node_id)

    async def test_system_message_unique_ids(self):
        """Multiple system messages get unique IDs."""
        async with ChatDisplayTestApp().run_test() as pilot:
            await pilot.pause()

            id1 = pilot.app._chat_display.add_system_message("One")
            id2 = pilot.app._chat_display.add_system_message("Two")
            assert id1 != id2


# ---------------------------------------------------------------------------
# Clear
# ---------------------------------------------------------------------------


class TestClear:
    async def test_clear_removes_all_messages(self):
        """clear() removes all messages from the display."""
        async with ChatDisplayTestApp().run_test() as pilot:
            await pilot.pause()

            cd = pilot.app._chat_display
            cd.add_user_message("Hello!")
            cd.begin_assistant_turn()
            cd.add_section("response")
            cd.finalize_turn()
            await _settle(pilot)

            tree = cd.query_one(Tree)
            root = tree._node_map["chat-display-root"]
            assert len(root.children) > 0

            cd.clear()
            await _settle(pilot)

            root = tree._node_map["chat-display-root"]
            assert len(root.children) == 0

    async def test_clear_resets_counters(self):
        """clear() resets turn and section counters."""
        async with ChatDisplayTestApp().run_test() as pilot:
            await pilot.pause()

            cd = pilot.app._chat_display
            cd.add_user_message("Hi")
            cd.begin_assistant_turn()
            cd.add_section("response")
            cd.finalize_turn()
            await _settle(pilot)

            cd.clear()
            assert cd._turn_count == 0
            assert cd._section_count == 0

    async def test_clear_resets_active_turn_state(self):
        """clear() clears active assistant turn and section map."""
        async with ChatDisplayTestApp().run_test() as pilot:
            await pilot.pause()

            cd = pilot.app._chat_display
            cd.begin_assistant_turn()
            cd.add_section("response")
            await _settle(pilot)

            cd.clear()
            assert cd._active_asst_id is None
            assert cd._section_md == {}

    async def test_clear_then_add_messages(self):
        """After clear(), new messages can be added normally."""
        async with ChatDisplayTestApp().run_test() as pilot:
            await pilot.pause()

            cd = pilot.app._chat_display
            cd.add_user_message("First round")
            await _settle(pilot)

            cd.clear()
            await _settle(pilot)

            # Should be able to add messages again
            cd.add_user_message("Second round")
            cd.add_system_message("System note")
            await _settle(pilot)

            tree = cd.query_one(Tree)
            root = tree._node_map["chat-display-root"]
            assert len(root.children) == 2

    async def test_add_section_system_type_is_valid(self):
        """'system' is a valid section type (used for command system messages)."""
        async with ChatDisplayTestApp().run_test() as pilot:
            await pilot.pause()

            cd = pilot.app._chat_display
            cd.begin_assistant_turn()
            # Should not raise
            section_id = cd.add_section("system")
            assert section_id.startswith("system-sec")