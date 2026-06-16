"""Tests for streaming crash prevention and stream preservation across recomposition.

Verifies:
1. ChatManager.on_unmount/on_remove detach display without cancelling stream
2. ChatManager._cancel_streaming() cancels stream via StreamManager on user abort
3. ChatManager._detach_display() marks display detached, cancels local worker
4. ChatDisplay guards skip DOM operations when _detached=True
5. StreamManager start/subscribe/cancel lifecycle
6. Stream preservation across recomposition
"""

from __future__ import annotations

import asyncio
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from textual.app import App, ComposeResult
from textual.containers import Container

from core.paths import collect_tcss
from core.stream_manager import StreamManager, StreamChunk
from core.providers.base import ToolCall
from skills.chat.chat_display import ChatDisplay
from skills.chat.chat_manager import ChatManager
from skills.chat.chat_input import ChatInput


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# A: ChatManager lifecycle — detach vs cancel
# ---------------------------------------------------------------------------


class TestChatManagerDetach:
	"""Tests for ChatManager detaching display on unmount/remove (NOT cancelling stream)."""

	@pytest.mark.asyncio
	async def test_on_unmount_detaches_display(self):
		"""on_unmount() should detach the display without cancelling the stream."""
		app = _ChatManagerApp()
		async with app.run_test(size=(80, 40)):
			manager = app.chat_manager
			manager._streaming = True

			manager.on_unmount()

			# Display should be detached.
			assert manager._chat_display._detached is True
			# Streaming flag should still be True — stream continues in StreamManager.
			assert manager._streaming is True

	@pytest.mark.asyncio
	async def test_on_remove_detaches_display(self):
		"""on_remove() should detach the display without cancelling the stream."""
		app = _ChatManagerApp()
		async with app.run_test(size=(80, 40)):
			manager = app.chat_manager
			manager._streaming = True

			manager.on_remove()

			assert manager._chat_display._detached is True
			assert manager._streaming is True

	@pytest.mark.asyncio
	async def test_detach_display_cancels_local_worker(self):
		"""_detach_display() should cancel the local chunk-processing worker."""
		app = _ChatManagerApp()
		async with app.run_test(size=(80, 40)):
			manager = app.chat_manager

			async def _long_running():
				await asyncio.sleep(100)

			worker = manager.run_worker(_long_running())
			manager._streaming_task = worker

			manager._detach_display()

			# The local worker should be cancelled.
			assert worker.is_finished or worker._cancelled

	def test_detach_display_marks_display_detached(self):
		"""_detach_display() should set _detached on the ChatDisplay."""
		manager = ChatManager()
		display = ChatDisplay()
		manager._chat_display = display

		manager._detach_display()

		assert display._detached is True

	def test_detach_display_handles_none_display(self):
		"""_detach_display() should not crash if _chat_display is None."""
		manager = ChatManager()
		manager._chat_display = None

		# Should not raise.
		manager._detach_display()

	def test_cancel_streaming_uses_stream_manager(self):
		"""_cancel_streaming() should cancel via StreamManager."""
		manager = ChatManager()
		manager._streaming = True
		manager._stream_id = "test-stream-id"
		manager._chat_display = ChatDisplay()

		# Mock the context and stream manager.
		mock_sm = MagicMock()
		mock_ctx = MagicMock()
		mock_ctx.stream_manager = mock_sm

		manager._get_context = lambda: mock_ctx

		manager._cancel_streaming()

		# Should have cancelled the stream via StreamManager.
		mock_sm.cancel.assert_called_once_with("test-stream-id")
		assert manager._stream_id is None
		assert manager._streaming is False

	def test_cancel_streaming_resets_state(self):
		"""_cancel_streaming() should reset streaming state."""
		manager = ChatManager()
		manager._streaming = True
		manager._stream_id = "test-stream-id"
		manager._chat_display = ChatDisplay()

		# Mock _get_context to return None (no stream manager).
		manager._get_context = lambda: None

		manager._cancel_streaming()

		assert manager._streaming is False
		assert manager._stream_id is None
		assert manager._chat_display._detached is True


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
# D: StreamManager lifecycle
# ---------------------------------------------------------------------------


