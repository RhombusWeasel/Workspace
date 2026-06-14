"""Tests for the streaming crash fix — workspace split/close during streaming.

Verifies:
1. ChatManager.on_unmount() cancels the streaming task
2. ChatManager._cancel_streaming() cleans up streaming state
3. ChatDisplay._detached flag prevents DOM operations after unmount
4. StreamSection guards bail out when display is detached
5. Streaming loop exits gracefully when widget is detached
"""

from __future__ import annotations

import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from textual.app import App, ComposeResult
from textual.containers import Container

from core.paths import collect_tcss
from skills.chat.chat_display import ChatDisplay
from skills.chat.chat_manager import ChatManager
from skills.chat.chat_input import ChatInput
from skills.chat.stream_section import StreamSection


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _ChatManagerApp(App):
	"""Minimal app that mounts a ChatManager for testing."""
	CSS_PATH = collect_tcss(
		os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
	)

	def __init__(self, **kwargs):
		super().__init__(**kwargs)
		self.chat_manager = ChatManager()

	def compose(self) -> ComposeResult:
		yield Container(self.chat_manager)


class _ChatDisplayApp(App):
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
# A: ChatManager lifecycle cancellation
# ---------------------------------------------------------------------------


class TestChatManagerUnmount:
	"""Tests for ChatManager cancelling streaming on widget removal."""

	def test_cancel_streaming_resets_flag(self):
		"""_cancel_streaming() should set _streaming to False."""
		manager = ChatManager()
		manager._streaming = True
		manager._streaming_task = None
		manager._agent = None
		manager._chat_display = ChatDisplay()

		manager._cancel_streaming()

		assert manager._streaming is False, (
			"Expected _streaming to be False after _cancel_streaming()"
		)

	def test_cancel_streaming_sets_display_detached(self):
		"""_cancel_streaming() should set _detached on the ChatDisplay."""
		manager = ChatManager()
		manager._streaming = True
		manager._streaming_task = None
		manager._agent = None
		display = ChatDisplay()
		manager._chat_display = display

		manager._cancel_streaming()

		assert display._detached is True, (
			"Expected _detached to be True on ChatDisplay after _cancel_streaming()"
		)

	@pytest.mark.asyncio
	async def test_on_unmount_cancels_streaming_task(self):
		"""on_unmount() should cancel an active streaming task."""
		app = _ChatManagerApp()
		async with app.run_test(size=(80, 40)):
			manager = app.chat_manager

			# Create a mock streaming task that we can track.
			task_was_cancelled = {"value": False}
			original_cancel = None

			# Create a mock agent that we can abort.
			mock_agent = MagicMock()
			mock_agent.abort = MagicMock()
			manager._agent = mock_agent

			# Set up a mock streaming task.
			async def _long_running():
				await asyncio.sleep(100)

			worker = manager.run_worker(_long_running())
			manager._streaming_task = worker
			manager._streaming = True

			# Call on_unmount — should cancel the task.
			manager.on_unmount()

			# The streaming flag should be reset.
			assert manager._streaming is False, (
				"Expected _streaming to be False after on_unmount()"
			)

			# The agent should have been aborted.
			mock_agent.abort.assert_called_once()

	@pytest.mark.asyncio
	async def test_on_remove_cancels_streaming(self):
		"""on_remove() should also cancel streaming (belt-and-suspenders)."""
		app = _ChatManagerApp()
		async with app.run_test(size=(80, 40)):
			manager = app.chat_manager

			mock_agent = MagicMock()
			mock_agent.abort = MagicMock()
			manager._agent = mock_agent

			async def _long_running():
				await asyncio.sleep(100)

			worker = manager.run_worker(_long_running())
			manager._streaming_task = worker
			manager._streaming = True

			manager.on_remove()

			assert manager._streaming is False, (
				"Expected _streaming to be False after on_remove()"
			)
			mock_agent.abort.assert_called_once()

	def test_cancel_streaming_idempotent(self):
		"""_cancel_streaming() should be safe to call multiple times."""
		manager = ChatManager()
		manager._streaming = True
		manager._streaming_task = None
		manager._agent = None
		display = ChatDisplay()
		manager._chat_display = display

		manager._cancel_streaming()
		manager._cancel_streaming()  # Second call should be a no-op.

		assert manager._streaming is False
		assert display._detached is True

	def test_cancel_streaming_no_display(self):
		"""_cancel_streaming() should not crash if _chat_display is None."""
		manager = ChatManager()
		manager._streaming = True
		manager._streaming_task = None
		manager._agent = None
		manager._chat_display = None

		# Should not raise an exception.
		manager._cancel_streaming()
		assert manager._streaming is False


