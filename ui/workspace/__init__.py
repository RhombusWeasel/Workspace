"""Workspace — recursively splitting pane container."""

from ui.workspace.workspace import Workspace, PaneContainer
from ui.workspace.tabs import WorkspaceTabs
from ui.workspace.file_editor import FileEditor
from ui.workspace.welcome_view import WelcomeView

__all__ = ["Workspace", "PaneContainer", "WorkspaceTabs", "FileEditor", "WelcomeView"]