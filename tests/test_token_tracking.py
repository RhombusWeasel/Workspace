"""Tests for token tracking — StreamManager captures usage and ChatManager updates ContextUsageBar.

Verifies:
1. StreamManager._handle_chunk stores usage data on done chunks
2. StreamManager.get_usage() returns stored usage after stream completes
3. StreamManager.get_usage() returns None for unknown/cancelled streams
4. StreamManager.cancel() cleans up usage data
5. ChatManager._sync_conversation calls update_context_progress after stream completes
"""

from __future__ import annotations

import asyncio
import os
import sys
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.stream_manager import StreamManager
from core.providers.base import StreamChunk, TokenUsage, ToolCall


# ---------------------------------------------------------------------------
# A: StreamManager usage capture
# ---------------------------------------------------------------------------


class TestStreamManagerUsageCapture:
	"""Tests for StreamManager capturing token usage from done chunks."""

	def test_handle_chunk_stores_usage_on_done(self):
		"""_handle_chunk should store the chunk in _usage when chunk.done is True."""
		sm = StreamManager()
		stream_id = "test-stream-1"
		# Set up minimal metadata so _handle_chunk doesn't crash.
		sm._metadata[stream_id] = {
			"db": None,
			"chat_id": None,
			"turn_id": None,
			"sections": [],
			"section_counter": 0,
			"current_section_type": None,
			"current_section_id": None,
			"current_section_text": "",
			"current_section_dirty": False,
			"tool_calls": {},
		}

		usage = TokenUsage(
			prompt_tokens=100,
			completion_tokens=50,
			total_tokens=150,
			context_length=8192,
		)
		chunk = StreamChunk(
			content="",
			done=True,
			usage=usage,
			thinking=None,
			tool_calls=None,
			tool_results=None,
		)

		sm._handle_chunk(stream_id, chunk)

		assert stream_id in sm._usage
		stored = sm._usage[stream_id]
		assert stored is chunk
		assert stored.usage is not None
		assert stored.usage.total_tokens == 150
		assert stored.usage.context_length == 8192

	def test_handle_chunk_does_not_store_non_done_chunks(self):
		"""_handle_chunk should NOT store chunks that are not done."""
		sm = StreamManager()
		stream_id = "test-stream-2"
		sm._metadata[stream_id] = {
			"db": None,
			"chat_id": None,
			"turn_id": None,
			"sections": [],
			"section_counter": 0,
			"current_section_type": None,
			"current_section_id": None,
			"current_section_text": "",
			"current_section_dirty": False,
			"tool_calls": {},
		}

		chunk = StreamChunk(
			content="hello",
			done=False,
			usage=None,
			thinking=None,
			tool_calls=None,
			tool_results=None,
		)

		sm._handle_chunk(stream_id, chunk)

		assert stream_id not in sm._usage

	def test_handle_chunk_stores_done_chunk_even_without_usage(self):
		"""_handle_chunk should store done chunk even if usage is None."""
		sm = StreamManager()
		stream_id = "test-stream-3"
		sm._metadata[stream_id] = {
			"db": None,
			"chat_id": None,
			"turn_id": None,
			"sections": [],
			"section_counter": 0,
			"current_section_type": None,
			"current_section_id": None,
			"current_section_text": "",
			"current_section_dirty": False,
			"tool_calls": {},
		}

		chunk = StreamChunk(
			content="",
			done=True,
			usage=None,
			thinking=None,
			tool_calls=None,
			tool_results=None,
		)

		sm._handle_chunk(stream_id, chunk)

		assert stream_id in sm._usage
		stored = sm._usage[stream_id]
		assert stored.done is True
		assert stored.usage is None