class TestStreamManager:
	"""Tests for StreamManager start/subscribe/cancel lifecycle."""

	@pytest.mark.asyncio
	async def test_start_returns_stream_id(self):
		"""start() should return a valid stream ID."""
		sm = StreamManager()
		mock_agent = MagicMock()
		mock_agent.stream_chat = MagicMock()
		# Make stream_chat return an async generator that yields nothing.
		async def _empty_stream(*args, **kwargs):
			return
			yield  # Make it an async generator

		mock_agent.stream_chat = _empty_stream

		stream_id = sm.start(mock_agent, [], "hello")
		assert stream_id is not None
		assert len(stream_id) > 0

	@pytest.mark.asyncio
	async def test_start_creates_background_task(self):
		"""start() should create a background task that runs the stream."""
		sm = StreamManager()
		mock_agent = MagicMock()

		async def _simple_stream(*args, **kwargs):
			yield StreamChunk(content="hello", thinking="", tool_calls=[], tool_results={}, done=True, usage=None)

		mock_agent.stream_chat = _simple_stream
		stream_id = sm.start(mock_agent, [], "hello")

		assert sm.has_stream(stream_id)
		await asyncio.sleep(0.1)  # Let the stream complete

	@pytest.mark.asyncio
	async def test_stream_writes_response_to_db(self):
		"""start() should write accumulated response text to the database."""
		sm = StreamManager()
		mock_agent = MagicMock()

		async def _simple_stream(*args, **kwargs):
			yield StreamChunk(content="hello ", thinking="", tool_calls=[], tool_results={}, done=False, usage=None)
			yield StreamChunk(content="world", thinking="", tool_calls=[], tool_results={}, done=True, usage=None)

		mock_agent.stream_chat = _simple_stream

		from core.database import DatabaseManager
		db = DatabaseManager(":memory:")
		chat_id = db.create_chat()
		turn_id = "turn-123"

		stream_id = sm.start(
			mock_agent, [], "hello",
			db=db, chat_id=chat_id, turn_id=turn_id,
		)
		assert sm.has_stream(stream_id)

		await asyncio.sleep(0.3)  # Let the stream complete and flush

		sections = db.load_sections(chat_id)
		response_rows = [s for s in sections if s["content_type"] == "response"]
		assert len(response_rows) == 1
		assert response_rows[0]["content"] == "hello world"

	@pytest.mark.asyncio
	async def test_stream_writes_thinking_to_db(self):
		"""start() should write accumulated thinking text to the database."""
		sm = StreamManager()
		mock_agent = MagicMock()

		async def _thinking_stream(*args, **kwargs):
			yield StreamChunk(content="answer", thinking="hmm", tool_calls=[], tool_results={}, done=True, usage=None)

		mock_agent.stream_chat = _thinking_stream

		from core.database import DatabaseManager
		db = DatabaseManager(":memory:")
		chat_id = db.create_chat()
		turn_id = "turn-123"

		stream_id = sm.start(
			mock_agent, [], "hello",
			db=db, chat_id=chat_id, turn_id=turn_id,
		)
		await asyncio.sleep(0.3)

		sections = db.load_sections(chat_id)
		thinking_rows = [s for s in sections if s["content_type"] == "thinking"]
		assert len(thinking_rows) == 1
		assert thinking_rows[0]["content"] == "hmm"

	@pytest.mark.asyncio
	async def test_stream_writes_tool_call_to_db(self):
		"""start() should write tool calls to the database."""
		sm = StreamManager()
		mock_agent = MagicMock()

		async def _tool_stream(*args, **kwargs):
			yield StreamChunk(
				content="",
				thinking="",
				tool_calls=[ToolCall(id="tc-1", name="read_file", arguments={"path": "/tmp/test"})],
				tool_results={},
				done=True,
				usage=None,
			)

		mock_agent.stream_chat = _tool_stream

		from core.database import DatabaseManager
		db = DatabaseManager(":memory:")
		chat_id = db.create_chat()
		turn_id = "turn-123"

		stream_id = sm.start(
			mock_agent, [], "hello",
			db=db, chat_id=chat_id, turn_id=turn_id,
		)
		await asyncio.sleep(0.3)

		sections = db.load_sections(chat_id)
		tool_rows = [s for s in sections if s["content_type"] == "tool_call"]
		assert len(tool_rows) == 1
		assert "read_file" in tool_rows[0]["content"]

	@pytest.mark.asyncio
	async def test_stream_writes_tool_result_to_db(self):
		"""start() should merge tool results into tool_call rows."""
		sm = StreamManager()
		mock_agent = MagicMock()

		async def _tool_stream(*args, **kwargs):
			yield StreamChunk(
				content="",
				thinking="",
				tool_calls=[ToolCall(id="tc-1", name="read_file", arguments={"path": "/tmp/test"})],
				tool_results={},
				done=False,
				usage=None,
			)
			yield StreamChunk(
				content="done",
				thinking="",
				tool_calls=[],
				tool_results={"tc-1": "file contents"},
				done=True,
				usage=None,
			)

		mock_agent.stream_chat = _tool_stream

		from core.database import DatabaseManager
		db = DatabaseManager(":memory:")
		chat_id = db.create_chat()
		turn_id = "turn-123"

		stream_id = sm.start(
			mock_agent, [], "hello",
			db=db, chat_id=chat_id, turn_id=turn_id,
		)
		await asyncio.sleep(0.3)

		sections = db.load_sections(chat_id)
		tool_rows = [s for s in sections if s["content_type"] == "tool_call"]
		assert len(tool_rows) == 1
		assert "file contents" in tool_rows[0]["content"]

	@pytest.mark.asyncio
	async def test_cancel_stops_stream(self):
		"""cancel() should abort the agent and remove the stream."""
		sm = StreamManager()

		async def _long_stream(*args, **kwargs):
			for i in range(100):
				yield StreamChunk(content=f"chunk {i}", thinking="", tool_calls=[], tool_results={}, done=False, usage=None)
				yield StreamChunk(content="", thinking="", tool_calls=[], tool_results={}, done=True, usage=None)

		mock_agent = MagicMock()
		mock_agent.stream_chat = _long_stream
		mock_agent.abort = MagicMock()

		stream_id = sm.start(mock_agent, [], "hello")
		assert sm.has_stream(stream_id)

		sm.cancel(stream_id)
		assert not sm.has_stream(stream_id)
		mock_agent.abort.assert_called_once()

	@pytest.mark.asyncio
	async def test_finished_stream_not_has_stream(self):
		"""has_stream() should return False after a stream completes."""
		sm = StreamManager()

		async def _quick_stream(*args, **kwargs):
			yield StreamChunk(content="done", thinking="", tool_calls=[], tool_results={}, done=True, usage=None)

		mock_agent = MagicMock()
		mock_agent.stream_chat = _quick_stream
		stream_id = sm.start(mock_agent, [], "hello")

		await asyncio.sleep(0.2)
		assert not sm.has_stream(stream_id)

	def test_has_stream_unknown_id(self):
		"""has_stream() with unknown ID should return False."""
		sm = StreamManager()
		assert sm.has_stream("nonexistent") is False


