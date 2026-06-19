"""Tests for the Markdown preview toggle in FileEditor.

Covers:
- Initial state is edit mode (TextArea visible, Markdown hidden)
- Ctrl+P toggles to preview mode for .md files
- Ctrl+P toggles back to edit mode
- Non-markdown files are no-op on toggle
- Preview content matches editor text
- AI suggestion is cleared when entering preview mode
- AI suggestion request is no-op in preview mode
- Save still works after a preview round-trip
"""

import os
import tempfile

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Markdown, TextArea

from ui.workspace.file_editor import FileEditor, FileEditorState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_md_file(content: str = "# Hello\n\nSome **markdown** text.\n") -> str:
	"""Create a temporary .md file and return its path."""
	fd, path = tempfile.mkstemp(suffix=".md")
	with os.fdopen(fd, "w") as f:
		f.write(content)
	return path


def _make_py_file(content: str = "print('hello')\n") -> str:
	"""Create a temporary .py file and return its path."""
	fd, path = tempfile.mkstemp(suffix=".py")
	with os.fdopen(fd, "w") as f:
		f.write(content)
	return path


class _EditorApp(App):
	"""Minimal app that mounts a FileEditor for testing."""

	def __init__(self, filepath: str):
		super().__init__()
		self._filepath = filepath

	def compose(self) -> ComposeResult:
		state = FileEditorState(self._filepath)
		yield FileEditor(state)


@pytest.mark.asyncio
async def test_initial_state_is_edit_mode():
	"""Freshly composed FileEditor is in edit mode."""
	path = _make_md_file()
	try:
		app = _EditorApp(path)
		async with app.run_test() as pilot:
			editor = app.query_one(FileEditor)
			text_area = app.query_one(TextArea)
			md_widget = app.query_one(Markdown)

			assert editor._preview_mode is False
			assert text_area.styles.display != "none"
			assert md_widget.styles.display == "none"
	finally:
		os.unlink(path)


@pytest.mark.asyncio
async def test_toggle_to_preview_mode():
	"""Ctrl+P on a .md file shows the Markdown preview and hides the TextArea."""
	path = _make_md_file("# Title\n\n**bold** text\n")
	try:
		app = _EditorApp(path)
		async with app.run_test() as pilot:
			editor = app.query_one(FileEditor)
			text_area = app.query_one(TextArea)
			md_widget = app.query_one(Markdown)

			# Toggle to preview
			await pilot.press("ctrl+e")
			await pilot.pause()

			assert editor._preview_mode is True
			assert text_area.styles.display == "none"
			assert md_widget.styles.display != "none"
	finally:
		os.unlink(path)


@pytest.mark.asyncio
async def test_toggle_back_to_edit_mode():
	"""Ctrl+P again returns to edit mode and focuses the TextArea."""
	path = _make_md_file()
	try:
		app = _EditorApp(path)
		async with app.run_test() as pilot:
			editor = app.query_one(FileEditor)
			text_area = app.query_one(TextArea)
			md_widget = app.query_one(Markdown)

			# Enter preview
			await pilot.press("ctrl+e")
			await pilot.pause()
			assert editor._preview_mode is True

			# Back to edit
			await pilot.press("ctrl+e")
			await pilot.pause()

			assert editor._preview_mode is False
			assert text_area.styles.display != "none"
			assert md_widget.styles.display == "none"
			assert text_area.has_focus
	finally:
		os.unlink(path)


@pytest.mark.asyncio
async def test_non_markdown_file_toggle_is_noop():
	"""Ctrl+P on a .py file does nothing — stays in edit mode."""
	path = _make_py_file()
	try:
		app = _EditorApp(path)
		async with app.run_test() as pilot:
			editor = app.query_one(FileEditor)
			text_area = app.query_one(TextArea)
			md_widget = app.query_one(Markdown)

			await pilot.press("ctrl+e")
			await pilot.pause()

			assert editor._preview_mode is False
			assert text_area.styles.display != "none"
			assert md_widget.styles.display == "none"
	finally:
		os.unlink(path)


@pytest.mark.asyncio
async def test_preview_content_matches_editor_text():
	"""The rendered Markdown widget contains the same text as the TextArea."""
	content = "# Heading\n\nA paragraph with **bold**.\n"
	path = _make_md_file(content)
	try:
		app = _EditorApp(path)
		async with app.run_test() as pilot:
			text_area = app.query_one(TextArea)

			# Ensure the text area has the content loaded
			assert text_area.text == content

			# Toggle to preview
			await pilot.press("ctrl+e")
			await pilot.pause()

			md_widget = app.query_one(Markdown)
			# The Markdown widget's document should contain our text
			md_text = md_widget._markdown
			assert "# Heading" in md_text
			assert "A paragraph with **bold**." in md_text
	finally:
		os.unlink(path)


@pytest.mark.asyncio
async def test_suggestion_cleared_on_entering_preview():
	"""Entering preview mode clears any active AI suggestion."""
	path = _make_md_file()
	try:
		app = _EditorApp(path)
		async with app.run_test() as pilot:
			editor = app.query_one(FileEditor)

			# Simulate an active suggestion
			editor._full_suggestion = "some suggestion text"
			assert editor._has_active_suggestion()

			# Toggle to preview
			await pilot.press("ctrl+e")
			await pilot.pause()

			assert editor._full_suggestion is None
			assert not editor._has_active_suggestion()
	finally:
		os.unlink(path)


@pytest.mark.asyncio
async def test_ai_suggestion_request_is_noop_in_preview_mode():
	"""action_request_ai_suggestion does nothing in preview mode."""
	path = _make_md_file()
	try:
		app = _EditorApp(path)
		async with app.run_test() as pilot:
			editor = app.query_one(FileEditor)

			# Enter preview mode
			await pilot.press("ctrl+e")
			await pilot.pause()
			assert editor._preview_mode is True

			# This should be a no-op — no exception, no worker started
			editor.action_request_ai_suggestion()
			await pilot.pause()

			# No suggestion should have been set
			assert editor._full_suggestion is None
	finally:
		os.unlink(path)


@pytest.mark.asyncio
async def test_save_works_after_preview_round_trip():
	"""After toggling to preview and back, saving still writes correct content."""
	path = _make_md_file("# Original\n")
	new_content = "# Modified\n\nNew text\n"
	try:
		app = _EditorApp(path)
		async with app.run_test() as pilot:
			text_area = app.query_one(TextArea)

			# Modify content
			text_area.text = new_content

			# Toggle to preview and back
			await pilot.press("ctrl+e")
			await pilot.pause()
			await pilot.press("ctrl+e")
			await pilot.pause()

			# Save should work
			editor = app.query_one(FileEditor)
			result = editor.save_file()
			assert result is True

			# Verify file on disk
			with open(path, "r") as f:
				assert f.read() == new_content
	finally:
		os.unlink(path)