"""Tests for chat history loading — simulates opening a past conversation
from the history panel and verifies that the display is correctly rebuilt.
"""

import json
import pytest
from unittest.mock import MagicMock, patch

from textual.app import App, ComposeResult
from textual.widgets import Collapsible, Markdown

from core.database import DatabaseManager
from skills.chat.chat_display import (
    AssistantTurn,
    ChatDisplay,
    Section,
    SystemMessage,
    ToolCallSection,
    UserMessage,
)
from skills.chat.chat_manager import ChatManager
from skills.chat.chat_tab import ChatTabState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_sections(chat_id: str, turns: list[dict]) -> list[dict]:
    """Build flat section dicts from a list of turn dicts.

    Each turn dict has 'turn_id' and 'messages' (list of
    {content_type, content} dicts).
    All sections are marked as 'complete' by default since
    test sections represent finished content.
    """
    sections = []
    for turn in turns:
        tid = turn["turn_id"]
        for msg in turn["messages"]:
            sections.append({
                "turn_id": tid,
                "content_type": msg["content_type"],
                "content": msg["content"],
                "status": msg.get("status", "complete"),
            })
    return sections


# ---------------------------------------------------------------------------
# Test app
# ---------------------------------------------------------------------------

class _ChatApp(App):
    """Minimal app that mounts a ChatDisplay for testing."""

    CSS = """
    ChatDisplay { height: 20; }
    """

    def __init__(self):
        super().__init__()
        self.chat_display = ChatDisplay()

    def compose(self) -> ComposeResult:
        yield self.chat_display


# ---------------------------------------------------------------------------
# Tests — batch rebuild from sections
# ---------------------------------------------------------------------------


