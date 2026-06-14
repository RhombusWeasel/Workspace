"""Tests for the refactored ChatDisplay (VerticalScroll + Collapsible).

Verifies the same public API as the Tree-based implementation, ensuring
ChatManager requires minimal changes.

Tests cover:
1. User message rendering
2. Assistant turn lifecycle (begin, add_section, finalize)
3. Streaming with Static widgets
4. Static → Markdown swap on finalize
5. Thinking sections stay as Static
6. Tool call rendering
7. System message rendering
8. System prompt rendering
9. Batch mode (conversation restore)
10. Clear/reset
11. Empty section removal on finalize
12. Collapsed label previews
13. Expand/collapse config (open_thinking, open_tools)
"""

from __future__ import annotations

import os
import sys

import asyncio

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from textual.app import App, ComposeResult
from textual.widgets import Collapsible, Markdown, Static

from core.paths import collect_tcss
from skills.chat.chat_display import (
    ChatDisplay,
    UserMessage,
    AssistantTurn,
    Section,
    ToolCallSection,
    SystemMessage,
    SystemPromptSection,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _ChatApp(App):
    """Minimal app that mounts a ChatDisplay for testing."""
    CSS_PATH = collect_tcss(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )

    def __init__(self, open_thinking=False, open_tools=False, show_system_prompt=False, **kwargs):
        super().__init__(**kwargs)
        self.chat_display = ChatDisplay(
            open_thinking=open_thinking,
            open_tools=open_tools,
            show_system_prompt=show_system_prompt,
        )

    def compose(self) -> ComposeResult:
        yield self.chat_display


# ---------------------------------------------------------------------------
# A: User messages
# ---------------------------------------------------------------------------


class TestUserMessage:
    """Tests for adding user messages."""

    @pytest.mark.asyncio
    async def test_add_user_message_mounts_collapsible(self):
        """add_user_message should mount a UserMessage Collapsible."""
        app = _ChatApp()
        async with app.run_test(size=(80, 40)):
            display = app.chat_display
            msg_id = display.add_user_message("Hello, world!")

            # Should find a UserMessage widget in the display.
            user_msgs = display.query(UserMessage)
            assert len(user_msgs) == 1
            assert user_msgs[0].message_id == msg_id

    @pytest.mark.asyncio
    async def test_user_message_contains_markdown(self):
        """A user message should contain a Markdown widget with the text."""
        app = _ChatApp()
        async with app.run_test(size=(80, 40)):
            display = app.chat_display
            display.add_user_message("Hello, **world**!")

            # Allow Collapsible children to compose.
            await asyncio.sleep(0.05)

            user_msg = display.query_one(UserMessage)
            # The Markdown widget inside should have the text.
            md_widgets = user_msg.query(Markdown)
            assert len(md_widgets) >= 1

    @pytest.mark.asyncio
    async def test_add_multiple_user_messages(self):
        """Multiple user messages should be mounted in order."""
        app = _ChatApp()
        async with app.run_test(size=(80, 40)):
            display = app.chat_display
            display.add_user_message("First")
            display.add_user_message("Second")

            user_msgs = display.query(UserMessage)
            assert len(user_msgs) == 2


# ---------------------------------------------------------------------------
# B: Assistant turn lifecycle
# ---------------------------------------------------------------------------


class TestAssistantTurnLifecycle:
    """Tests for begin_assistant_turn, add_section, finalize_turn."""

    @pytest.mark.asyncio
    async def test_begin_assistant_turn_mounts_container(self):
        """begin_assistant_turn should mount an AssistantTurn container."""
        app = _ChatApp()
        async with app.run_test(size=(80, 40)):
            display = app.chat_display
            asst_id = display.begin_assistant_turn()

            turns = display.query(AssistantTurn)
            assert len(turns) == 1
            assert turns[0].turn_id == asst_id

    @pytest.mark.asyncio
    async def test_add_section_creates_collapsible(self):
        """add_section should mount a Section Collapsible inside the turn."""
        app = _ChatApp()
        async with app.run_test(size=(80, 40)):
            display = app.chat_display
            display.begin_assistant_turn()
            section_id = display.add_section("response")

            # Allow the section to mount (compose_add_child is deferred).
            await asyncio.sleep(0.05)

            turn = display.query_one(AssistantTurn)
            sections = turn.query(Section)
            assert len(sections) == 1
            assert sections[0].section_id == section_id

    @pytest.mark.asyncio
    async def test_section_starts_as_static(self):
        """During streaming, sections should use Static widgets."""
        app = _ChatApp()
        async with app.run_test(size=(80, 40)):
            display = app.chat_display
            display.begin_assistant_turn()
            section_id = display.add_section("response")

            # The content widget should be a Static.
            widget = display._section_widgets.get(section_id)
            assert isinstance(widget, Static)

    @pytest.mark.asyncio
    async def test_update_section_updates_static(self):
        """update_section should update the Static widget text."""
        app = _ChatApp()
        async with app.run_test(size=(80, 40)):
            display = app.chat_display
            display.begin_assistant_turn()
            section_id = display.add_section("response")
            await display.update_section(section_id, "Hello world")

            # The tracked text should match.
            assert display._section_texts.get(section_id) == "Hello world"


# ---------------------------------------------------------------------------
# C: Finalize — Static → Markdown swap
# ---------------------------------------------------------------------------


class TestFinalizeSwap:
    """Tests for finalize_turn swapping Static → Markdown."""

    @pytest.mark.asyncio
    async def test_finalize_swaps_response_to_markdown(self):
        """finalize_turn should swap response sections from Static to Markdown."""
        app = _ChatApp()
        async with app.run_test(size=(80, 40)):
            display = app.chat_display
            display.begin_assistant_turn()
            section_id = display.add_section("response")
            await display.update_section(section_id, "Hello **world**!")
            await display.finalize_turn()

            # Allow mount to complete (swap is async).
            await asyncio.sleep(0.05)

            # After finalize, the section's content widget should be Markdown.
            section_node = display._find_section(section_id)
            assert section_node is not None
            md_widgets = section_node.query(Markdown)
            assert len(md_widgets) >= 1

    @pytest.mark.asyncio
    async def test_finalize_keeps_thinking_as_static(self):
        """finalize_turn should NOT swap thinking sections — they stay Static."""
        app = _ChatApp()
        async with app.run_test(size=(80, 40)):
            display = app.chat_display
            display.begin_assistant_turn()
            section_id = display.add_section("thinking")
            await display.update_section(section_id, "Hmm...")
            await display.finalize_turn()

            # Allow mount to complete.
            await asyncio.sleep(0.05)

            # Thinking sections should remain as Static — find the Section
            # in the DOM and check its content widget.
            all_sections = display.query(Section)
            # Should have at least one Section with a Static child.
            static_count = 0
            for s in all_sections:
                if hasattr(s, '_content_widget') and isinstance(s._content_widget, Static):
                    static_count += 1
            assert static_count >= 1, "Expected at least one thinking section with Static content"

    @pytest.mark.asyncio
    async def test_finalize_removes_empty_sections(self):
        """finalize_turn should remove sections with no content."""
        app = _ChatApp()
        async with app.run_test(size=(80, 40)):
            display = app.chat_display
            asst_id = display.begin_assistant_turn()
            thinking_id = display.add_section("thinking")
            # Don't update the thinking section — it stays empty.
            response_id = display.add_section("response")
            await display.update_section(response_id, "Answer!")
            await display.finalize_turn()

            # Allow mount to complete.
            await asyncio.sleep(0.05)

            # The empty thinking section should be removed from the turn.
            turn = display._find_assistant_turn(asst_id)
            assert turn is not None
            sections = turn.query(Section)
            # Only the response section should remain.
            assert len(sections) == 1
            assert sections[0].section_id == response_id


# ---------------------------------------------------------------------------
# D: Tool calls
# ---------------------------------------------------------------------------


class TestToolCall:
    """Tests for add_tool_call."""

    @pytest.mark.asyncio
    async def test_add_tool_call_mounts_section(self):
        """add_tool_call should mount a ToolCallSection Collapsible."""
        app = _ChatApp()
        async with app.run_test(size=(80, 40)):
            display = app.chat_display
            display.begin_assistant_turn()
            tc_id = display.add_tool_call("read_file", {"path": "/tmp/test"})

            # Allow tool call section to mount.
            await asyncio.sleep(0.05)

            turn = display.query_one(AssistantTurn)
            tool_sections = turn.query(ToolCallSection)
            assert len(tool_sections) == 1
            assert tool_sections[0].section_id == tc_id

    @pytest.mark.asyncio
    async def test_tool_call_contains_markdown(self):
        """A tool call section should contain a Markdown widget with formatted args."""
        app = _ChatApp()
        async with app.run_test(size=(80, 40)):
            display = app.chat_display
            display.begin_assistant_turn()
            display.add_tool_call("read_file", {"path": "/tmp/test"})

            # Allow Collapsible children to compose.
            await asyncio.sleep(0.05)

            turn = display.query_one(AssistantTurn)
            tool_section = turn.query_one(ToolCallSection)
            md_widgets = tool_section.query(Markdown)
            assert len(md_widgets) >= 1

    @pytest.mark.asyncio
    async def test_tool_call_collapsed_by_default(self):
        """Tool call sections should start collapsed when open_tools=False (default)."""
        app = _ChatApp()
        async with app.run_test(size=(80, 40)):
            display = app.chat_display
            display.begin_assistant_turn()
            display.add_tool_call("read_file", {"path": "/tmp/test"})

            # Allow tool call section to mount.
            await asyncio.sleep(0.05)

            turn = display.query_one(AssistantTurn)
            tool_section = turn.query_one(ToolCallSection)
            assert tool_section.collapsed is True

    @pytest.mark.asyncio
    async def test_tool_call_expanded_when_configured(self):
        """Tool call sections should start expanded when open_tools=True."""
        app = _ChatApp(open_tools=True)
        async with app.run_test(size=(80, 40)):
            display = app.chat_display

            display.begin_assistant_turn()
            display.add_tool_call("read_file", {"path": "/tmp/test"})

            # Allow tool call section to mount.
            await asyncio.sleep(0.05)

            turn = display.query_one(AssistantTurn)
            tool_section = turn.query_one(ToolCallSection)
            assert tool_section.collapsed is False


# ---------------------------------------------------------------------------
# E: System messages
# ---------------------------------------------------------------------------


class TestSystemMessage:
    """Tests for add_system_message."""

    @pytest.mark.asyncio
    async def test_add_system_message(self):
        """add_system_message should mount a SystemMessage Collapsible."""
        app = _ChatApp()
        async with app.run_test(size=(80, 40)):
            display = app.chat_display
            msg_id = display.add_system_message("Chat cleared.")

            sys_msgs = display.query(SystemMessage)
            assert len(sys_msgs) == 1
            assert sys_msgs[0].message_id == msg_id


# ---------------------------------------------------------------------------
# F: System prompt
# ---------------------------------------------------------------------------


class TestSystemPrompt:
    """Tests for add_system_prompt."""

    @pytest.mark.asyncio
    async def test_add_system_prompt_starts_collapsed(self):
        """System prompt sections should start collapsed."""
        app = _ChatApp()
        async with app.run_test(size=(80, 40)):
            display = app.chat_display
            display.add_system_prompt("You are a helpful assistant.")

            # Allow Collapsible children to compose.
            await asyncio.sleep(0)

            # Check for SystemPromptSection widgets.
            from skills.chat.chat_display import SystemPromptSection
            prompt_sections = display.query(SystemPromptSection)
            assert len(prompt_sections) >= 1
            assert prompt_sections[0].collapsed is True


# ---------------------------------------------------------------------------
# G: Batch mode
# ---------------------------------------------------------------------------


class TestBatchMode:
    """Tests for batch mode (conversation restore)."""

    @pytest.mark.asyncio
    async def test_batch_mode_produces_correct_structure(self):
        """After batch mode, all widgets should be mounted correctly."""
        app = _ChatApp()
        async with app.run_test(size=(80, 40)):
            display = app.chat_display

            display.begin_batch()

            display.add_user_message("Hello")
            display.begin_assistant_turn()
            s1 = display.add_section("response")
            await display.update_section(s1, "Hi!")

            display.end_batch()

            user_msgs = display.query(UserMessage)
            turns = display.query(AssistantTurn)
            assert len(user_msgs) == 1
            assert len(turns) == 1

    @pytest.mark.asyncio
    async def test_batch_finalize_turns(self):
        """batch_finalize_turns should swap Static → Markdown."""
        app = _ChatApp()
        async with app.run_test(size=(80, 40)):
            display = app.chat_display

            display.begin_batch()

            display.add_user_message("Hello")
            display.begin_assistant_turn()
            s1 = display.add_section("response")
            await display.update_section(s1, "Answer!")

            display.batch_finalize_turns()
            display.end_batch()

            # Allow mount to complete.
            await asyncio.sleep(0.1)

            # After finalize, the response section should have Markdown content.
            section_widget = display._find_section(s1)
            # section_map is cleared after end_batch, but _find_section
            # may return None — check the DOM directly.
            md_widgets = display.query(Markdown)
            assert len(md_widgets) >= 1, "Expected at least one Markdown widget after finalize"

    @pytest.mark.asyncio
    async def test_batch_finalize_removes_empty_sections(self):
        """batch_finalize_turns should remove empty sections."""
        app = _ChatApp()
        async with app.run_test(size=(80, 40)):
            display = app.chat_display

            display.begin_batch()

            display.add_user_message("Hello")
            asst_id = display.begin_assistant_turn()
            # Add a thinking section with no content (empty).
            s1 = display.add_section("thinking")
            # Add a response section with content.
            s2 = display.add_section("response")
            await display.update_section(s2, "Answer!")

            display.batch_finalize_turns()
            display.end_batch()

            # Allow mount to complete.
            await asyncio.sleep(0.1)

            # The turn should have only one Section (the response),
            # since the empty thinking section was removed.
            turn = display._find_assistant_turn(asst_id)
            assert turn is not None
            all_sections = turn.query(Section)
            # ToolCallSection is a subclass of Section, so filter it out.
            non_tool_sections = [s for s in all_sections if not isinstance(s, ToolCallSection)]
            assert len(non_tool_sections) == 1


# ---------------------------------------------------------------------------
# H: Clear / Reset
# ---------------------------------------------------------------------------


class TestClear:
    """Tests for the clear() method."""

    @pytest.mark.asyncio
    async def test_clear_removes_all_messages(self):
        """clear() should remove all widgets from the display."""
        app = _ChatApp()
        async with app.run_test(size=(80, 40)):
            display = app.chat_display

            display.add_user_message("Hello")
            display.begin_assistant_turn()
            s1 = display.add_section("response")
            await display.update_section(s1, "Hi!")

            display.clear()

            # Allow removal to complete.
            await asyncio.sleep(0.1)

            # No UserMessage or AssistantTurn widgets should remain.
            assert len(display.query(UserMessage)) == 0
            assert len(display.query(AssistantTurn)) == 0

    @pytest.mark.asyncio
    async def test_clear_resets_state(self):
        """clear() should reset internal tracking state."""
        app = _ChatApp()
        async with app.run_test(size=(80, 40)):
            display = app.chat_display

            display.add_user_message("Hello")
            display.begin_assistant_turn()

            display.clear()

            # Internal state should be reset.
            assert display._turn_count == 0
            assert display._section_count == 0
            assert display._tool_call_count == 0
            assert display._active_asst_id is None


# ---------------------------------------------------------------------------
# I: Expand/collapse config
# ---------------------------------------------------------------------------


class TestExpandConfig:
    """Tests for open_thinking and open_tools config."""

    @pytest.mark.asyncio
    async def test_thinking_collapsed_by_default(self):
        """Thinking sections should start collapsed when open_thinking=False."""
        app = _ChatApp()
        async with app.run_test(size=(80, 40)):
            display = app.chat_display
            display.begin_assistant_turn()
            section_id = display.add_section("thinking")

            section_widget = display._find_section(section_id)
            assert section_widget is not None
            assert section_widget.collapsed is True

    @pytest.mark.asyncio
    async def test_thinking_expanded_when_configured(self):
        """Thinking sections should start expanded when open_thinking=True."""
        app = _ChatApp(open_thinking=True)
        async with app.run_test(size=(80, 40)):
            display = app.chat_display

            display.begin_assistant_turn()
            section_id = display.add_section("thinking")

            section_widget = display._find_section(section_id)
            assert section_widget is not None
            assert section_widget.collapsed is False

    @pytest.mark.asyncio
    async def test_response_expanded_by_default(self):
        """Response sections should start expanded."""
        app = _ChatApp()
        async with app.run_test(size=(80, 40)):
            display = app.chat_display
            display.begin_assistant_turn()
            section_id = display.add_section("response")

            section_widget = display._find_section(section_id)
            assert section_widget is not None
            assert section_widget.collapsed is False


# ---------------------------------------------------------------------------
# J: Multi-turn conversation
# ---------------------------------------------------------------------------


class TestMultiTurn:
    """Tests for multi-turn conversation flow."""

    @pytest.mark.asyncio
    async def test_full_multi_turn_flow(self):
        """A complete multi-turn conversation should render correctly."""
        app = _ChatApp()
        async with app.run_test(size=(80, 40)):
            display = app.chat_display

            # Turn 1: User → Response
            display.add_user_message("Hello")
            display.begin_assistant_turn()
            s1 = display.add_section("response")
            await display.update_section(s1, "Hi there!")
            await display.finalize_turn()

            # Turn 2: User → Thinking → Response
            display.add_user_message("Explain this")
            display.begin_assistant_turn()
            s2 = display.add_section("thinking")
            await display.update_section(s2, "Let me think...")
            s3 = display.add_section("response")
            await display.update_section(s3, "Here's the explanation.")
            await display.finalize_turn()

            # Should have 2 user messages and 2 assistant turns.
            user_msgs = display.query(UserMessage)
            assert len(user_msgs) == 2
            turns = display.query(AssistantTurn)
            assert len(turns) == 2

    @pytest.mark.asyncio
    async def test_tool_call_between_sections(self):
        """Tool calls should appear as sections within the assistant turn."""
        app = _ChatApp()
        async with app.run_test(size=(80, 40)):
            display = app.chat_display

            display.add_user_message("Read that file")
            display.begin_assistant_turn()
            display.add_tool_call("read_file", {"path": "/tmp/test"})
            s1 = display.add_section("response")
            await display.update_section(s1, "Here's the content.")
            await display.finalize_turn()

            # Allow deferred mounts to complete.
            await asyncio.sleep(0.05)

            turn = display.query_one(AssistantTurn)
            # Turn should have a ToolCallSection and a Section.
            tool_sections = turn.query(ToolCallSection)
            assert len(tool_sections) == 1
            response_sections = [s for s in turn.query(Section) if not isinstance(s, ToolCallSection)]
            assert len(response_sections) == 1


# ---------------------------------------------------------------------------
# K: CSS class assignment
# ---------------------------------------------------------------------------


class TestMessageCSSClasses:
    """Tests for coloured left-border CSS classes on message widgets."""

    @pytest.mark.asyncio
    async def test_user_message_has_chat_user_class(self):
        """UserMessage should have the chat-user CSS class."""
        app = _ChatApp()
        async with app.run_test(size=(80, 40)):
            display = app.chat_display
            display.add_user_message("Hello")

            user_msg = display.query_one(UserMessage)
            assert user_msg.has_class("chat-user")

    @pytest.mark.asyncio
    async def test_assistant_turn_has_chat_response_class(self):
        """AssistantTurn should have the chat-response CSS class."""
        app = _ChatApp()
        async with app.run_test(size=(80, 40)):
            display = app.chat_display
            display.begin_assistant_turn()

            turn = display.query_one(AssistantTurn)
            assert turn.has_class("chat-response")

    @pytest.mark.asyncio
    async def test_thinking_section_has_chat_thinking_class(self):
        """Thinking Section should have the chat-thinking CSS class."""
        app = _ChatApp()
        async with app.run_test(size=(80, 40)):
            display = app.chat_display
            display.begin_assistant_turn()
            display.add_section("thinking")

            # Allow deferred mount.
            await asyncio.sleep(0.05)

            # Find the Section — it should have the chat-thinking class.
            all_sections = display.query(Section)
            # Filter out ToolCallSection subclasses.
            sections = [s for s in all_sections if not isinstance(s, ToolCallSection)]
            assert len(sections) == 1
            assert sections[0].has_class("chat-thinking")

    @pytest.mark.asyncio
    async def test_response_section_has_chat_response_class(self):
        """Response Section should have the chat-response CSS class."""
        app = _ChatApp()
        async with app.run_test(size=(80, 40)):
            display = app.chat_display
            display.begin_assistant_turn()
            display.add_section("response")

            # Allow deferred mount.
            await asyncio.sleep(0.05)

            all_sections = display.query(Section)
            sections = [s for s in all_sections if not isinstance(s, ToolCallSection)]
            assert len(sections) == 1
            assert sections[0].has_class("chat-response")

    @pytest.mark.asyncio
    async def test_tool_call_section_has_chat_tools_class(self):
        """ToolCallSection should have the chat-tools CSS class."""
        app = _ChatApp()
        async with app.run_test(size=(80, 40)):
            display = app.chat_display
            display.begin_assistant_turn()
            display.add_tool_call("read_file", {"path": "/tmp/test"})

            # Allow deferred mount.
            await asyncio.sleep(0.05)

            tool_section = display.query_one(ToolCallSection)
            assert tool_section.has_class("chat-tools")

    @pytest.mark.asyncio
    async def test_system_message_has_chat_system_class(self):
        """SystemMessage should have the chat-system CSS class."""
        app = _ChatApp()
        async with app.run_test(size=(80, 40)):
            display = app.chat_display
            display.add_system_message("Chat cleared.")

            sys_msg = display.query_one(SystemMessage)
            assert sys_msg.has_class("chat-system")

    @pytest.mark.asyncio
    async def test_system_prompt_has_chat_system_class(self):
        """SystemPromptSection should have the chat-system CSS class."""
        app = _ChatApp()
        async with app.run_test(size=(80, 40)):
            display = app.chat_display
            display.add_system_prompt("You are a helpful assistant.")

            # Allow deferred mount.
            await asyncio.sleep(0)

            prompt_section = display.query_one(SystemPromptSection)
            assert prompt_section.has_class("chat-system")


# ---------------------------------------------------------------------------
# L: Tool result display
# ---------------------------------------------------------------------------


class TestToolResult:
    """Tests for add_tool_result updating ToolCallSection with result."""

    @pytest.mark.asyncio
    async def test_add_tool_result_updates_markdown(self):
        """add_tool_result should append result to the ToolCallSection markdown."""
        app = _ChatApp()
        async with app.run_test(size=(80, 40)):
            display = app.chat_display
            display.begin_assistant_turn()
            tc_id = display.add_tool_call("read_file", {"path": "/tmp/test"})

            # Allow tool call section to mount.
            await asyncio.sleep(0.05)

            # Add the result.
            display.add_tool_result(tc_id, "file contents here")

            # Check the ToolCallSection has the result flag set.
            tool_section = display.query_one(ToolCallSection)
            assert tool_section._has_result is True

    @pytest.mark.asyncio
    async def test_add_tool_result_updates_label(self):
        """add_tool_result should update the collapsed label with checkmark."""
        app = _ChatApp()
        async with app.run_test(size=(80, 40)):
            display = app.chat_display
            display.begin_assistant_turn()
            tc_id = display.add_tool_call("read_file", {"path": "/tmp/test"})

            await asyncio.sleep(0.05)

            display.add_tool_result(tc_id, "file contents here")

            tool_section = display.query_one(ToolCallSection)
            # The title should now contain a checkmark.
            assert "\u2714" in tool_section.title

    @pytest.mark.asyncio
    async def test_add_tool_result_idempotent(self):
        """Calling add_tool_result twice should not duplicate the result."""
        app = _ChatApp()
        async with app.run_test(size=(80, 40)):
            display = app.chat_display
            display.begin_assistant_turn()
            tc_id = display.add_tool_call("read_file", {"path": "/tmp/test"})

            await asyncio.sleep(0.05)

            display.add_tool_result(tc_id, "first result")
            display.add_tool_result(tc_id, "second result")

            tool_section = display.query_one(ToolCallSection)
            # _has_result should still be True (not double-processed).
            assert tool_section._has_result is True

    @pytest.mark.asyncio
    async def test_add_tool_result_nonexistent_tc(self):
        """add_tool_result with a bad tc_id should be a no-op."""
        app = _ChatApp()
        async with app.run_test(size=(80, 40)):
            display = app.chat_display
            display.begin_assistant_turn()

            # Should not raise.
            display.add_tool_result("tc-999", "some result")

    @pytest.mark.asyncio
    async def test_tool_call_with_result_in_batch_mode(self):
        """Tool call with result should display correctly in batch mode."""
        app = _ChatApp()
        async with app.run_test(size=(80, 40)):
            display = app.chat_display

            display.begin_batch()
            display.add_user_message("Read the file")
            display.begin_assistant_turn()
            tc_id = display.add_tool_call("read_file", {"path": "/tmp/test"})
            s1 = display.add_section("response")
            await display.update_section(s1, "Here's what I found.")
            display.add_tool_result(tc_id, "file contents here")
            display.batch_finalize_turns()
            display.end_batch()

            await asyncio.sleep(0.1)

            # Check the ToolCallSection has the result.
            tool_section = display.query_one(ToolCallSection)
            assert tool_section._has_result is True
            assert "\u2714" in tool_section.title