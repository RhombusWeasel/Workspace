"""Tests for StreamManager section sequencing.

Verifies that when the LLM produces multiple thinking → response transitions
within a single turn (e.g. during tool-calling loops), each section gets its
own unique section_id and DB row instead of being merged into a single
accumulated blob.

Tests cover:
1. Single thinking → response (basic case, no regression)
2. Multiple thinking sections separated by tool calls
3. Multiple response sections separated by tool calls
4. Full cycle: thinking → response → tool_call → thinking → response
5. Section IDs are unique and sequential
6. DB rows are written in order with distinct section_ids
7. History reconstruction still works with multiple sections per turn
"""

from __future__ import annotations

import asyncio
import os
import sys
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.stream_manager import StreamManager, _format_tool_call_json
from core.providers.base import StreamChunk, TokenUsage, ToolCall


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class FakeDB:
	"""Minimal in-memory database for testing StreamManager persistence."""

	def __init__(self):
		self.rows: list[dict] = []
		self._next_id = 1

	def create_chat(self) -> str:
		return "chat-1"

	def save_section(self, chat_id, turn_id, content_type, content, section_id=""):
		row = {
			"id": self._next_id,
			"chat_id": chat_id,
			"turn_id": turn_id,
			"section_id": section_id,
			"content_type": content_type,
			"content": content,
		}
		self._next_id += 1
		self.rows.append(row)
		return row["id"]

	def upsert_streaming_section(self, chat_id, turn_id, section_id, content_type, content):
		"""Upsert: if section_id exists, update in place; otherwise insert."""
		for row in self.rows:
			if row["chat_id"] == chat_id and row["turn_id"] == turn_id and row["section_id"] == section_id:
				row["content"] = content
				row["content_type"] = content_type
				return row["id"]
		return self.save_section(chat_id, turn_id, content_type, content, section_id=section_id)

	def load_sections(self, chat_id):
		return sorted(self.rows, key=lambda r: r["id"])


class MockAgent:
	"""A mock agent that yields configurable chunks."""

	def __init__(self, chunks):
		self._chunks = chunks
		self._aborted = False

	def abort(self):
		self._aborted = True

	async def stream_chat(self, history, user_text, tools=None):
		for chunk in self._chunks:
			yield chunk


# ---------------------------------------------------------------------------
# A: Basic single-section streaming (regression test)
# ---------------------------------------------------------------------------


class TestBasicStreaming:
	"""Verify that simple single thinking→response still works."""

	@pytest.mark.asyncio
	async def test_single_response_no_thinking(self):
		"""A stream with only response content should create one response section."""
		sm = StreamManager()
		db = FakeDB()
		turn_id = "turn-1"

		chunks = [
			StreamChunk(content="Hello ", done=False),
			StreamChunk(content="world!", done=True, usage=TokenUsage(total_tokens=10)),
		]

		agent = MockAgent(chunks)
		stream_id = sm.start(agent, [], "hi", db=db, chat_id="chat-1", turn_id=turn_id)

		# Wait for the stream to complete.
		for _ in range(20):
			await asyncio.sleep(0.05)
			if not sm.has_stream(stream_id):
				break

		# Should have one response section.
		response_rows = [r for r in db.rows if r["content_type"] == "response"]
		assert len(response_rows) >= 1
		assert "Hello world!" in response_rows[-1]["content"]

	@pytest.mark.asyncio
	async def test_single_thinking_then_response(self):
		"""thinking→response should produce two sections with distinct IDs."""
		sm = StreamManager()
		db = FakeDB()
		turn_id = "turn-2"

		chunks = [
			StreamChunk(content="", thinking="Let me think...", done=False),
			StreamChunk(content="Here's the answer.", done=True, usage=TokenUsage(total_tokens=20)),
		]

		agent = MockAgent(chunks)
		stream_id = sm.start(agent, [], "hi", db=db, chat_id="chat-1", turn_id=turn_id)

		for _ in range(20):
			await asyncio.sleep(0.05)
			if not sm.has_stream(stream_id):
				break

		thinking_rows = [r for r in db.rows if r["content_type"] == "thinking"]
		response_rows = [r for r in db.rows if r["content_type"] == "response"]

		assert len(thinking_rows) >= 1
		assert len(response_rows) >= 1
		assert "Let me think..." in thinking_rows[0]["content"]
		assert "Here's the answer." in response_rows[0]["content"]