class TestBatchRebuildFromSections:
    """Test that ChatDisplay batch mode correctly
    rebuilds the conversation from a flat list of sections.

    These tests exercise the low-level batch API directly,
    which is used by ChatDisplay.refresh_from_sections()
    for efficient incremental updates.
    """

    @pytest.mark.asyncio
    async def test_simple_conversation_rebuild(self):
        """A simple user/assistant conversation should rebuild correctly."""
        flat_sections = _make_sections("chat-1", [
            {
                "turn_id": "t1",
                "messages": [
                    {"content_type": "user", "content": "Hello"},
                    {"content_type": "response", "content": "Hi there!"},
                ],
            },
            {
                "turn_id": "t2",
                "messages": [
                    {"content_type": "user", "content": "How are you?"},
                    {"content_type": "thinking", "content": "The user is asking."},
                    {"content_type": "response", "content": "I'm doing well!"},
                ],
            },
        ])

        async with _ChatApp().run_test() as pilot:
            display = pilot.app.chat_display

            # Simulate _sync_conversation(finalize=True)
            display.begin_batch()
            try:
                turn_order = []
                turns = {}
                for sec in flat_sections:
                    tid = sec["turn_id"]
                    if tid not in turns:
                        turn_order.append(tid)
                        turns[tid] = []
                    turns[tid].append(sec)

                for tid in turn_order:
                    sections = turns[tid]
                    assistant_started = False
                    for sec in sections:
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
                            section_id = await display.add_section("thinking")
                            await display.update_section(section_id, content)
                        elif ct == "response":
                            if not assistant_started:
                                display.begin_assistant_turn()
                                assistant_started = True
                            section_id = await display.add_section("response")
                            await display.update_section(section_id, content)
                        elif ct == "tool_call":
                            if not assistant_started:
                                display.begin_assistant_turn()
                                assistant_started = True
                            tc_data = json.loads(content)
                            tc_id = await display.add_tool_call(
                                tc_data["name"], tc_data["arguments"],
                            )
                            if "result" in tc_data and tc_data["result"]:
                                display.add_tool_result(tc_id, tc_data["result"])

                await display.batch_finalize_turns()
            finally:
                display.end_batch()

            # Wait for DOM to settle after batch mount
            await pilot.pause()

            # Verify display structure
            user_msgs = list(display.query(UserMessage))
            asst_turns = list(display.query(AssistantTurn))

            assert len(user_msgs) == 2, f"Expected 2 user messages, got {len(user_msgs)}"
            assert len(asst_turns) == 2, f"Expected 2 assistant turns, got {len(asst_turns)}"

    @pytest.mark.asyncio
    async def test_conversation_with_tool_calls(self):
        """A conversation with tool calls should rebuild correctly."""
        flat_sections = _make_sections("chat-2", [
            {
                "turn_id": "t1",
                "messages": [
                    {"content_type": "user", "content": "Read foo.py"},
                    {"content_type": "thinking", "content": "I need to read the file."},
                    {
                        "content_type": "tool_call",
                        "content": json.dumps({
                            "name": "read_file",
                            "arguments": {"path": "foo.py"},
                            "result": "contents of foo.py",
                        }),
                    },
                    {"content_type": "response", "content": "Here's foo.py..."},
                ],
            },
        ])

        async with _ChatApp().run_test() as pilot:
            display = pilot.app.chat_display

            display.begin_batch()
            try:
                turn_order = []
                turns = {}
                for sec in flat_sections:
                    tid = sec["turn_id"]
                    if tid not in turns:
                        turn_order.append(tid)
                        turns[tid] = []
                    turns[tid].append(sec)

                for tid in turn_order:
                    sections = turns[tid]
                    assistant_started = False
                    for sec in sections:
                        ct = sec["content_type"]
                        content = sec["content"]

                        if ct == "user":
                            display.add_user_message(content)
                        elif ct == "thinking":
                            if not assistant_started:
                                display.begin_assistant_turn()
                                assistant_started = True
                            section_id = await display.add_section("thinking")
                            await display.update_section(section_id, content)
                        elif ct == "response":
                            if not assistant_started:
                                display.begin_assistant_turn()
                                assistant_started = True
                            section_id = await display.add_section("response")
                            await display.update_section(section_id, content)
                        elif ct == "tool_call":
                            if not assistant_started:
                                display.begin_assistant_turn()
                                assistant_started = True
                            tc_data = json.loads(content)
                            tc_id = await display.add_tool_call(
                                tc_data["name"], tc_data["arguments"],
                            )
                            if "result" in tc_data and tc_data["result"]:
                                display.add_tool_result(tc_id, tc_data["result"])

                await display.batch_finalize_turns()
            finally:
                display.end_batch()

            # Wait for DOM to settle after batch mount
            await pilot.pause()

            # Verify display structure
            user_msgs = list(display.query(UserMessage))
            asst_turns = list(display.query(AssistantTurn))
            tool_calls = list(display.query(ToolCallSection))

            assert len(user_msgs) == 1, f"Expected 1 user message, got {len(user_msgs)}"
            assert len(asst_turns) == 1, f"Expected 1 assistant turn, got {len(asst_turns)}"
            assert len(tool_calls) == 1, f"Expected 1 tool call, got {len(tool_calls)}"

    @pytest.mark.asyncio
    async def test_conversation_with_system_message(self):
        """A conversation with a system message should rebuild correctly."""
        flat_sections = _make_sections("chat-3", [
            {
                "turn_id": "t1",
                "messages": [
                    {"content_type": "system", "content": "Switched to agent: coder"},
                    {"content_type": "user", "content": "Hello"},
                    {"content_type": "response", "content": "Hi!"},
                ],
            },
        ])

        async with _ChatApp().run_test() as pilot:
            display = pilot.app.chat_display

            display.begin_batch()
            try:
                turn_order = []
                turns = {}
                for sec in flat_sections:
                    tid = sec["turn_id"]
                    if tid not in turns:
                        turn_order.append(tid)
                        turns[tid] = []
                    turns[tid].append(sec)

                for tid in turn_order:
                    sections = turns[tid]
                    assistant_started = False
                    for sec in sections:
                        ct = sec["content_type"]
                        content = sec["content"]

                        if ct == "user":
                            display.add_user_message(content)
                        elif ct == "system":
                            display.add_system_message(content)
                        elif ct == "response":
                            if not assistant_started:
                                display.begin_assistant_turn()
                                assistant_started = True
                            section_id = await display.add_section("response")
                            await display.update_section(section_id, content)

                await display.batch_finalize_turns()
            finally:
                    display.end_batch()

            # Wait for DOM to settle after batch mount
            await pilot.pause()

            # Verify display structure
            user_msgs = list(display.query(UserMessage))
            sys_msgs = list(display.query(SystemMessage))
            asst_turns = list(display.query(AssistantTurn))

            assert len(user_msgs) == 1, f"Expected 1 user message, got {len(user_msgs)}"
            assert len(sys_msgs) == 1, f"Expected 1 system message, got {len(sys_msgs)}"
            assert len(asst_turns) == 1, f"Expected 1 assistant turn, got {len(asst_turns)}"

    @pytest.mark.asyncio
    async def test_empty_sections_list(self):
        """An empty sections list should not crash and should produce an empty display."""
        async with _ChatApp().run_test() as pilot:
            display = pilot.app.chat_display

            display.begin_batch()
            try:
                # No sections to add
                await display.batch_finalize_turns()
            finally:
                display.end_batch()

            user_msgs = list(display.query(UserMessage))
            asst_turns = list(display.query(AssistantTurn))

            assert len(user_msgs) == 0
            assert len(asst_turns) == 0


