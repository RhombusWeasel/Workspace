"""Tests for the conversation rebuild optimization in ChatDisplay.

Verifies:
1. Batch mode suppresses intermediate rebuilds and scrolls.
2. Node lookup map provides O(1) lookups.
3. Single-pass finalization during batch rebuild.
4. Rebuild from sections produces correct output with batch mode.
5. Batch mode correctly restores expand state after end_batch().
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from textual.app import App, ComposeResult
from textual.containers import Container

from core.paths import collect_tcss
from skills.chat.chat_display import ChatDisplay
from ui.tree.tree import Tree
from ui.tree.tree_row import TreeNode


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _ChatApp(App):
    """Minimal app that mounts a ChatDisplay for testing."""
    CSS_PATH = collect_tcss(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.chat_display = ChatDisplay()

    def compose(self) -> ComposeResult:
        yield Container(self.chat_display)


# ---------------------------------------------------------------------------
# A: Batch mode — suppresses _rebuild() and _schedule_scroll()
# ---------------------------------------------------------------------------


class TestBatchMode:
    """Tests for ChatDisplay batch mode optimization."""

    @pytest.mark.asyncio
    async def test_batch_mode_suppresses_rebuild(self):
        """In batch mode, _rebuild() should not call tree.rebuild()."""
        app = _ChatApp()
        async with app.run_test(size=(80, 40)):
            display = app.chat_display
            tree = display.query_one(Tree)

            # Patch tree.rebuild to count calls.
            rebuild_count = {"count": 0}
            original_rebuild = tree.rebuild

            def counting_rebuild():
                rebuild_count["count"] += 1
                return original_rebuild()

            tree.rebuild = counting_rebuild

            # Begin batch mode.
            display.begin_batch()

            # These should NOT trigger tree.rebuild().
            display.add_user_message("Hello")
            display.begin_assistant_turn()
            section_id = display.add_section("response")
            await display.update_section(section_id, "World")
            display.add_tool_call("read_file", {"path": "/tmp/test"})

            # No rebuilds should have happened during batch.
            assert rebuild_count["count"] == 0, (
                f"Expected 0 rebuilds during batch mode, got {rebuild_count['count']}"
            )

            # End batch mode — should trigger a single rebuild.
            display.end_batch()
            assert rebuild_count["count"] == 1, (
                f"Expected exactly 1 rebuild after end_batch, got {rebuild_count['count']}"
            )

    @pytest.mark.asyncio
    async def test_batch_mode_suppresses_scroll(self):
        """In batch mode, _schedule_scroll() should not set timers."""
        app = _ChatApp()
        async with app.run_test(size=(80, 40)):
            display = app.chat_display

            # Begin batch mode.
            display.begin_batch()

            # Patch _scroll_to_bottom to count calls.
            scroll_count = {"count": 0}
            original_scroll = display._scroll_to_bottom

            def counting_scroll():
                scroll_count["count"] += 1

            display._scroll_to_bottom = counting_scroll

            # These should NOT trigger scroll.
            display.add_user_message("Hello")
            display.begin_assistant_turn()
            section_id = display.add_section("response")
            await display.update_section(section_id, "World")

            assert scroll_count["count"] == 0, (
                f"Expected 0 scrolls during batch mode, got {scroll_count['count']}"
            )

            # End batch — should trigger one scroll.
            display.end_batch()
            # The scroll is deferred via set_timer, so we need to let the
            # event loop process it.
            # For now just check that end_batch was called without error.

    @pytest.mark.asyncio
    async def test_batch_mode_produces_correct_tree(self):
        """After batch mode ends, the tree should contain all nodes correctly."""
        app = _ChatApp()
        async with app.run_test(size=(80, 40)):
            display = app.chat_display

            display.begin_batch()

            display.add_user_message("Hello")
            asst_id = display.begin_assistant_turn()
            section_id = display.add_section("response")
            await display.update_section(section_id, "World!")

            display.end_batch()

            # The tree should have the user message and assistant branch.
            assert len(display._root.children) == 2
            assert display._root.children[0].id == "msg-1"
            assert display._root.children[1].id == "msg-2"

    @pytest.mark.asyncio
    async def test_batch_mode_nests_sections_correctly(self):
        """Sections added in batch mode should be correctly nested under assistant."""
        app = _ChatApp()
        async with app.run_test(size=(80, 40)):
            display = app.chat_display

            display.begin_batch()

            display.add_user_message("Hello")
            asst_id = display.begin_assistant_turn()
            s1 = display.add_section("thinking")
            await display.update_section(s1, "Hmm...")
            s2 = display.add_section("response")
            await display.update_section(s2, "Answer!")
            display.add_tool_call("read_file", {"path": "/tmp/test"})

            display.end_batch()

            # Assistant node should have 3 children: thinking, response, tool_call.
            asst_node = display._find_node(asst_id)
            assert asst_node is not None
            assert len(asst_node.children) == 3

            # Verify section types.
            assert asst_node.children[0].data.get("section") == "thinking"
            assert asst_node.children[1].data.get("section") == "response"
            assert asst_node.children[2].data.get("tool_call") == "read_file"

    @pytest.mark.asyncio
    async def test_non_batch_mode_still_rebuilds(self):
        """Outside batch mode, _rebuild() should still schedule a rebuild."""
        app = _ChatApp()
        async with app.run_test(size=(80, 40)):
            display = app.chat_display

            # Not in batch mode — add should schedule a rebuild.
            display.add_user_message("Hello")

            # The rebuild is deferred via set_timer, so we check the flag.
            assert display._rebuild_pending is True, (
                "Expected _rebuild_pending to be True after add outside batch mode"
            )


# ---------------------------------------------------------------------------
# B: Node lookup map — O(1) _find_node()
# ---------------------------------------------------------------------------


class TestNodeLookupMap:
    """Tests for the node lookup map optimization."""

    @pytest.mark.asyncio
    async def test_find_node_returns_correct_node(self):
        """_find_node should find nodes in O(1) via the lookup map."""
        app = _ChatApp()
        async with app.run_test(size=(80, 40)):
            display = app.chat_display

            display.add_user_message("Hello")
            asst_id = display.begin_assistant_turn()

            # The node should be findable.
            node = display._find_node(asst_id)
            assert node is not None
            assert node.id == asst_id

    @pytest.mark.asyncio
    async def test_find_node_returns_none_for_unknown(self):
        """_find_node should return None for non-existent node IDs."""
        app = _ChatApp()
        async with app.run_test(size=(80, 40)):
            display = app.chat_display

            result = display._find_node("nonexistent-id")
            assert result is None

    @pytest.mark.asyncio
    async def test_node_map_stays_in_sync(self):
        """The node lookup map should stay in sync with tree modifications."""
        app = _ChatApp()
        async with app.run_test(size=(80, 40)):
            display = app.chat_display

            user_id = display.add_user_message("Hello")
            asst_id = display.begin_assistant_turn()
            section_id = display.add_section("response")

            # All nodes should be in the map.
            assert display._find_node(user_id) is not None
            assert display._find_node(asst_id) is not None
            assert display._find_node(section_id) is not None

            # Leaf nodes should also be findable.
            section_leaf_id = f"{section_id}-leaf"
            assert display._find_node(section_leaf_id) is not None

    @pytest.mark.asyncio
    async def test_clear_resets_node_map(self):
        """clear() should reset the node lookup map."""
        app = _ChatApp()
        async with app.run_test(size=(80, 40)):
            display = app.chat_display

            user_id = display.add_user_message("Hello")
            assert display._find_node(user_id) is not None

            display.clear()

            # After clear, old nodes should not be findable.
            assert display._find_node(user_id) is None


# ---------------------------------------------------------------------------
# C: Single-pass finalization during batch rebuild
# ---------------------------------------------------------------------------


class TestSinglePassFinalize:
    """Tests for batch-aware finalization in rebuild_from_sections."""

    @pytest.mark.asyncio
    async def test_rebuild_from_sections_produces_finalized_output(self):
        """_rebuild_display_from_sections should produce properly finalized output."""
        app = _ChatApp()
        async with app.run_test(size=(80, 40)):
            display = app.chat_display

            # Manually build sections that represent a conversation.
            sections = [
                {"turn_id": "t1", "content_type": "user", "content": "Hello"},
                {"turn_id": "t1", "content_type": "response", "content": "Hi there!"},
                {"turn_id": "t2", "content_type": "user", "content": "How are you?"},
                {"turn_id": "t2", "content_type": "thinking", "content": "Thinking..."},
                {"turn_id": "t2", "content_type": "response", "content": "I'm fine!"},
            ]

            # Replay sections into display.
            display.begin_batch()

            import json as _json
            turn_order = []
            turns = {}
            for sec in sections:
                tid = sec["turn_id"]
                if tid not in turns:
                    turn_order.append(tid)
                    turns[tid] = []
                turns[tid].append(sec)

            for tid in turn_order:
                assistant_started = False
                for sec in turns[tid]:
                    ct = sec["content_type"]
                    content = sec["content"]
                    if ct == "user":
                        display.add_user_message(content)
                    elif ct == "system":
                        display.add_system_message(content)
                    elif ct == "thinking":
                        if not assistant_started:
                            display.begin_assistant_turn()
                            assistant_started = True
                        sid = display.add_section("thinking")
                        await display.update_section(sid, content)
                    elif ct == "response":
                        if not assistant_started:
                            display.begin_assistant_turn()
                            assistant_started = True
                        sid = display.add_section("response")
                        await display.update_section(sid, content)
                    elif ct == "tool_call":
                        if not assistant_started:
                            display.begin_assistant_turn()
                            assistant_started = True
                        try:
                            tc_data = _json.loads(content)
                            display.add_tool_call(tc_data["name"], tc_data["arguments"])
                        except (_json.JSONDecodeError, KeyError):
                            display.add_tool_call("unknown", {"raw": content})

            # Finalize all turns in batch.
            display.batch_finalize_turns()

            display.end_batch()

            # Verify the tree structure: user1 + asst1 + user2 + asst2.
            assert len(display._root.children) == 4
            # All assistant turns should be finalized (no active asst).
            assert display._active_asst_id is None

    @pytest.mark.asyncio
    async def test_batch_finalize_swaps_static_to_markdown(self):
        """batch_finalize_turns should swap response sections from Static to Markdown."""
        app = _ChatApp()
        async with app.run_test(size=(80, 40)):
            display = app.chat_display

            display.begin_batch()

            display.add_user_message("Hello")
            display.begin_assistant_turn()
            sid = display.add_section("response")
            await display.update_section(sid, "Hi there!")

            display.batch_finalize_turns()
            display.end_batch()

            # The response section should have been swapped to Markdown
            # in the data model, so after end_batch's rebuild, it should
            # be a Markdown widget.
            from textual.widgets import Markdown, Static
            section_node = display._find_node(sid)
            assert section_node is not None
            assert len(section_node.children) == 1
            # The content should be a Markdown widget (swapped from Static).
            leaf = section_node.children[0]
            assert isinstance(leaf.content, Markdown), (
                f"Expected Markdown after finalize, got {type(leaf.content).__name__}"
            )


# ---------------------------------------------------------------------------
# Integration: Full rebuild flow matches original behavior
# ---------------------------------------------------------------------------


class TestRebuildIntegration:
    """Integration tests to ensure batch rebuild produces same results as original."""

    @pytest.mark.asyncio
    async def test_multi_turn_conversation_rebuild(self):
        """A multi-turn conversation rebuilt in batch mode should match expected structure."""
        app = _ChatApp()
        async with app.run_test(size=(80, 40)):
            display = app.chat_display

            display.begin_batch()

            # Turn 1: User → Response
            display.add_user_message("Hello")
            display.begin_assistant_turn()
            s1 = display.add_section("response")
            await display.update_section(s1, "Hi there!")

            # Turn 2: User → Thinking → Response
            display.add_user_message("Explain this")
            display.begin_assistant_turn()
            s2 = display.add_section("thinking")
            await display.update_section(s2, "Let me think...")
            s3 = display.add_section("response")
            await display.update_section(s3, "Here's the explanation.")

            # Turn 3: User → Tool call → Response
            display.add_user_message("Read that file")
            display.begin_assistant_turn()
            display.add_tool_call("read_file", {"path": "/tmp/test"})
            s4 = display.add_section("response")
            await display.update_section(s4, "Here's the file content.")

            display.batch_finalize_turns()
            display.end_batch()

            # Should have 6 top-level nodes: 3 user + 3 assistant.
            assert len(display._root.children) == 6

            # Verify node roles.
            assert display._root.children[0].data.get("role") == "user"
            assert display._root.children[1].data.get("role") == "assistant"
            assert display._root.children[2].data.get("role") == "user"
            assert display._root.children[3].data.get("role") == "assistant"
            assert display._root.children[4].data.get("role") == "user"
            assert display._root.children[5].data.get("role") == "assistant"

            # Assistant node 1 should have 1 section (response).
            assert len(display._root.children[1].children) == 1
            # Assistant node 2 should have 2 sections (thinking + response).
            assert len(display._root.children[3].children) == 2
            # Assistant node 3 should have 2 children (tool_call + response).
            assert len(display._root.children[5].children) == 2

    @pytest.mark.asyncio
    async def test_empty_sections_removed_after_batch_finalize(self):
        """Empty sections should be removed by batch_finalize_turns."""
        app = _ChatApp()
        async with app.run_test(size=(80, 40)):
            display = app.chat_display

            display.begin_batch()

            display.add_user_message("Hello")
            display.begin_assistant_turn()
            # Add a thinking section with no content (empty).
            s1 = display.add_section("thinking")
            # Don't call update_section — it stays empty.
            # Add a response section with content.
            s2 = display.add_section("response")
            await display.update_section(s2, "Answer!")

            display.batch_finalize_turns()
            display.end_batch()

            # The assistant node should only have the response section
            # (empty thinking section should be removed).
            asst_node = display._find_node("msg-2")
            assert asst_node is not None
            # Only response section should remain.
            assert len(asst_node.children) == 1
            assert asst_node.children[0].data.get("section") == "response"

    @pytest.mark.asyncio
    async def test_batch_rebuild_thinking_collapsed_by_default(self):
        """Thinking sections should be collapsed after batch rebuild
        when open_thinking=False (the default)."""
        app = _ChatApp()
        async with app.run_test(size=(80, 40)):
            display = app.chat_display
            tree = display.query_one(Tree)

            display.begin_batch()

            display.add_user_message("Hello")
            display.begin_assistant_turn()
            s1 = display.add_section("thinking")
            await display.update_section(s1, "Hmm...")
            s2 = display.add_section("response")
            await display.update_section(s2, "Answer!")

            display.batch_finalize_turns()
            display.end_batch()

            # The thinking section should be collapsed (default config).
            assert not tree.is_expanded(s1), (
                f"Thinking section {s1} should be collapsed after batch rebuild "
                f"when open_thinking=False"
            )
            # The response section should be expanded.
            assert tree.is_expanded(s2), (
                f"Response section {s2} should be expanded after batch rebuild"
            )

    @pytest.mark.asyncio
    async def test_batch_rebuild_thinking_expanded_when_configured(self):
        """Thinking sections should be expanded after batch rebuild
        when open_thinking=True."""
        app = _ChatApp()
        async with app.run_test(size=(80, 40)):
            # Create a ChatDisplay with open_thinking=True.
            display = ChatDisplay(open_thinking=True)

            # We need to mount it in the app.
            app.chat_display = display
            await app.query_one(Container).mount(display)

            tree = display.query_one(Tree)

            display.begin_batch()

            display.add_user_message("Hello")
            display.begin_assistant_turn()
            s1 = display.add_section("thinking")
            await display.update_section(s1, "Hmm...")
            s2 = display.add_section("response")
            await display.update_section(s2, "Answer!")

            display.batch_finalize_turns()
            display.end_batch()

            # The thinking section should be expanded (open_thinking=True).
            assert tree.is_expanded(s1), (
                f"Thinking section {s1} should be expanded after batch rebuild "
                f"when open_thinking=True"
            )

    @pytest.mark.asyncio
    async def test_batch_rebuild_tools_collapsed_by_default(self):
        """Tool call branches should be collapsed after batch rebuild
        when open_tools=False (the default)."""
        app = _ChatApp()
        async with app.run_test(size=(80, 40)):
            display = app.chat_display
            tree = display.query_one(Tree)

            display.begin_batch()

            display.add_user_message("Hello")
            display.begin_assistant_turn()
            tc1 = display.add_tool_call("read_file", {"path": "/tmp/test"})
            s1 = display.add_section("response")
            await display.update_section(s1, "Answer!")

            display.batch_finalize_turns()
            display.end_batch()

            # The tool call should be collapsed (default config).
            assert not tree.is_expanded(tc1), (
                f"Tool call {tc1} should be collapsed after batch rebuild "
                f"when open_tools=False"
            )

    @pytest.mark.asyncio
    async def test_batch_rebuild_tools_expanded_when_configured(self):
        """Tool call branches should be expanded after batch rebuild
        when open_tools=True."""
        app = _ChatApp()
        async with app.run_test(size=(80, 40)):
            # Create a ChatDisplay with open_tools=True.
            display = ChatDisplay(open_tools=True)
            app.chat_display = display
            await app.query_one(Container).mount(display)

            tree = display.query_one(Tree)

            display.begin_batch()

            display.add_user_message("Hello")
            display.begin_assistant_turn()
            tc1 = display.add_tool_call("read_file", {"path": "/tmp/test"})
            s1 = display.add_section("response")
            await display.update_section(s1, "Answer!")

            display.batch_finalize_turns()
            display.end_batch()

            # The tool call should be expanded (open_tools=True).
            assert tree.is_expanded(tc1), (
                f"Tool call {tc1} should be expanded after batch rebuild "
                f"when open_tools=True"
            )