# ---------------------------------------------------------------------------
# E: ChatTabState stream ID preservation
# ---------------------------------------------------------------------------


class TestChatTabState:
	"""Tests for ChatTabState storing stream ID and cancelling on dispose."""

	def test_tab_state_has_stream_id(self):
		"""ChatTabState should have a _stream_id field."""
		from skills.chat.chat_tab import ChatTabState
		state = ChatTabState()
		assert hasattr(state, '_stream_id')
		assert state._stream_id is None

	def test_tab_state_dispose_cancels_stream(self):
		"""ChatTabState.dispose() should cancel the stream via StreamManager."""
		from skills.chat.chat_tab import ChatTabState
		state = ChatTabState()
		state._stream_id = "test-stream-id"

		mock_sm = MagicMock()
		mock_ctx = MagicMock()
		mock_ctx.stream_manager = mock_sm
		state._ctx = mock_ctx

		state.dispose()

		mock_sm.cancel.assert_called_once_with("test-stream-id")
		assert state._stream_id is None

	def test_tab_state_dispose_handles_no_stream(self):
		"""ChatTabState.dispose() should handle no stream ID gracefully."""
		from skills.chat.chat_tab import ChatTabState
		state = ChatTabState()
		state._stream_id = None
		# Should not raise.
		state.dispose()


# ---------------------------------------------------------------------------
# F: Streaming graceful exit
# ---------------------------------------------------------------------------


class TestStreamingGracefulExit:
	"""Tests for the streaming loop exiting gracefully when detached."""

	@pytest.mark.asyncio
	async def test_sync_conversation_returns_when_no_db(self):
		"""_sync_conversation should return early if no DB or chat_id."""
		manager = ChatManager()
		manager._state = MagicMock()

		# No DB and no chat_id — should return without error.
		await manager._sync_conversation(finalize=True)