# ---------------------------------------------------------------------------
# B: ChatDisplay _detached flag
# ---------------------------------------------------------------------------


class TestChatDisplayDetached:
	"""Tests for ChatDisplay._detached flag preventing DOM operations."""

	@pytest.mark.asyncio
	async def test_update_section_returns_early_when_detached(self):
		"""update_section() should return early if _detached is True."""
		app = _ChatDisplayApp()
		async with app.run_test(size=(80, 40)):
			display = app.chat_display
			display._detached = True

			# Should not raise — just return silently.
			await display.update_section("nonexistent", "text")

	@pytest.mark.asyncio
	async def test_add_user_message_returns_early_when_detached(self):
		"""add_user_message() should return a placeholder ID when detached."""
		display = ChatDisplay()
		display._detached = True

		msg_id = display.add_user_message("Hello")
		# Should still return an ID, just not do DOM operations.
		assert msg_id is not None
		assert "detached" not in msg_id or "user" in msg_id  # Placeholder ID

	@pytest.mark.asyncio
	async def test_add_section_returns_early_when_detached(self):
		"""add_section() should return a section ID when detached, skipping DOM."""
		display = ChatDisplay()
		display._detached = True
		display._turn_count = 1
		display._active_asst_id = "asst-1"
		display._turn_map["asst-1"] = None

		section_id = display.add_section("response")
		assert section_id is not None
		assert "response" in section_id

	@pytest.mark.asyncio
	async def test_finalize_turn_returns_early_when_detached(self):
		"""finalize_turn() should return early when detached, just clearing state."""
		display = ChatDisplay()
		display._detached = True
		display._active_asst_id = "asst-1"
		display._section_widgets = {"s1": "widget"}
		display._section_texts = {"s1": "text"}
		display._section_types = {"s1": "response"}

		# Should not raise.
		await display.finalize_turn()

		# Should have cleared state.
		assert display._active_asst_id is None
		assert display._section_widgets == {}
		assert display._section_texts == {}
		assert display._section_types == {}

	@pytest.mark.asyncio
	async def test_schedule_scroll_returns_early_when_detached(self):
		"""_schedule_scroll() should not set a timer when detached."""
		app = _ChatDisplayApp()
		async with app.run_test(size=(80, 40)):
			display = app.chat_display
			display._detached = True

			timer_count = {"count": 0}
			original_set_timer = display.set_timer

			def counting_set_timer(delay, callback, **kwargs):
				timer_count["count"] += 1
				return original_set_timer(delay, callback, **kwargs)

			display.set_timer = counting_set_timer
			display._schedule_scroll()

			assert timer_count["count"] == 0, (
				f"Expected 0 timers when detached, got {timer_count['count']}"
			)

	@pytest.mark.asyncio
	async def test_add_tool_call_returns_early_when_detached(self):
		"""add_tool_call() should return a tc_id when detached, skipping DOM."""
		display = ChatDisplay()
		display._detached = True
		display._active_asst_id = "asst-1"
		display._turn_map["asst-1"] = None
		display._turn_count = 1

		tc_id = display.add_tool_call("read_file", {"path": "/tmp/test"})
		assert tc_id is not None
		assert "tc" in tc_id

	@pytest.mark.asyncio
	async def test_add_tool_result_returns_early_when_detached(self):
		"""add_tool_result() should return early when detached."""
		display = ChatDisplay()
		display._detached = True

		# Should not raise — just return.
		display.add_tool_result("tc-1", "result text")


