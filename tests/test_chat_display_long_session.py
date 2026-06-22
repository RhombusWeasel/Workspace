"""Regression tests for chat display losing connection in long sessions.

The core bug: the _sync_conversation polling loop caught all exceptions from
refresh_from_sections at DEBUG level (effectively silent).  Once an exception
started occurring, every subsequent poll failed at the same point and the
display never recovered for the rest of the stream.

These tests verify:
1. Per-section errors in refresh_from_sections don't block subsequent sections.
2. _section_widgets dict is NOT cleared by begin_assistant_turn during
   DB-driven refresh (so earlier-turn sections can still be updated).
3. Polling loop errors are logged at WARNING level (visible, not silent).
4. A long multi-turn conversation with many sections renders correctly.
"""

import json
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Collapsible, Markdown, Static

from skills.chat.chat_display import (
	AssistantTurn,
	ChatDisplay,
	Section,
	ToolCallSection,
	UserMessage,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_sections(chat_id, turns):
	"""Build flat section dicts from a list of turn dicts."""
	sections = []
	sec_idx = 0
	for turn in turns:
		tid = turn["turn_id"]
		for msg in turn["messages"]:
			sec_idx += 1
			sections.append({
		"turn_id": tid,
				"content_type": msg["content_type"],
				"content": msg["content"],
				"status": msg.get("status", "complete"),
				"section_id": msg.get("section_id", f"sec-{sec_idx}"),
				"id": sec_idx,
			})
	return sections


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


def _make_long_conversation(num_turns=5):
	"""Build a long conversation with multiple turns, tool calls, and thinking."""
	turns = []
	for i in range(num_turns):
		turns.append({
			"turn_id": f"t{i+1}",
			"messages": [
				{"content_type": "user", "content": f"Question {i+1}"},
				{"content_type": "thinking", "content": f"Thinking about question {i+1}..."},
				{
					"content_type": "tool_call",
					"content": json.dumps({
						"name": "read_file",
						"arguments": {"path": f"file{i+1}.py"},
						"result": f"contents of file{i+1}.py",
					}),
				},
				{"content_type": "response", "content": f"Answer {i+1} with **bold** text."},
			],
		})
	return turns


# ---------------------------------------------------------------------------
# Tests — per-section error isolation
# ---------------------------------------------------------------------------

class TestPerSectionErrorIsolation:
	"""Test that one failing section doesn't block all subsequent sections."""

	@pytest.mark.asyncio
	async def test_one_section_error_doesnt_block_others(self):
		"""If add_section raises for one section, subsequent sections
		should still be processed."""
		async with _ChatApp().run_test() as pilot:
			display = pilot.app.chat_display

			# Build sections for two turns
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
						{"content_type": "response", "content": "I'm good!"},
					],
				},
			])

			# Patch add_section to fail for the first response section only
			original_add_section = display.add_section
			call_count = 0

			async def patched_add_section(section_type, *, as_markdown=False):
				nonlocal call_count
				call_count += 1
				if call_count == 1 and section_type == "response":
					raise RuntimeError("Simulated section error")
				return await original_add_section(section_type, as_markdown=as_markdown)

			with patch.object(display, 'add_section', side_effect=patched_add_section):
				await display.refresh_from_sections(sections, finalize=True)
				await pilot.pause()

			# The first response section failed, but the second turn should
			# still have been created with its user message and response.
			user_msgs = list(display.query(UserMessage))
			assert len(user_msgs) == 2, (
				f"Both user messages should be present, got {len(user_msgs)}"
			)

	@pytest.mark.asyncio
	async def test_swap_error_doesnt_block_subsequent_sections(self):
		"""If _maybe_swap_to_markdown raises for one section, subsequent
		sections should still be processed."""
		async with _ChatApp().run_test() as pilot:
			display = pilot.app.chat_display

			# First poll: streaming sections
			streaming_sections = _make_sections("chat-1", [
				{
					"turn_id": "t1",
					"messages": [
						{"content_type": "user", "content": "Hello"},
						{"content_type": "response", "content": "Hi", "status": "streaming"},
					],
				},
				{
					"turn_id": "t2",
					"messages": [
						{"content_type": "user", "content": "How?"},
						{"content_type": "response", "content": "Good", "status": "streaming"},
					],
				},
			])
			await display.refresh_from_sections(streaming_sections, finalize=False)
			await pilot.pause()

			# Second poll: sections completed — swap should be attempted
			completed_sections = _make_sections("chat-1", [
				{
					"turn_id": "t1",
					"messages": [
						{"content_type": "user", "content": "Hello"},
						{"content_type": "response", "content": "Hi", "status": "complete"},
					],
				},
				{
					"turn_id": "t2",
					"messages": [
						{"content_type": "user", "content": "How?"},
						{"content_type": "response", "content": "Good", "status": "complete"},
					],
				},
			])

			# Patch _maybe_swap_to_markdown to always raise
			async def broken_swap(key, content):
				raise RuntimeError("Swap failed")

			with patch.object(display, '_maybe_swap_to_markdown', side_effect=broken_swap):
				# Should not raise — error is caught per-section
				await display.refresh_from_sections(completed_sections, finalize=False)
				await pilot.pause()

			# Both turns should still be in the display
			user_msgs = list(display.query(UserMessage))
			assert len(user_msgs) == 2, (
				f"Both user messages should survive swap error, got {len(user_msgs)}"
			)


