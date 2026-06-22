"""Tests for final response display — ensuring the last response section
is always visible even when refresh/swap operations encounter errors.

Covers:
- _sync_conversation final refresh success and failure paths
- _swap_to_markdown fallback when DOM swap fails
- finalize_turn error resilience
"""

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from skills.chat.chat_display import ChatDisplay


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_section(turn_id="t1", content_type="response", content="hello", section_id="s1"):
	"""Create a minimal section dict like the DB returns."""
	return {
		"turn_id": turn_id,
		"content_type": content_type,
		"content": content,
		"section_id": section_id,
	}


# ---------------------------------------------------------------------------
# ChatManager._sync_conversation — final refresh error handling
# ---------------------------------------------------------------------------

class TestSyncConversationFinalRefresh:
	"""Tests for the final refresh in _sync_conversation."""

	def _make_cm(self):
		"""Create a mock ChatManager with _sync_conversation bound."""
		from skills.chat.chat_manager import ChatManager
		cm = MagicMock(spec=ChatManager)
		cm._sync_conversation = ChatManager._sync_conversation.__get__(cm, ChatManager)
		cm.is_mounted = True
		cm._chat_display = MagicMock(spec=ChatDisplay)
		cm._chat_display._detached = False
		cm._db = MagicMock()
		cm._chat_id = "c1"
		cm._stream_id = None
		cm._rebuild_history = MagicMock()
		cm._chat_input = MagicMock()
		cm._agent = MagicMock(_model="test")
		cm._state = MagicMock()
		cm._attach_revert_buttons = MagicMock()
		cm._streaming = False
		return cm

	def _setup_no_stream(self, cm):
		"""Configure mocks so there's no active stream (single-shot finalize)."""
		sm = MagicMock()
		sm.get_usage.return_value = None
		ctx = MagicMock()
		ctx.stream_manager = sm
		cm._get_context = MagicMock(return_value=ctx)
		return sm

	@pytest.mark.asyncio
	async def test_final_refresh_logs_error_on_failure(self, caplog):
		"""If the finalize refresh_from_sections raises, the error is logged."""
		cm = self._make_cm()
		self._setup_no_stream(cm)
		cm._db.load_sections.return_value = [_make_section()]

		# finalize=True raises, fallback also raises.
		cm._chat_display.refresh_from_sections = AsyncMock(
			side_effect=RuntimeError("DOM error")
		)

		# Should NOT raise — error should be caught, logged, and retried.
		with caplog.at_level(logging.ERROR, logger="skills.chat.chat_manager"):
			await cm._sync_conversation(finalize=True)

		# Both errors should be logged.
		assert any("finalize=True" in r.message for r in caplog.records)
		assert any("Fallback" in r.message for r in caplog.records)

	@pytest.mark.asyncio
	async def test_final_refresh_retry_on_failure(self):
		"""If finalize=True fails, retry with finalize=False as fallback."""
		cm = self._make_cm()
		self._setup_no_stream(cm)
		cm._db.load_sections.return_value = [_make_section()]

		# First call (finalize=True) raises, second call (finalize=False) succeeds.
		call_count = 0
		async def _refresh(sections, finalize=False):
			nonlocal call_count
			call_count += 1
			if finalize:
				raise RuntimeError("DOM swap failed")
			# Succeeds without finalize.

		cm._chat_display.refresh_from_sections = AsyncMock(side_effect=_refresh)

		await cm._sync_conversation(finalize=True)

		assert call_count == 2  # finalize=True failed, then finalize=False succeeded

	@pytest.mark.asyncio
	async def test_final_refresh_both_attempts_fail_no_crash(self, caplog):
		"""If both finalize and non-finalize refreshes fail, no crash."""
		cm = self._make_cm()
		self._setup_no_stream(cm)
		cm._db.load_sections.return_value = [_make_section()]

		# Both calls fail.
		cm._chat_display.refresh_from_sections = AsyncMock(
			side_effect=RuntimeError("catastrophic")
		)

		# Should NOT raise.
		with caplog.at_level(logging.ERROR, logger="skills.chat.chat_manager"):
			await cm._sync_conversation(finalize=True)

		assert any("Fallback" in r.message for r in caplog.records)

	@pytest.mark.asyncio
	async def test_final_refresh_succeeds_first_try(self):
		"""If the final refresh succeeds on the first try, no retry needed."""
		cm = self._make_cm()
		self._setup_no_stream(cm)
		cm._db.load_sections.return_value = [_make_section()]

		call_count = 0
		async def _refresh(sections, finalize=False):
			nonlocal call_count
			call_count += 1

		cm._chat_display.refresh_from_sections = AsyncMock(side_effect=_refresh)

		await cm._sync_conversation(finalize=True)

		assert call_count == 1  # Only one call, no retry

	@pytest.mark.asyncio
	async def test_sync_conversation_returns_early_when_no_db(self):
		"""_sync_conversation should return early if no DB or chat_id."""
		from skills.chat.chat_manager import ChatManager
		cm = MagicMock(spec=ChatManager)
		cm._sync_conversation = ChatManager._sync_conversation.__get__(cm, ChatManager)
		cm._db = None
		cm._chat_id = None

		# Should return without error — no DB to load from.
		await cm._sync_conversation(finalize=True)

	@pytest.mark.asyncio
	async def test_streaming_poll_error_logged_as_warning(self, caplog):
		"""During streaming loop, refresh errors are logged at WARNING level."""
		from skills.chat.chat_manager import ChatManager
		cm = MagicMock(spec=ChatManager)
		cm._sync_conversation = ChatManager._sync_conversation.__get__(cm, ChatManager)
		cm.is_mounted = True
		cm._chat_display = MagicMock(spec=ChatDisplay)
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

		sm = MagicMock()
		# Stream finishes after one iteration.
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

		cm._db.load_sections.return_value = [_make_section()]
		cm._chat_display.refresh_from_sections = AsyncMock(
			side_effect=RuntimeError("transient")
		)

		with caplog.at_level(logging.WARNING, logger="skills.chat.chat_manager"):
			await cm._sync_conversation(loop=True)

		assert any("Conversation sync refresh failed during polling" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# ChatDisplay._swap_to_markdown — fallback logging
# ---------------------------------------------------------------------------

class TestSwapToMarkdownFallback:
	"""Tests for _swap_to_markdown error resilience."""

	@pytest.mark.asyncio
	async def test_swap_to_markdown_fallback_on_dom_error(self):
		"""If DOM swap fails, _contents_list fallback is used."""
		display = ChatDisplay()
		from textual.widgets import Static, Markdown

		# Setup internal state.
		section_id = "sec1"
		display._section_widgets = {section_id: Static("hello")}
		display._section_texts = {section_id: "hello world"}
		display._section_types = {section_id: "response"}
		display._section_map = {}  # No Section in DOM.

		# Should not crash even with no Section widget.
		await display._swap_to_markdown(section_id)

		# Widget mapping should be updated to Markdown.
		assert isinstance(display._section_widgets[section_id], Markdown)

	@pytest.mark.asyncio
	async def test_swap_to_markdown_no_crash_on_empty_text(self):
		"""_swap_to_markdown with empty text should return early."""
		display = ChatDisplay()
		section_id = "sec2"
		from textual.widgets import Static
		display._section_widgets = {section_id: Static("")}
		display._section_texts = {section_id: ""}
		display._section_types = {section_id: "response"}

		await display._swap_to_markdown(section_id)
		# Should remain Static (not swapped).
		assert isinstance(display._section_widgets[section_id], Static)


# ---------------------------------------------------------------------------
# ChatDisplay.finalize_turn — empty section removal
# ---------------------------------------------------------------------------

class TestFinalizeTurnEmptyRemoval:
	"""Tests for finalize_turn removing empty sections correctly."""

	@pytest.mark.asyncio
	async def test_finalize_clears_state_when_detached(self):
		"""finalize_turn should clear tracking state when detached."""
		display = ChatDisplay()
		display._detached = True  # Skip DOM operations

		from textual.widgets import Static
		display._active_asst_id = "asst1"
		display._section_widgets = {"sec1": Static("hello")}
		display._section_texts = {"sec1": "hello"}
		display._section_types = {"sec1": "response"}

		await display.finalize_turn()

		# State should be cleared even when detached.
		assert display._active_asst_id is None
		assert display._section_widgets == {}
		assert display._section_texts == {}