# ---------------------------------------------------------------------------
# B: Sequential section creation (the core fix)
# ---------------------------------------------------------------------------


class TestSequentialSections:
	"""Verify that multiple thinking/response transitions create separate sections."""

	@pytest.mark.asyncio
	async def test_thinking_after_response_creates_new_section(self):
		"""When thinking content arrives after response content has been written,
		a new thinking section should be created instead of merging into the
		existing thinking accumulator."""
		sm = StreamManager()
		db = FakeDB()
		turn_id = "turn-3"

		# Simulate: thinking → response → tool_call → thinking → response
		chunks = [
			StreamChunk(content="", thinking="First thinking", done=False),
			StreamChunk(content="First response", done=False),
			StreamChunk(
				content="",
				done=False,
				tool_calls=[ToolCall(id="tc-1", name="read_file", arguments={"path": "/tmp/test"})],
			),
			StreamChunk(content="", done=False, tool_results={"tc-1": "file contents"}),
			StreamChunk(content="", thinking="Second thinking", done=False),
			StreamChunk(content="Second response", done=True, usage=TokenUsage(total_tokens=50)),
		]

		agent = MockAgent(chunks)
		stream_id = sm.start(agent, [], "hi", db=db, chat_id="chat-1", turn_id=turn_id)

		for _ in range(30):
			await asyncio.sleep(0.05)
			if not sm.has_stream(stream_id):
				break

		thinking_rows = [r for r in db.rows if r["content_type"] == "thinking"]
		response_rows = [r for r in db.rows if r["content_type"] == "response"]

		# Should have TWO thinking sections, not one merged blob.
		assert len(thinking_rows) == 2, f"Expected 2 thinking rows, got {len(thinking_rows)}: {thinking_rows}"
		assert "First thinking" in thinking_rows[0]["content"]
		assert "Second thinking" in thinking_rows[1]["content"]

		# Should have TWO response sections, not one merged blob.
		assert len(response_rows) == 2, f"Expected 2 response rows, got {len(response_rows)}: {response_rows}"
		assert "First response" in response_rows[0]["content"]
		assert "Second response" in response_rows[1]["content"]

		# Sections should have DISTINCT section_ids (not the same).
		thinking_ids = {r["section_id"] for r in thinking_rows}
		response_ids = {r["section_id"] for r in response_rows}
		assert len(thinking_ids) == 2, f"Thinking section IDs should be unique, got: {thinking_ids}"
		assert len(response_ids) == 2, f"Response section IDs should be unique, got: {response_ids}"

	@pytest.mark.asyncio
	async def test_section_ids_are_unique(self):
		"""All sections in a turn should have unique section_ids."""
		sm = StreamManager()
		db = FakeDB()
		turn_id = "turn-4"

		chunks = [
			StreamChunk(content="", thinking="Think 1", done=False),
			StreamChunk(content="Resp 1", done=False),
			StreamChunk(
				content="",
				done=False,
				tool_calls=[ToolCall(id="tc-1", name="run_command", arguments={"cmd": "ls"})],
			),
			StreamChunk(content="", done=False, tool_results={"tc-1": "file1.txt\nfile2.txt"}),
			StreamChunk(content="", thinking="Think 2", done=False),
			StreamChunk(content="Resp 2", done=True, usage=TokenUsage(total_tokens=30)),
		]

		agent = MockAgent(chunks)
		stream_id = sm.start(agent, [], "hi", db=db, chat_id="chat-1", turn_id=turn_id)

		for _ in range(30):
			await asyncio.sleep(0.05)
			if not sm.has_stream(stream_id):
				break

		all_ids = [r["section_id"] for r in db.rows]
		assert len(all_ids) == len(set(all_ids)), f"Section IDs should be unique, got: {all_ids}"

	@pytest.mark.asyncio
	async def test_section_order_preserved(self):
		"""Sections should be stored in DB in the order they were created."""
		sm = StreamManager()
		db = FakeDB()
		turn_id = "turn-5"

		chunks = [
			StreamChunk(content="", thinking="Think 1", done=False),
			StreamChunk(content="Resp 1", done=False),
			StreamChunk(
				content="",
				done=False,
				tool_calls=[ToolCall(id="tc-1", name="run_command", arguments={"cmd": "ls"})],
			),
			StreamChunk(content="", done=False, tool_results={"tc-1": "output"}),
			StreamChunk(content="", thinking="Think 2", done=False),
			StreamChunk(content="Resp 2", done=True, usage=TokenUsage(total_tokens=30)),
		]

		agent = MockAgent(chunks)
		stream_id = sm.start(agent, [], "hi", db=db, chat_id="chat-1", turn_id=turn_id)

		for _ in range(30):
			await asyncio.sleep(0.05)
			if not sm.has_stream(stream_id):
				break

		content_types = [r["content_type"] for r in db.rows]
		# Expected order: thinking, response, tool_call, thinking, response
		assert content_types == ["thinking", "response", "tool_call", "thinking", "response"], \
			f"Expected sequential content types, got: {content_types}"

	@pytest.mark.asyncio
	async def test_response_after_tool_result_creates_new_section(self):
		"""When response content arrives after tool calls, it should be a
		new response section, not merged with the pre-tool-call response."""
		sm = StreamManager()
		db = FakeDB()
		turn_id = "turn-6"

		chunks = [
			StreamChunk(content="Before tool call.", done=False),
			StreamChunk(
				content="",
				done=False,
				tool_calls=[ToolCall(id="tc-1", name="read_file", arguments={"path": "/tmp/x"})],
			),
			StreamChunk(content="", done=False, tool_results={"tc-1": "file content"}),
			StreamChunk(content="After tool call.", done=True, usage=TokenUsage(total_tokens=40)),
		]

		agent = MockAgent(chunks)
		stream_id = sm.start(agent, [], "hi", db=db, chat_id="chat-1", turn_id=turn_id)

		for _ in range(30):
			await asyncio.sleep(0.05)
			if not sm.has_stream(stream_id):
				break

		response_rows = [r for r in db.rows if r["content_type"] == "response"]
		assert len(response_rows) == 2, f"Expected 2 response rows, got {len(response_rows)}: {response_rows}"
		assert "Before tool call." in response_rows[0]["content"]
		assert "After tool call." in response_rows[1]["content"]