# ---------------------------------------------------------------------------
# Tests — _section_widgets not cleared by begin_assistant_turn
# ---------------------------------------------------------------------------

class TestSectionWidgetsNotCleared:
	"""Test that begin_assistant_turn does NOT clear _section_widgets
	during DB-driven refresh, so earlier-turn sections can still be updated."""

	@pytest.mark.asyncio
	async def test_begin_assistant_turn_preserves_section_widgets(self):
		"""After begin_assistant_turn for turn 2, section_widgets from
		turn 1 should still be present."""
		async with _ChatApp().run_test() as pilot:
			display = pilot.app.chat_display

			# Simulate first turn
			display.begin_assistant_turn(turn_id="t1")
			section_id_1 = await display.add_section("response")
			await display.update_section(section_id_1, "First response")
			await pilot.pause()

			# Verify section widget exists
			assert section_id_1 in display._section_widgets

			# Start second turn — this should NOT clear section_widgets
			display.begin_assistant_turn(turn_id="t2")
			section_id_2 = await display.add_section("response")
			await display.update_section(section_id_2, "Second response")
			await pilot.pause()

			# Both section widgets should still be tracked
			assert section_id_1 in display._section_widgets, (
				"Section widget from turn 1 should NOT be cleared by begin_assistant_turn"
			)
			assert section_id_2 in display._section_widgets

	@pytest.mark.asyncio
	async def test_multi_turn_refresh_preserves_all_sections(self):
		"""A multi-turn DB-driven refresh should preserve section widgets
		across turns so incremental updates work for all turns."""
		async with _ChatApp().run_test() as pilot:
			display = pilot.app.chat_display

			# Build a 3-turn conversation
			turns = _make_long_conversation(num_turns=3)
			sections = _make_sections("chat-1", turns)

			# First poll: all streaming
			streaming_sections = []
			for sec in sections:
				s = dict(sec)
				if s["content_type"] in ("response", "thinking"):
					s["status"] = "streaming"
				streaming_sections.append(s)

			await display.refresh_from_sections(streaming_sections, finalize=False)
			await pilot.pause()

			# Count section widgets — should have all response + thinking sections
			response_widgets_before = len([
				k for k, v in display._section_widgets.items()
				if k.startswith("response-")
			])
			assert response_widgets_before == 3, (
				f"Expected 3 response section widgets, got {response_widgets_before}"
			)

			# Second poll: first turn's response completed, others still streaming
			# This triggers _maybe_swap_to_markdown for the completed section
			updated_sections = []
			for sec in streaming_sections:
				s = dict(sec)
				if sec["turn_id"] == "t1" and s["content_type"] == "response":
					s["status"] = "complete"
				updated_sections.append(s)

			await display.refresh_from_sections(updated_sections, finalize=False)
			await pilot.pause()

			# All section widgets should still be tracked
			response_widgets_after = len([
				k for k, v in display._section_widgets.items()
				if k.startswith("response-")
			])
			assert response_widgets_after == 3, (
				f"Expected 3 response section widgets after update, "
				f"got {response_widgets_after}"
			)


