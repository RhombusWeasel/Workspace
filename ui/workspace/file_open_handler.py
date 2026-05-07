"""File open handler — opens files in workspace tabs.

Handles the ``files.open`` CodyEvent by creating a
:class:`~ui.workspace.tabs.WorkspaceTabs` in the focused workspace pane
and opening the file as a :class:`~ui.workspace.file_view.FileView` tab.

Registered at import time via ``@register_handler``.
"""

from __future__ import annotations

import os

from context import AppContext
from core.events import CodyEvent, register_handler
from ui.workspace.file_view import FileView
from ui.workspace.workspace import PaneContainer
from ui.workspace.tabs import WorkspaceTabs


@register_handler("files.open")
def _on_files_open(data: dict, ctx: AppContext) -> None:
    """Open a file in the workspace."""
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

    # Check if the container already has a WorkspaceTabs
    existing_tabs = None
    try:
        existing_tabs = container.query_one(WorkspaceTabs)
    except Exception:
        pass

    if existing_tabs is not None:
        # Open in existing tabs
        filename = os.path.basename(filepath)
        tab_id = f"file-{_path_to_tab_id(filepath)}"
        existing_tabs.open_tab(tab_id, filename, FileView(filepath))
    else:
        # Create new WorkspaceTabs and set as pane content
        tabs = WorkspaceTabs()
        filename = os.path.basename(filepath)
        tab_id = f"file-{_path_to_tab_id(filepath)}"
        async def _do() -> None:
            # Mount the tabs widget in the container
            await container.mount(tabs)
            tabs.open_tab(tab_id, filename, FileView(filepath))
        app.run_worker(_do())


def _path_to_tab_id(filepath: str) -> str:
    """Convert a filepath to a valid tab ID (no dots, no spaces)."""
    return os.path.basename(filepath).replace(".", "_").replace(" ", "_")