# ---------------------------------------------------------------------------
# C: _handle_chunk transition detection
# ---------------------------------------------------------------------------


class TestHandleChunkTransitions:
	"""Unit tests for _handle_chunk section transition detection."""

	def test_thinking_chunk_creates_thinking_section(self):
		"""A thinking chunk should start a thinking section."""
		sm = StreamManager()
		stream_id = "test-s1"

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

		chunk = StreamChunk(content="", thinking="Hmm...", done=False)
		sm._handle_chunk(stream_id, chunk)

		meta = sm._metadata[stream_id]
		assert meta["current_section_type"] == "thinking"
		assert "Hmm..." in meta["current_section_text"]

	def test_response_after_thinking_creates_new_section(self):
		"""When a response chunk arrives while the current section is thinking,
		a new response section should be started."""
		sm = StreamManager()
		stream_id = "test-s2"

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

		# First chunk: thinking
		sm._handle_chunk(stream_id, StreamChunk(content="", thinking="Think...", done=False))
		assert sm._metadata[stream_id]["current_section_type"] == "thinking"

		# Second chunk: response — should transition to a new section
		sm._handle_chunk(stream_id, StreamChunk(content="Respond...", done=False))
		assert sm._metadata[stream_id]["current_section_type"] == "response"

		# The previous thinking section should be in the completed sections list.
		thinking_sections = [s for s in sm._metadata[stream_id]["sections"] if s["content_type"] == "thinking"]
		assert len(thinking_sections) == 1
		assert "Think..." in thinking_sections[0]["text"]

	def test_thinking_after_response_creates_new_section(self):
		"""When a thinking chunk arrives while the current section is response,
		a new thinking section should be started."""
		sm = StreamManager()
		stream_id = "test-s3"

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

		# First chunk: response
		sm._handle_chunk(stream_id, StreamChunk(content="First response", done=False))
		assert sm._metadata[stream_id]["current_section_type"] == "response"

		# Second chunk: thinking — should transition to a new section
		sm._handle_chunk(stream_id, StreamChunk(content="", thinking="Second thinking", done=False))
		assert sm._metadata[stream_id]["current_section_type"] == "thinking"

		# The previous response section should be in completed sections.
		response_sections = [s for s in sm._metadata[stream_id]["sections"] if s["content_type"] == "response"]
		assert len(response_sections) == 1
		assert "First response" in response_sections[0]["text"]

	def test_tool_call_finalizes_current_text_section(self):
		"""When a tool call chunk arrives, the current text section should be
		finalized and added to the sections list."""
		sm = StreamManager()
		stream_id = "test-s4"

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

		# Response chunk starts a response section
		sm._handle_chunk(stream_id, StreamChunk(content="Before tools", done=False))
		assert sm._metadata[stream_id]["current_section_type"] == "response"

		# Tool call chunk should finalize the response section
		sm._handle_chunk(stream_id, StreamChunk(
			content="",
			done=False,
			tool_calls=[ToolCall(id="tc-1", name="read_file", arguments={"path": "/tmp"})],
		))

		# The response section should be finalized
		response_sections = [s for s in sm._metadata[stream_id]["sections"] if s["content_type"] == "response"]
		assert len(response_sections) == 1
		assert "Before tools" in response_sections[0]["text"]

		# Current section type should be reset (tool calls don't set current_section_type)
		assert sm._metadata[stream_id]["current_section_type"] is None

	def test_same_type_continues_current_section(self):
		"""Multiple chunks of the same type should accumulate in the same section."""
		sm = StreamManager()
		stream_id = "test-s5"

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

		# Multiple response chunks should accumulate in the same section
		sm._handle_chunk(stream_id, StreamChunk(content="Hello ", done=False))
		sm._handle_chunk(stream_id, StreamChunk(content="world", done=False))
		sm._handle_chunk(stream_id, StreamChunk(content="!", done=False))

		meta = sm._metadata[stream_id]
		assert meta["current_section_type"] == "response"
		assert meta["current_section_text"] == "Hello world!"
		assert len(meta["sections"]) == 0  # No transitions, so no completed sections

	def test_thinking_and_response_in_same_chunk(self):
		"""A single chunk with both thinking and content should create two sections."""
		sm = StreamManager()
		stream_id = "test-s6"

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

		# Chunk with both thinking and content
		sm._handle_chunk(stream_id, StreamChunk(thinking="I'm thinking", content="Here's the answer", done=False))

		meta = sm._metadata[stream_id]
		# Current section should be response (last type processed)
		assert meta["current_section_type"] == "response"
		assert "Here's the answer" in meta["current_section_text"]

		# Thinking section should be in completed sections
		thinking_sections = [s for s in meta["sections"] if s["content_type"] == "thinking"]
		assert len(thinking_sections) == 1
		assert "I'm thinking" in thinking_sections[0]["text"]