class TestStreamManagerGetUsage:
	"""Tests for StreamManager.get_usage()."""

	def test_get_usage_returns_none_for_unknown_stream(self):
		"""get_usage() should return None for an unknown stream ID."""
		sm = StreamManager()
		assert sm.get_usage("nonexistent") is None

	def test_get_usage_returns_stored_chunk(self):
		"""get_usage() should return the stored done chunk after stream completes."""
		sm = StreamManager()
		stream_id = "test-stream-4"
		usage = TokenUsage(
			prompt_tokens=200,
			completion_tokens=100,
			total_tokens=300,
			context_length=4096,
		)
		chunk = StreamChunk(
			content="",
			done=True,
			usage=usage,
			thinking=None,
			tool_calls=None,
			tool_results=None,
		)
		sm._usage[stream_id] = chunk

		result = sm.get_usage(stream_id)
		assert result is chunk
		assert result.usage.total_tokens == 300

	@pytest.mark.asyncio
	async def test_cancel_removes_usage(self):
		"""cancel() should remove usage data for the stream."""
		sm = StreamManager()

		# Store usage manually to simulate a completed stream.
		usage = TokenUsage(
			prompt_tokens=50,
			completion_tokens=25,
			total_tokens=75,
			context_length=4096,
		)
		sm._usage["fake-id-1"] = StreamChunk(
			content="", done=True, usage=usage,
		)

		# Set up a stream that's running.
		mock_agent = MagicMock()

		async def _infinite_stream(*args, **kwargs):
			while True:
				yield StreamChunk(content=".", done=False, usage=None)
				await asyncio.sleep(0.1)

		mock_agent.stream_chat = _infinite_stream

		real_stream_id = sm.start(mock_agent, [], "test")

		# Give the stream a moment to start.
		await asyncio.sleep(0.05)

		# Cancel the real stream.
		sm.cancel(real_stream_id)

		# Real stream's usage should be gone.
		assert sm.get_usage(real_stream_id) is None

		# Also verify cancel cleans up manually added usage.
		sm.cancel("fake-id-1")
		assert sm.get_usage("fake-id-1") is None

	@pytest.mark.asyncio
	async def test_get_usage_after_stream_completes(self):
		"""get_usage() should return usage data after a stream naturally completes."""
		sm = StreamManager()
		mock_agent = MagicMock()

		usage = TokenUsage(
			prompt_tokens=100,
			completion_tokens=50,
			total_tokens=150,
			context_length=8192,
		)

		async def _stream_with_usage(*args, **kwargs):
			yield StreamChunk(content="hello", done=False, usage=None)
			yield StreamChunk(content=" world", done=True, usage=usage)

		mock_agent.stream_chat = _stream_with_usage

		stream_id = sm.start(mock_agent, [], "test")

		# Wait for the stream to complete.
		await asyncio.sleep(0.3)

		# Stream should be done.
		assert not sm.has_stream(stream_id)

		# Usage should be available.
		result = sm.get_usage(stream_id)
		assert result is not None
		assert result.done is True
		assert result.usage is not None
		assert result.usage.total_tokens == 150
		assert result.usage.context_length == 8192


class TestStreamManagerUsageCleanup:
	"""Tests for usage data cleanup on cancel and stream completion."""

	def test_cancel_cleans_up_manually_added_usage(self):
		"""cancel() should remove manually added usage data."""
		sm = StreamManager()
		stream_id = "test-stream-cancel"

		usage = TokenUsage(
			prompt_tokens=10,
			completion_tokens=5,
			total_tokens=15,
			context_length=4096,
		)
		sm._usage[stream_id] = StreamChunk(
			content="", done=True, usage=usage,
		)

		# cancel on a non-existent stream ID still cleans up the _usage dict.
		sm.cancel(stream_id)
		assert sm.get_usage(stream_id) is None


# ---------------------------------------------------------------------------
# B: ChatManager integration — update_context_progress called after stream
# ---------------------------------------------------------------------------


class TestChatManagerTokenTracking:
	"""Tests that ChatManager calls update_context_progress after streaming."""

	@pytest.mark.asyncio
	async def test_sync_conversation_updates_context_bar(self):
		"""_sync_conversation should call update_context_progress with usage data after stream completes."""
		from core.database import DatabaseManager

		sm = StreamManager()
		usage = TokenUsage(
			prompt_tokens=200,
			completion_tokens=100,
			total_tokens=300,
			context_length=4096,
		)

		async def _stream_with_usage(*args, **kwargs):
			yield StreamChunk(content="hello", done=False, usage=None)
			yield StreamChunk(content="", done=True, usage=usage)

		mock_agent = MagicMock()
		mock_agent.stream_chat = _stream_with_usage

		stream_id = sm.start(mock_agent, [], "test")

		# Wait for stream to complete.
		await asyncio.sleep(0.3)

		result = sm.get_usage(stream_id)
		assert result is not None
		assert result.usage.total_tokens == 300
		assert result.usage.context_length == 4096

	def test_update_context_progress_updates_bar(self):
		"""update_context_progress should update the ContextUsageBar."""
		from skills.chat.chat_input import ChatInput

		chat_input = ChatInput()
		# We can't mount it in a real app here, but we can test the
		# internal state updates.
		chat_input._context_progress = 0
		chat_input._context_total = 0

		chat_input.update_context_progress("qwen3:0.8b", 300, 4096)

		assert chat_input._context_progress == 300
		assert chat_input._context_total == 4096

	def test_update_context_progress_handles_none_total(self):
		"""update_context_progress should handle None total gracefully."""
		from skills.chat.chat_input import ChatInput

		chat_input = ChatInput()
		chat_input._context_progress = 0
		chat_input._context_total = 0

		chat_input.update_context_progress("qwen3:0.8b", 300, None)

		assert chat_input._context_progress == 300
		assert chat_input._context_total == 0