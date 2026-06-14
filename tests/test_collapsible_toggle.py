"""Tests verifying that Collapsible subclasses in ChatDisplay are actually collapsible.

These tests ensure that our custom Collapsible widgets integrate properly
with Textual's Collapsible mechanism — specifically that they produce a
CollapsibleTitle (clickable toggle) and a Contents container (the collapsible
area), so that clicking on the title toggles visibility of the content.

The root bug: overriding compose() without calling super().compose() bypasses
Collapsible's own compose(), which creates CollapsibleTitle and Contents.
Without these, the widget cannot be collapsed/expanded interactively.
"""

from __future__ import annotations

import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from textual.app import App, ComposeResult
from textual.widgets import Collapsible, Markdown, Static
from textual.widgets._collapsible import CollapsibleTitle

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
# Test: CollapsibleTitle presence in all Collapsible subclasses
# ---------------------------------------------------------------------------


class TestCollapsibleTitlePresence:
    """Verify that each Collapsible subclass has a CollapsibleTitle and Contents."""

    @pytest.mark.asyncio
    async def test_user_message_has_collapsible_title(self):
        """UserMessage should contain a CollapsibleTitle for toggling."""
        app = _ChatApp()
        async with app.run_test(size=(80, 40)):
            display = app.chat_display
            display.add_user_message("Hello world")

            # Allow Collapsible children to compose.
            await asyncio.sleep(0.05)

            user_msg = display.query_one(UserMessage)
            titles = user_msg.query(CollapsibleTitle)
            assert len(titles) == 1, (
                f"UserMessage should have exactly 1 CollapsibleTitle, got {len(titles)}"
            )

    @pytest.mark.asyncio
    async def test_user_message_has_contents_container(self):
        """UserMessage should contain a Contents container for collapsible content."""
        app = _ChatApp()
        async with app.run_test(size=(80, 40)):
            display = app.chat_display
            display.add_user_message("Hello world")

            # Allow Collapsible children to compose.
            await asyncio.sleep(0.05)

            user_msg = display.query_one(UserMessage)
            contents = user_msg.query(Collapsible.Contents)
            assert len(contents) == 1, (
                f"UserMessage should have exactly 1 Contents container, got {len(contents)}"
            )

    @pytest.mark.asyncio
    async def test_system_message_has_collapsible_title(self):
        """SystemMessage should contain a CollapsibleTitle for toggling."""
        app = _ChatApp()
        async with app.run_test(size=(80, 40)):
            display = app.chat_display
            display.add_system_message("Chat cleared.")

            # Allow Collapsible children to compose.
            await asyncio.sleep(0.05)

            sys_msg = display.query_one(SystemMessage)
            titles = sys_msg.query(CollapsibleTitle)
            assert len(titles) == 1, (
                f"SystemMessage should have exactly 1 CollapsibleTitle, got {len(titles)}"
            )

    @pytest.mark.asyncio
    async def test_system_prompt_section_has_collapsible_title(self):
        """SystemPromptSection should contain a CollapsibleTitle for toggling."""
        app = _ChatApp()
        async with app.run_test(size=(80, 40)):
            display = app.chat_display
            display.add_system_prompt("You are a helpful assistant.")

            # Allow Collapsible children to compose.
            await asyncio.sleep(0.05)

            prompt_section = display.query_one(SystemPromptSection)
            titles = prompt_section.query(CollapsibleTitle)
            assert len(titles) == 1, (
                f"SystemPromptSection should have exactly 1 CollapsibleTitle, got {len(titles)}"
            )

    @pytest.mark.asyncio
    async def test_section_has_collapsible_title(self):
        """Section should contain a CollapsibleTitle for toggling."""
        app = _ChatApp()
        async with app.run_test(size=(80, 40)):
            display = app.chat_display
            display.begin_assistant_turn()
            display.add_section("response")

            # Allow Collapsible children to compose.
            await asyncio.sleep(0.05)

            section = display.query_one(Section)
            titles = section.query(CollapsibleTitle)
            assert len(titles) == 1, (
                f"Section should have exactly 1 CollapsibleTitle, got {len(titles)}"
            )

    @pytest.mark.asyncio
    async def test_section_has_contents_container(self):
        """Section should contain a Contents container for collapsible content."""
        app = _ChatApp()
        async with app.run_test(size=(80, 40)):
            display = app.chat_display
            display.begin_assistant_turn()
            display.add_section("response")

            # Allow Collapsible children to compose.
            await asyncio.sleep(0.05)

            section = display.query_one(Section)
            contents = section.query(Collapsible.Contents)
            assert len(contents) == 1, (
                f"Section should have exactly 1 Contents container, got {len(contents)}"
            )

    @pytest.mark.asyncio
    async def test_tool_call_section_has_collapsible_title(self):
        """ToolCallSection should contain a CollapsibleTitle for toggling."""
        app = _ChatApp()
        async with app.run_test(size=(80, 40)):
            display = app.chat_display
            display.begin_assistant_turn()
            display.add_tool_call("read_file", {"path": "/tmp/test"})

            # Allow Collapsible children to compose.
            await asyncio.sleep(0.05)

            tc_section = display.query_one(ToolCallSection)
            titles = tc_section.query(CollapsibleTitle)
            assert len(titles) == 1, (
                f"ToolCallSection should have exactly 1 CollapsibleTitle, got {len(titles)}"
            )

    @pytest.mark.asyncio
    async def test_tool_call_section_has_contents_container(self):
        """ToolCallSection should contain a Contents container for collapsible content."""
        app = _ChatApp()
        async with app.run_test(size=(80, 40)):
            display = app.chat_display
            display.begin_assistant_turn()
            display.add_tool_call("read_file", {"path": "/tmp/test"})

            # Allow Collapsible children to compose.
            await asyncio.sleep(0.05)

            tc_section = display.query_one(ToolCallSection)
            contents = tc_section.query(Collapsible.Contents)
            assert len(contents) == 1, (
                f"ToolCallSection should have exactly 1 Contents container, got {len(contents)}"
            )

    @pytest.mark.asyncio
    async def test_assistant_turn_has_collapsible_title(self):
        """AssistantTurn should contain a CollapsibleTitle for toggling."""
        app = _ChatApp()
        async with app.run_test(size=(80, 40)):
            display = app.chat_display
            display.begin_assistant_turn()

            # Allow Collapsible children to compose.
            await asyncio.sleep(0.05)

            turn = display.query_one(AssistantTurn)
            titles = turn.query(CollapsibleTitle)
            assert len(titles) == 1, (
                f"AssistantTurn should have exactly 1 CollapsibleTitle, got {len(titles)}"
            )