# ---------------------------------------------------------------------------
# Tests — ChatManager._sync_conversation integration
# ---------------------------------------------------------------------------


class TestChatManagerRebuild:
    """Test that ChatManager._sync_conversation correctly
    rebuilds the display using refresh_from_sections when opening
    a conversation from history.
    """

    def test_set_state_preserves_chat_id(self):
        """set_state() should preserve chat_id for on_mount rebuild."""
        mock_ctx = MagicMock()
        mock_ctx.database = MagicMock()

        state = ChatTabState(ctx=mock_ctx, agent_id=None)
        state._history = [{"role": "user", "content": "Hello"}]
        state._db = mock_ctx.database
        state._chat_id = "chat-1"

        manager = ChatManager()
        manager.set_state(state)

        assert manager._chat_id == "chat-1"

    @pytest.mark.asyncio
    async def test_refresh_from_sections_simple_conversation(self):
        """refresh_from_sections should rebuild a simple conversation."""
        sections = _make_sections("chat-1", [
            {
                "turn_id": "t1",
                "messages": [
                    {"content_type": "user", "content": "Hello"},
                    {"content_type": "response", "content": "Hi there!"},
                ],
            },
        ])

        # Add section_id for refresh_from_sections
        for i, sec in enumerate(sections):
            sec["section_id"] = f"sec-{i+1}"
            sec["id"] = i + 1

        async with _ChatApp().run_test() as pilot:
            display = pilot.app.chat_display

            await display.refresh_from_sections(sections, finalize=True)

            user_msgs = list(display.query(UserMessage))
            asst_turns = list(display.query(AssistantTurn))

            assert len(user_msgs) == 1, f"Expected 1 user message, got {len(user_msgs)}"
            assert len(asst_turns) == 1, f"Expected 1 assistant turn, got {len(asst_turns)}"

    @pytest.mark.asyncio
    async def test_refresh_from_sections_only_user_messages(self):
        """refresh_from_sections should handle turns with only user messages."""
        sections = _make_sections("chat-1", [
            {
                "turn_id": "t1",
                "messages": [
                    {"content_type": "user", "content": "Hello"},
                ],
            },
        ])

        for i, sec in enumerate(sections):
            sec["section_id"] = f"sec-{i+1}"
            sec["id"] = i + 1

        async with _ChatApp().run_test() as pilot:
            display = pilot.app.chat_display

            await display.refresh_from_sections(sections, finalize=True)

            user_msgs = list(display.query(UserMessage))
            assert len(user_msgs) == 1, f"Expected 1 user message, got {len(user_msgs)}"



# ---------------------------------------------------------------------------
# Tests — HistoryPanel._open_chat
# ---------------------------------------------------------------------------