# ---------------------------------------------------------------------------
# C: StreamSection guards
# ---------------------------------------------------------------------------


class TestStreamSectionDetached:
	"""Tests for StreamSection bailing out when display is detached."""

	@pytest.mark.asyncio
	async def test_append_skips_update_when_detached(self):
		"""StreamSection.append() should skip display update when detached."""
		app = _ChatDisplayApp()
		async with app.run_test(size=(80, 40)):
			display = app.chat_display
			display._detached = True

			# Need an active turn for add_section to work.
			display._turn_count = 0
			display._active_asst_id = "asst-1"
			display._turn_map["asst-1"] = None

			# Create a StreamSection — add_section returns an ID but
			# doesn't mount anything since we're detached.
			section = StreamSection(display, "response")

			# Append should not raise and should accumulate text.
			await section.append("Hello")
			assert section.text == "Hello", (
				f"Expected text to be 'Hello', got '{section.text}'"
			)

	@pytest.mark.asyncio
	async def test_replace_skips_update_when_detached(self):
		"""StreamSection.replace() should skip display update when detached."""
		app = _ChatDisplayApp()
		async with app.run_test(size=(80, 40)):
			display = app.chat_display
			display._detached = True

			# Need an active turn for add_section to work even when detached.
			display._turn_count = 0
			display._active_asst_id = "asst-1"
			display._turn_map["asst-1"] = None

			section = StreamSection(display, "response")

			# Replace should not raise.
			await section.replace("Replaced text")
			assert section.text == "Replaced text", (
				f"Expected text to be 'Replaced text', got '{section.text}'"
			)

	@pytest.mark.asyncio
	async def test_flush_skips_update_when_detached(self):
		"""StreamSection.flush() should skip display update when detached."""
		app = _ChatDisplayApp()
		async with app.run_test(size=(80, 40)):
			display = app.chat_display
			display._detached = True

			# Need an active turn for add_section to work even when detached.
			display._turn_count = 0
			display._active_asst_id = "asst-1"
			display._turn_map["asst-1"] = None

			section = StreamSection(display, "response")
			await section.append("Hello")

			# Flush should not raise.
			await section.flush()

			assert section.text == "Hello"


# ---------------------------------------------------------------------------
# D: Streaming loop graceful exit
# ---------------------------------------------------------------------------


class TestStreamingGracefulExit:
	"""Tests for the streaming loop exiting gracefully when detached."""

	@pytest.mark.asyncio
	async def test_rebuild_display_bails_out_when_not_mounted(self):
		"""_rebuild_display_from_sections should return early if not mounted."""
		manager = ChatManager()
		manager._sections = [
			{"turn_id": "t1", "content_type": "user", "content": "hello"},
		]
		manager._state = MagicMock()

		# is_mounted will be False since we're not inside an app.
		# This should return without error.
		await manager._rebuild_display_from_sections()

	def test_cancel_streaming_with_finished_task(self):
		"""_cancel_streaming() should handle a finished task gracefully."""
		manager = ChatManager()
		manager._streaming = True
		manager._agent = MagicMock()
		manager._chat_display = ChatDisplay()

		# Create a mock finished task.
		mock_task = MagicMock()
		mock_task.is_finished = True
		manager._streaming_task = mock_task

		manager._cancel_streaming()

		# Should not have called abort since task was already finished.
		manager._agent.abort.assert_not_called()
		assert manager._streaming is False

	def test_cancel_streaming_with_running_task(self):
		"""_cancel_streaming() should cancel a running streaming task."""
		manager = ChatManager()
		manager._streaming = True
		manager._agent = MagicMock()
		manager._chat_display = ChatDisplay()

		# Create a mock running task.
		mock_task = MagicMock()
		mock_task.is_finished = False
		manager._streaming_task = mock_task

		manager._cancel_streaming()

		# Should have called abort on the agent and cancel on the task.
		manager._agent.abort.assert_called_once()
		mock_task.cancel.assert_called_once()
		assert manager._streaming is False