# ---------------------------------------------------------------------------
# Tests — polling loop error visibility
# ---------------------------------------------------------------------------

class TestPollingLoopErrorVisibility:
	"""Test that polling loop errors are logged at WARNING level."""

	def _make_cm(self):
		"""Create a mock ChatManager with _sync_conversation bound."""
		from skills.chat.chat_manager import ChatManager
		from skills.chat.chat_display import ChatDisplay as CD
		cm = MagicMock(spec=ChatManager)
		cm._sync_conversation = ChatManager._sync_conversation.__get__(cm, ChatManager)
		cm.is_mounted = True
		cm._chat_display = MagicMock(spec=CD)
		cm._chat_display._detached = False
		cm._db = MagicMock()
		cm._chat_id = "c1"
		cm._stream_id = "s1"
		cm._rebuild_history = MagicMock()
		cm._chat_input = MagicMock()
		cm._agent = MagicMock(_model="test")
		cm._state = MagicMock()
		cm._attach_revert_buttons = MagicMock()
		cm._streaming = True
		return cm

	@pytest.mark.asyncio
	async def test_polling_error_logged_at_warning(self, caplog):
		"""Polling loop refresh errors should be logged at WARNING level."""
		cm = self._make_cm()

		sm = MagicMock()
		call_count = 0
		def has_stream(sid):
			nonlocal call_count
			call_count += 1
			return call_count < 2  # Only one poll iteration
		sm.has_stream = has_stream
		sm.get_usage.return_value = None
		ctx = MagicMock()
		ctx.stream_manager = sm
		cm._get_context = MagicMock(return_value=ctx)

		cm._db.load_sections.return_value = [{"turn_id": "t1", "content_type": "response", "content": "hi", "section_id": "s1"}]
		cm._chat_display.refresh_from_sections = AsyncMock(
			side_effect=RuntimeError("transient error")
		)

		with caplog.at_level(logging.WARNING, logger="skills.chat.chat_manager"):
			await cm._sync_conversation(loop=True)

		# Should be logged at WARNING, not DEBUG
		warning_records = [
			r for r in caplog.records
			if r.levelno == logging.WARNING
			and "Conversation sync refresh failed during polling" in r.message
		]
		assert len(warning_records) >= 1, (
			"Polling loop error should be logged at WARNING level"
		)

	@pytest.mark.asyncio
	async def test_polling_error_not_silent(self, caplog):
		"""Polling loop errors should NOT be at DEBUG level only."""
		cm = self._make_cm()

		sm = MagicMock()
		call_count = 0
		def has_stream(sid):
			nonlocal call_count
			call_count += 1
			return call_count < 2
		sm.has_stream = has_stream
		sm.get_usage.return_value = None
		ctx = MagicMock()
		ctx.stream_manager = sm
		cm._get_context = MagicMock(return_value=ctx)

		cm._db.load_sections.return_value = [{"turn_id": "t1", "content_type": "response", "content": "hi", "section_id": "s1"}]
		cm._chat_display.refresh_from_sections = AsyncMock(
			side_effect=RuntimeError("transient error")
		)

		# Capture at DEBUG level to check what gets logged
		with caplog.at_level(logging.DEBUG, logger="skills.chat.chat_manager"):
			await cm._sync_conversation(loop=True)

		# Should be at WARNING, not DEBUG
		debug_only_records = [
			r for r in caplog.records
			if r.levelno == logging.DEBUG
			and "Conversation sync refresh failed" in r.message
		]
		assert len(debug_only_records) == 0, (
			"Polling loop error should NOT be logged at DEBUG level only"
		)