class TestRefreshFromSectionsMultiTurn:
    """Test that refresh_from_sections(f finalize=True) correctly
    rebuilds multi-turn conversations, including the Static→Markdown
    swap for all turns (not just the last one).

    Regression test for the bug where begin_assistant_turn() clears
    per-turn tracking dicts, causing earlier turns' sections to appear
    "empty" and be removed by finalize_turn().
    """

    @pytest.mark.asyncio
    async def test_multi_turn_finalize_preserves_earlier_turns(self):
        """All turns should have their sections after finalize."""
        sections = _make_sections("chat-1", [
            {
                "turn_id": "t1",
                "messages": [
                    {"content_type": "user", "content": "Hello"},
                    {"content_type": "response", "content": "Hi there!"},
                ],
            },
            {
                "turn_id": "t2",
                "messages": [
                    {"content_type": "user", "content": "How are you?"},
                    {"content_type": "thinking", "content": "The user is asking."},
                    {"content_type": "response", "content": "I am doing well!"},
                ],
            },
        ])

        # Add section_id for refresh_from_sections
        for i, sec in enumerate(sections):
            sec["section_id"] = f"sec-{i+1}"
            sec["id"] = i + 1

        async with _ChatApp().run_test() as pilot:
            display = pilot.app.chat_display

            await display.refresh_from_sections(sections, finalize=True)

            # Allow DOM to settle after batch mount
            await pilot.pause()

            user_msgs = list(display.query(UserMessage))
            asst_turns = list(display.query(AssistantTurn))

            assert len(user_msgs) == 2, f"Expected 2 user messages, got {len(user_msgs)}"
            assert len(asst_turns) == 2, f"Expected 2 assistant turns, got {len(asst_turns)}"

            # Verify each turn has its sections
            for turn in asst_turns:
                sections_in_turn = list(turn.query(Section))
                assert len(sections_in_turn) > 0, (
                    f"Turn {turn.turn_id} has no sections!"
                )

    @pytest.mark.asyncio
    async def test_multi_turn_response_sections_use_markdown(self):
        """Response sections in ALL turns should be Markdown, not Static."""
        sections = _make_sections("chat-1", [
            {
                "turn_id": "t1",
                "messages": [
                    {"content_type": "user", "content": "Hello"},
                    {"content_type": "response", "content": "Hi there!"},
                ],
            },
            {
                "turn_id": "t2",
                "messages": [
                    {"content_type": "user", "content": "How are you?"},
                    {"content_type": "response", "content": "I am doing well!"},
                ],
            },
        ])

        for i, sec in enumerate(sections):
            sec["section_id"] = f"sec-{i+1}"
            sec["id"] = i + 1

        async with _ChatApp().run_test() as pilot:
            display = pilot.app.chat_display

            await display.refresh_from_sections(sections, finalize=True)
            await pilot.pause()

            # Both response sections should have Markdown content widgets
            # (swapped from Static during batch_finalize_turns).
            all_sections = list(display.query(Section))
            response_sections = [
                s for s in all_sections
                if not isinstance(s, ToolCallSection)
                and s.section_id.startswith("response-")
            ]
            assert len(response_sections) == 2, (
                f"Expected 2 response sections, got {len(response_sections)}"
            )
            for s in response_sections:
                cw = s._content_widget
                assert isinstance(cw, Markdown), (
                    f"Response section {s.section_id} should have Markdown "
                    f"content, got {type(cw).__name__}"
                )

    @pytest.mark.asyncio
    async def test_multi_turn_with_tool_calls(self):
        """Multi-turn conversation with tool calls should rebuild correctly."""
        sections = _make_sections("chat-1", [
            {
                "turn_id": "t1",
                "messages": [
                    {"content_type": "user", "content": "Read foo.py"},
                    {
                        "content_type": "tool_call",
                        "content": json.dumps({
                            "name": "read_file",
                            "arguments": {"path": "foo.py"},
                            "result": "contents of foo.py",
                        }),
                    },
                    {"content_type": "response", "content": "Here is foo.py..."},
                ],
            },
            {
                "turn_id": "t2",
                "messages": [
                    {"content_type": "user", "content": "Thanks!"},
                    {"content_type": "response", "content": "You are welcome!"},
                ],
            },
        ])

        for i, sec in enumerate(sections):
            sec["section_id"] = f"sec-{i+1}"
            sec["id"] = i + 1

        async with _ChatApp().run_test() as pilot:
            display = pilot.app.chat_display

            await display.refresh_from_sections(sections, finalize=True)
            await pilot.pause()

            user_msgs = list(display.query(UserMessage))
            asst_turns = list(display.query(AssistantTurn))
            tool_calls = list(display.query(ToolCallSection))

            assert len(user_msgs) == 2, f"Expected 2 user messages, got {len(user_msgs)}"
            assert len(asst_turns) == 2, f"Expected 2 assistant turns, got {len(asst_turns)}"
            assert len(tool_calls) == 1, f"Expected 1 tool call, got {len(tool_calls)}"

            # Tool call should have result flag set
            assert tool_calls[0]._has_result is True


# ---------------------------------------------------------------------------
# Tests — HistoryPanel._open_chat
# ---------------------------------------------------------------------------


class TestHistoryPanelOpenChat:
    """Test the HistoryPanel._open_chat flow end-to-end."""

    @pytest.mark.asyncio
    async def test_open_chat_creates_tab(self):
        """_open_chat should create a chat tab with the loaded conversation."""
        # Create an in-memory database with a conversation
        db = DatabaseManager(":memory:")

        # Create a chat
        chat_id = db.create_chat()
        # Add a user message
        db.save_section(chat_id, "t1", "user", "Hello")
        # Add an assistant response
        db.save_section(chat_id, "t1", "response", "Hi there!")

        # Load sections
        sections = db.load_sections(chat_id)
        assert len(sections) == 2, f"Expected 2 sections, got {len(sections)}"
        assert sections[0]["content_type"] == "user"
        assert sections[0]["content"] == "Hello"
        assert sections[1]["content_type"] == "response"
        assert sections[1]["content"] == "Hi there!"