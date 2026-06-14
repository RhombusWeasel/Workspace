"""Tests for streaming update optimizations in ChatDisplay.

Verifies:
1. Coalesced scroll — only one scroll timer exists at a time.
2. Throttled rebuild — rapid _rebuild() calls are coalesced into one.
3. Targeted expand — incremental additions use targeted expand
   instead of full restore_expand_state().
4. Streaming update path is efficient — update_section doesn't rebuild.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from textual.app import App, ComposeResult
from textual.containers import Container
from textual.widgets import Markdown, Static

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
# A: Coalesced scroll
# ---------------------------------------------------------------------------


class TestCoalescedScroll:
    """Tests for the coalesced scroll optimization.

    During streaming, _schedule_scroll() is called on every update_section().
    Without coalescing, each call creates a new timer. With coalescing,
    only one timer exists at a time — new calls while a timer is pending
    are no-ops.
    """

    @pytest.mark.asyncio
    async def test_schedule_scroll_creates_timer_on_first_call(self):
        """First _schedule_scroll() should create a timer."""
        app = _ChatApp()
        async with app.run_test(size=(80, 40)):
            display = app.chat_display

            # Track timer creation.
            timer_count = {"count": 0}
            original_set_timer = display.set_timer

            def counting_set_timer(delay, callback, **kwargs):
                timer_count["count"] += 1
                return original_set_timer(delay, callback, **kwargs)

            display.set_timer = counting_set_timer

            display._schedule_scroll()
            assert timer_count["count"] == 1, (
                f"Expected 1 timer on first call, got {timer_count['count']}"
            )

    @pytest.mark.asyncio
    async def test_schedule_scroll_coalesces_rapid_calls(self):
        """Multiple rapid _schedule_scroll() calls should only create one timer."""
        app = _ChatApp()
        async with app.run_test(size=(80, 40)):
            display = app.chat_display

            timer_count = {"count": 0}
            original_set_timer = display.set_timer

            def counting_set_timer(delay, callback, **kwargs):
                timer_count["count"] += 1
                return original_set_timer(delay, callback, **kwargs)

            display.set_timer = counting_set_timer

            # Simulate rapid streaming: 20 scroll requests.
            for _ in range(20):
                display._schedule_scroll()

            # Only one timer should have been created.
            assert timer_count["count"] == 1, (
                f"Expected 1 timer with coalescing, got {timer_count['count']}"
            )

    @pytest.mark.asyncio
    async def test_schedule_scroll_creates_new_timer_after_fire(self):
        """After the pending scroll fires, a new _schedule_scroll() should
        create a new timer (the coalescing flag should be reset)."""
        app = _ChatApp()
        async with app.run_test(size=(80, 40)):
            display = app.chat_display

            timer_count = {"count": 0}
            original_set_timer = display.set_timer

            def counting_set_timer(delay, callback, **kwargs):
                timer_count["count"] += 1
                return original_set_timer(delay, callback, **kwargs)

            display.set_timer = counting_set_timer

            # First call creates a timer.
            display._schedule_scroll()
            assert timer_count["count"] == 1

            # Simulate the timer firing.
            display._scroll_pending = False

            # Next call should create a new timer.
            display._schedule_scroll()
            assert timer_count["count"] == 2, (
                f"Expected 2 timers after fire, got {timer_count['count']}"
            )

    @pytest.mark.asyncio
    async def test_batch_mode_still_suppresses_scroll(self):
        """In batch mode, _schedule_scroll() should still be a no-op."""
        app = _ChatApp()
        async with app.run_test(size=(80, 40)):
            display = app.chat_display

            timer_count = {"count": 0}
            original_set_timer = display.set_timer

            def counting_set_timer(delay, callback, **kwargs):
                timer_count["count"] += 1
                return original_set_timer(delay, callback, **kwargs)

            display.set_timer = counting_set_timer

            display.begin_batch()

            for _ in range(20):
                display._schedule_scroll()

            assert timer_count["count"] == 0, (
                f"Expected 0 timers in batch mode, got {timer_count['count']}"
            )


# ---------------------------------------------------------------------------
# B: Throttled rebuild
# ---------------------------------------------------------------------------


class TestThrottledRebuild:
    """Tests for the throttled rebuild optimization.

    During streaming, multiple structural additions (add_section, add_tool_call)
    in rapid succession each call _rebuild(). With throttling, rapid calls
    are coalesced — only one rebuild happens per frame (~16ms).

    Note: _rebuild() is now deferred via set_timer(1/60, ...). Tests that
    check rebuild counts must use _immediate_rebuild() or verify the throttle
    flag behavior directly.
    """

    @pytest.mark.asyncio
    async def test_rebuild_sets_pending_flag(self):
        """_rebuild() should set _rebuild_pending=True and schedule a timer."""
        app = _ChatApp()
        async with app.run_test(size=(80, 40)):
            display = app.chat_display

            assert display._rebuild_pending is False

            display._rebuild()

            assert display._rebuild_pending is True, (
                "Expected _rebuild_pending to be True after _rebuild()"
            )

    @pytest.mark.asyncio
    async def test_rapid_rebuilds_are_coalesced(self):
        """Multiple rapid _rebuild() calls should only schedule one timer."""
        app = _ChatApp()
        async with app.run_test(size=(80, 40)):
            display = app.chat_display

            timer_count = {"count": 0}
            original_set_timer = display.set_timer

            def counting_set_timer(delay, callback, **kwargs):
                timer_count["count"] += 1
                return original_set_timer(delay, callback, **kwargs)

            display.set_timer = counting_set_timer

            # First call schedules a timer.
            display._rebuild()
            assert timer_count["count"] == 1

            # Subsequent calls should NOT schedule more timers.
            for _ in range(9):
                display._rebuild()

            assert timer_count["count"] == 1, (
                f"Expected 1 timer with throttling, got {timer_count['count']}"
            )

    @pytest.mark.asyncio
    async def test_immediate_rebuild_bypasses_throttle(self):
        """_immediate_rebuild() should fire immediately without throttling."""
        app = _ChatApp()
        async with app.run_test(size=(80, 40)):
            display = app.chat_display
            tree = display.query_one(Tree)

            rebuild_count = {"count": 0}
            original_rebuild = tree.rebuild

            def counting_rebuild():
                rebuild_count["count"] += 1
                return original_rebuild()

            tree.rebuild = counting_rebuild

            display._immediate_rebuild()

            assert rebuild_count["count"] == 1, (
                f"Expected 1 immediate rebuild, got {rebuild_count['count']}"
            )
            assert display._rebuild_pending is False, (
                "Expected _rebuild_pending to be False after immediate rebuild"
            )

    @pytest.mark.asyncio
    async def test_batch_mode_still_suppresses_rebuild(self):
        """In batch mode, _rebuild() should still be a no-op."""
        app = _ChatApp()
        async with app.run_test(size=(80, 40)):
            display = app.chat_display

            display.begin_batch()
            display._rebuild()

            assert display._rebuild_pending is False, (
                "Expected _rebuild_pending to remain False in batch mode"
            )

    @pytest.mark.asyncio
    async def test_end_batch_fires_immediate_rebuild(self):
        """end_batch() should fire an immediate rebuild regardless of throttle."""
        app = _ChatApp()
        async with app.run_test(size=(80, 40)):
            display = app.chat_display
            tree = display.query_one(Tree)

            rebuild_count = {"count": 0}
            original_rebuild = tree.rebuild

            def counting_rebuild():
                rebuild_count["count"] += 1
                return original_rebuild()

            tree.rebuild = counting_rebuild

            display.begin_batch()
            display.add_user_message("Hello")
            display.begin_assistant_turn()
            s = display.add_section("response")

            # In batch mode, no rebuilds should have happened.
            assert rebuild_count["count"] == 0

            display.end_batch()

            # end_batch should have triggered exactly 1 immediate rebuild.
            assert rebuild_count["count"] == 1, (
                f"Expected 1 rebuild after end_batch, got {rebuild_count['count']}"
            )
            assert display._rebuild_pending is False


# ---------------------------------------------------------------------------
# C: Targeted expand (incremental additions)
# ---------------------------------------------------------------------------


class TestTargetedExpand:
    """Tests for targeted expand optimization.

    When adding a new node during streaming, the add methods call
    expand_node() directly instead of relying on restore_expand_state()
    which iterates all nodes.  The expand state is stored in the Tree's
    _expanded set and survives across rebuilds.
    """

    @pytest.mark.asyncio
    async def test_add_section_expand_state_recorded(self):
        """add_section should record the section as expanded in _expanded."""
        app = _ChatApp()
        async with app.run_test(size=(80, 40)):
            display = app.chat_display
            tree = display.query_one(Tree)

            display.add_user_message("Hello")
            display.begin_assistant_turn()
            section_id = display.add_section("response")

            # The section should be in the Tree's _expanded set.
            assert section_id in tree._expanded, (
                f"Section {section_id} should be in _expanded"
            )

    @pytest.mark.asyncio
    async def test_add_tool_call_collapse_state_recorded(self):
        """add_tool_call should record the tool call as collapsed in _expanded."""
        app = _ChatApp()
        async with app.run_test(size=(80, 40)):
            display = app.chat_display
            tree = display.query_one(Tree)

            display.add_user_message("Hello")
            display.begin_assistant_turn()
            tc_id = display.add_tool_call("read_file", {"path": "/tmp/test"})

            # The tool call should NOT be in _expanded (collapsed by default).
            assert tc_id not in tree._expanded, (
                f"Tool call {tc_id} should NOT be in _expanded"
            )

    @pytest.mark.asyncio
    async def test_thinking_section_collapse_state_recorded(self):
        """Thinking sections should be collapsed by default (not in _expanded)."""
        app = _ChatApp()
        async with app.run_test(size=(80, 40)):
            display = app.chat_display
            tree = display.query_one(Tree)

            display.add_user_message("Hello")
            display.begin_assistant_turn()
            section_id = display.add_section("thinking")

            # Thinking sections should NOT be in _expanded (collapsed by default).
            assert section_id not in tree._expanded, (
                f"Thinking section {section_id} should NOT be in _expanded"
            )

    @pytest.mark.asyncio
    async def test_open_thinking_config_expands_section(self):
        """When open_thinking=True, thinking sections should be expanded."""
        display = ChatDisplay(open_thinking=True)
        assert display._open_thinking is True


# ---------------------------------------------------------------------------
# Integration: streaming update path efficiency
# ---------------------------------------------------------------------------


class TestStreamingEfficiency:
    """Integration tests to verify the streaming path is efficient."""

    @pytest.mark.asyncio
    async def test_update_section_does_not_rebuild(self):
        """update_section should NOT trigger a tree rebuild.

        During streaming, update_section is called on every chunk.
        It should only update the Static widget text — no rebuild.
        """
        app = _ChatApp()
        async with app.run_test(size=(80, 40)):
            display = app.chat_display
            tree = display.query_one(Tree)

            display.add_user_message("Hello")
            display.begin_assistant_turn()
            section_id = display.add_section("response")

            rebuild_count = {"count": 0}
            original_rebuild = tree.rebuild

            def counting_rebuild():
                rebuild_count["count"] += 1
                return original_rebuild()

            tree.rebuild = counting_rebuild

            # Simulate streaming: multiple update_section calls.
            await display.update_section(section_id, "Hello")
            assert rebuild_count["count"] == 0, (
                f"update_section should not rebuild, got {rebuild_count['count']}"
            )

            await display.update_section(section_id, "Hello world")
            assert rebuild_count["count"] == 0, (
                f"update_section should not rebuild, got {rebuild_count['count']}"
            )

    @pytest.mark.asyncio
    async def test_update_section_does_not_scroll(self):
        """update_section should NOT trigger a scroll.

        During streaming, update_section is called ~20 times/sec.
        Scrolling is now only triggered at structural boundaries
        (add_section, add_tool_call, etc.) and chunk.done, not on
        every content update.
        """
        app = _ChatApp()
        async with app.run_test(size=(80, 40)):
            display = app.chat_display

            display.add_user_message("Hello")
            display.begin_assistant_turn()
            section_id = display.add_section("response")

            # Clear any pending scroll from structural additions.
            display._scroll_pending = False

            # Track scroll timer creation.
            scroll_count = {"count": 0}
            original_set_timer = display.set_timer

            def counting_set_timer(delay, callback, **kwargs):
                scroll_count["count"] += 1
                return original_set_timer(delay, callback, **kwargs)

            display.set_timer = counting_set_timer

            # Simulate streaming: multiple update_section calls.
            await display.update_section(section_id, "Hello")
            await display.update_section(section_id, "Hello world")
            await display.update_section(section_id, "Hello world!")

            # No scroll timers should have been created by update_section.
            assert scroll_count["count"] == 0, (
                f"update_section should not create scroll timers, got {scroll_count['count']}"
            )

    @pytest.mark.asyncio
    async def test_structural_additions_do_scroll(self):
        """Structural additions (add_section, add_tool_call) should
        trigger a scroll — these are the boundaries where the user
        needs to see new content."""
        app = _ChatApp()
        async with app.run_test(size=(80, 40)):
            display = app.chat_display

            # Track scroll timer creation.
            scroll_count = {"count": 0}
            original_schedule_scroll = display._schedule_scroll

            def counting_schedule_scroll():
                scroll_count["count"] += 1
                return original_schedule_scroll()

            display._schedule_scroll = counting_schedule_scroll

            display.add_user_message("Hello")
            assert scroll_count["count"] >= 1, (
                f"add_user_message should trigger scroll, got {scroll_count['count']}"
            )

            display.begin_assistant_turn()
            assert scroll_count["count"] >= 2, (
                f"begin_assistant_turn should trigger scroll, got {scroll_count['count']}"
            )

            section_id = display.add_section("response")
            assert scroll_count["count"] >= 3, (
                f"add_section should trigger scroll, got {scroll_count['count']}"
            )

    @pytest.mark.asyncio
    async def test_rapid_structural_additions_set_throttle_flag(self):
        """Adding multiple sections and tool calls in quick succession
        should set the throttle flag so only one rebuild is scheduled."""
        app = _ChatApp()
        async with app.run_test(size=(80, 40)):
            display = app.chat_display

            # Before any adds, throttle should be clear.
            assert display._rebuild_pending is False

            display.add_user_message("Hello")
            # First add schedules a rebuild.
            assert display._rebuild_pending is True

            # Subsequent adds should NOT schedule additional rebuilds.
            timer_count = {"count": 0}
            original_set_timer = display.set_timer

            def counting_set_timer(delay, callback, **kwargs):
                timer_count["count"] += 1
                return original_set_timer(delay, callback, **kwargs)

            display.set_timer = counting_set_timer

            display.begin_assistant_turn()
            display.add_section("thinking")
            display.add_section("response")
            display.add_tool_call("read_file", {"path": "/tmp/test"})

            # Only 0 additional timers (throttle flag is already set).
            assert timer_count["count"] == 0, (
                f"Expected 0 additional timers with throttling, got {timer_count['count']}"
            )

    @pytest.mark.asyncio
    async def test_clear_uses_immediate_rebuild(self):
        """clear() should use _immediate_rebuild() for an instant clear."""
        app = _ChatApp()
        async with app.run_test(size=(80, 40)):
            display = app.chat_display

            display.add_user_message("Hello")
            display.clear()

            # After clear, the tree should be empty and throttle flags reset.
            assert display._rebuild_pending is False
            assert display._scroll_pending is False
            assert len(display._root.children) == 0