# ---------------------------------------------------------------------------
# Tests — long multi-turn conversation
# ---------------------------------------------------------------------------

class TestLongMultiTurnConversation:
	"""Test that a long multi-turn conversation renders correctly."""

	@pytest.mark.asyncio
	async def test_five_turn_conversation_renders(self):
		"""A 5-turn conversation with tool calls should render all turns."""
		turns = _make_long_conversation(num_turns=5)
		sections = _make_sections("chat-1", turns)

		async with _ChatApp().run_test() as pilot:
			display = pilot.app.chat_display

			await display.refresh_from_sections(sections, finalize=True)
			await pilot.pause()

			user_msgs = list(display.query(UserMessage))
			asst_turns = list(display.query(AssistantTurn))
			tool_calls = list(display.query(ToolCallSection))

			assert len(user_msgs) == 5, (
				f"Expected 5 user messages, got {len(user_msgs)}"
			)
			assert len(asst_turns) == 5, (
				f"Expected 5 assistant turns, got {len(asst_turns)}"
			)
			assert len(tool_calls) == 5, (
				f"Expected 5 tool call sections, got {len(tool_calls)}"
			)

	@pytest.mark.asyncio
	async def test_streaming_then_finalize_long_conversation(self):
		"""Simulate streaming a 3-turn conversation: streaming polls then
		a final finalize.  All content should be present and rendered."""
		turns = _make_long_conversation(num_turns=3)
		sections = _make_sections("chat-1", turns)

		async with _ChatApp().run_test() as pilot:
			display = pilot.app.chat_display

			# Streaming poll 1: first turn only, response streaming
			poll_1 = _make_sections("chat-1", [turns[0]])
			for s in poll_1:
				if s["content_type"] in ("response", "thinking"):
					s["status"] = "streaming"
			await display.refresh_from_sections(poll_1, finalize=False)
			await pilot.pause()

			# Verify first turn's response is Static during streaming
			all_sections = list(display.query(Section))
			response_sections = [
				s for s in all_sections
				if s.section_id.startswith("response-")
			]
			assert len(response_sections) == 1
			assert isinstance(response_sections[0]._content_widget, Static), (
				"Response should be Static during streaming"
			)

			# Streaming poll 2: first turn complete, second turn streaming
			poll_2 = _make_sections("chat-1", [turns[0], turns[1]])
			for s in poll_2:
				if s["turn_id"] == "t1" and s["content_type"] in ("response", "thinking"):
					s["status"] = "complete"
				elif s["turn_id"] == "t2" and s["content_type"] in ("response", "thinking"):
					s["status"] = "streaming"
			await display.refresh_from_sections(poll_2, finalize=False)
			await pilot.pause()

			# Both turns should have user messages
			user_msgs = list(display.query(UserMessage))
			assert len(user_msgs) == 2

			# Final finalize: all turns complete
			await display.refresh_from_sections(sections, finalize=True)
			await pilot.pause()

			user_msgs = list(display.query(UserMessage))
			asst_turns = list(display.query(AssistantTurn))
			tool_calls = list(display.query(ToolCallSection))

			assert len(user_msgs) == 3
			assert len(asst_turns) == 3
			assert len(tool_calls) == 3

			# All response sections should be Markdown after finalize
			all_sections = list(display.query(Section))
			response_sections = [
				s for s in all_sections
				if s.section_id.startswith("response-")
			]
			assert len(response_sections) == 3
			for s in response_sections:
				assert isinstance(s._content_widget, Markdown), (
					f"Response section {s.section_id} should be Markdown after finalize, "
					f"got {type(s._content_widget).__name__}"
				)