# ---------------------------------------------------------------------------
# Test: Collapsible toggle behavior
# ---------------------------------------------------------------------------


class TestCollapsibleToggle:
    """Verify that toggling the collapsed state actually shows/hides content."""

    @pytest.mark.asyncio
    async def test_user_message_toggle_collapsed(self):
        """Clicking CollapsibleTitle on UserMessage should toggle collapsed state."""
        app = _ChatApp()
        async with app.run_test(size=(80, 40)):
            display = app.chat_display
            display.add_user_message("Hello world")

            # Allow Collapsible children to compose.
            await asyncio.sleep(0.05)

            user_msg = display.query_one(UserMessage)
            # Starts expanded.
            assert user_msg.collapsed is False

            # Collapse it.
            user_msg.collapsed = True
            await asyncio.sleep(0)

            # The Collapsible should have the -collapsed CSS class.
            assert user_msg.has_class("-collapsed")

            # The Contents container should exist.
            contents = user_msg.query_one(Collapsible.Contents)
            assert contents.has_class("-collapsed") is False  # class is on parent

    @pytest.mark.asyncio
    async def test_section_toggle_collapsed(self):
        """Collapsing a Section should add -collapsed CSS class."""
        app = _ChatApp()
        async with app.run_test(size=(80, 40)):
            display = app.chat_display
            display.begin_assistant_turn()
            section_id = display.add_section("response")

            # Allow Collapsible children to compose.
            await asyncio.sleep(0.05)

            section = display.query_one(Section)
            # Response sections start expanded.
            assert section.collapsed is False

            # Collapse it.
            section.collapsed = True
            await asyncio.sleep(0)

            # The section should have the -collapsed CSS class.
            assert section.has_class("-collapsed")

    @pytest.mark.asyncio
    async def test_system_prompt_starts_collapsed(self):
        """SystemPromptSection should start with -collapsed CSS class."""
        app = _ChatApp()
        async with app.run_test(size=(80, 40)):
            display = app.chat_display
            display.add_system_prompt("You are a helpful assistant.")

            # Allow Collapsible children to compose.
            await asyncio.sleep(0.05)

            prompt_section = display.query_one(SystemPromptSection)
            assert prompt_section.collapsed is True

    @pytest.mark.asyncio
    async def test_collapsible_title_click_toggles(self):
        """Simulating a click on CollapsibleTitle should toggle collapsed state."""
        app = _ChatApp()
        async with app.run_test(size=(80, 40)):
            display = app.chat_display
            display.add_user_message("Hello world")

            # Allow Collapsible children to compose.
            await asyncio.sleep(0.05)

            user_msg = display.query_one(UserMessage)
            title = user_msg.query_one(CollapsibleTitle)

            # Initially expanded.
            assert user_msg.collapsed is False

            # Simulate toggle via title click message.
            title.post_message(CollapsibleTitle.Toggle())
            await asyncio.sleep(0.05)

            # Should now be collapsed.
            assert user_msg.collapsed is True

            # Toggle again.
            title.post_message(CollapsibleTitle.Toggle())
            await asyncio.sleep(0.05)

            # Should be expanded again.
            assert user_msg.collapsed is False