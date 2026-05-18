"""File edit handler — opens files in workspace tabs for editing.

Handles the ``files.edit`` CodyEvent by creating a
:class:`~ui.workspace.tabs.WorkspaceTabs` in the focused workspace pane
and opening the file as a :class:`~ui.workspace.file_editor.FileEditor` tab
with syntax highlighting and editing support.

Registered at import time via ``@register_handler``.
"""

from __future__ import annotations

import os

from context import AppContext
from core.events import CodyEvent, register_handler
from ui.workspace.file_editor import FileEditor, FileEditorState
from ui.workspace.workspace import PaneContainer
from ui.workspace.tabs import WorkspaceTabs
from utils.dom_id import path_to_id


@register_handler("files.edit")
def _on_files_edit(data: dict, ctx: AppContext) -> None:
    """Open a file in the editor workspace."""
    filepath = data.get("path", "")
    if not filepath or not os.path.isfile(filepath):
        return

    app = ctx.app
    if app is None:
        return

    try:
        ws = app.query_one("#workspace")
    except Exception:
        return

    # Find the focused pane container
    focused_id = ws.focused_id
    try:
        container = app.query_one(f"#pane-{focused_id}", PaneContainer)
    except Exception:
        return

    # Check if the container already has WorkspaceTabs
    existing_tabs = None
    try:
        existing_tabs = container.query_one(WorkspaceTabs)
    except Exception:
        pass

    filename = os.path.basename(filepath)
    tab_id = path_to_id("file", filepath)

    # Create the persistent state for this tab.
    state = FileEditorState(filepath)

    # Factory that recreates the FileEditor — receives the same state.
    def _make_file_editor(s: FileEditorState) -> FileEditor:
        return FileEditor(s)

    if existing_tabs is not None:
        # Open in existing tabs
        existing_tabs.open_tab(tab_id, filename, state=state, content_factory=_make_file_editor)
    else:
        # Create new WorkspaceTabs and set as pane content
        tabs = WorkspaceTabs()

        async def _do() -> None:
            # Mount the tabs widget in the container
            await container.mount(tabs)
            tabs.open_tab(tab_id, filename, state=state, content_factory=_make_file_editor)

        app.run_worker(_do())