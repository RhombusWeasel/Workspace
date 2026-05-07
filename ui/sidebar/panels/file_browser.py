"""File browser panel — sidebar tab for browsing project files.

Uses the generic Tree widget with lazy loading: directories are scanned
one level at a time when expanded.  Files and directories have inline
action buttons (open/edit, add, rename, delete).
"""

from __future__ import annotations

import hashlib
import os

from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.widgets import Button, Static

from core.events import CodyEvent
from ui.sidebar.registry import register_sidebar_tab
from ui.tree.tree import Tree, NodeNeedsChildren
from ui.tree.tree_row import TreeRow, RowButton, TreeNode
from utils.dom_id import path_to_id
from utils.icons import get_file_icon, get_folder_icon, EDIT, RENAME, DELETE, REFRESH, FOLDER_OPEN

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_OPEN = "open"
_ADD_FILE = "add_file"
_ADD_DIR = "add_dir"
_RENAME = "rename"
_DEL = "del"

# Directories and files to skip
_IGNORED_NAMES: set[str] = {
    "__pycache__",
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    ".venv",
    "venv",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "dist",
    "build",
    "*.egg-info",
    ".eggs",
    ".idea",
    ".vscode",
    ".DS_Store",
    "Thumbs.db",
}


def _file_buttons() -> list[RowButton]:
    return [
        RowButton(_OPEN, "Open", "btn-open"),
        RowButton(_RENAME, "Rename", "btn-rename"),
        RowButton(_DEL, "Del", "btn-del"),
    ]


def _dir_buttons() -> list[RowButton]:
    return [
        RowButton(_ADD_FILE, "+File", "btn-add-file"),
        RowButton(_ADD_DIR, "+Dir", "btn-add-dir"),
        RowButton(_RENAME, "Rename", "btn-rename"),
        RowButton(_DEL, "Del", "btn-del"),
    ]


# ---------------------------------------------------------------------------
# Panel
# ---------------------------------------------------------------------------


@register_sidebar_tab(name="files", icon="\ue795", side="left", tooltip="Files")
class FileBrowserPanel(Container):
    """Sidebar panel showing project directory structure.

    Uses lazy loading — only one level is scanned when a directory is
    expanded.  Clicking expand on an unloaded directory triggers
    ``NodeNeedsChildren`` which this panel handles by scanning the
    directory, adding children, and refreshing the tree.

    Actions:
    - **Open**: Posts ``CodyEvent("files.open")`` with the file path.
    - **Add File**: Creates an empty file in the selected directory.
    - **Add Dir**: Creates a new directory.
    - **Rename**: Renames a file or directory on disk.
    - **Delete**: Deletes a file or directory after confirmation.
    - **Refresh**: Rescans the working directory from scratch.
    """

    def __init__(self, working_directory: str | None = None):
        super().__init__()
        self._wd = working_directory or os.getcwd()

    # ------------------------------------------------------------------
    # Compose
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Static("\uf07c  Files", classes="section-header")
        self._tree = Tree(TreeNode("fb-root", "Loading..."))
        yield self._tree
        with Horizontal(classes="file-browser-actions"):
            yield Button("+ File", id="fb-new-file", variant="default")
            yield Button("+ Dir", id="fb-new-dir", variant="default")
            yield Button(REFRESH, id="fb-refresh", variant="default")

    def on_mount(self) -> None:
        # Override working directory from AppContext if available
        app = self.app
        if hasattr(app, "context") and app.context is not None:
            self._wd = app.context.working_directory or self._wd
        self._rebuild()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def working_directory(self) -> str:
        return self._wd

    def refresh_tree(self) -> None:
        """Rescan the working directory and rebuild the tree from scratch."""
        self._rebuild()

    # ------------------------------------------------------------------
    # Tree building (lazy)
    # ------------------------------------------------------------------

    def _rebuild(self) -> None:
        """Scan the top level of the working directory and set as tree root."""
        root_label = os.path.basename(self._wd) or self._wd
        children = self._scan_dir(self._wd)
        root = TreeNode(
            path_to_id("fb", self._wd),
            f"{get_folder_icon(self._wd)}  {root_label}",
            children=children,
            data={"path": self._wd, "type": "dir", "name": root_label},
            buttons=_dir_buttons(),
        )
        self._tree.set_root(root)
        self._tree.expand_node(root.id)

    def _scan_dir(self, dirpath: str) -> list[TreeNode]:
        """Scan *dirpath* one level deep and return child TreeNodes.

        Directories are created as lazy nodes (``loaded=False``).
        Files are created as leaf nodes with action buttons.
        """
        try:
            entries = sorted(os.listdir(dirpath))
        except PermissionError:
            return []

        nodes: list[TreeNode] = []
        for name in entries:
            # Skip ignored names and hidden files (starting with .)
            if name in _IGNORED_NAMES or name.startswith("."):
                continue

            full_path = os.path.join(dirpath, name)
            if not os.path.exists(full_path):
                continue

            is_dir = os.path.isdir(full_path)
            node_id = path_to_id("fb", full_path)

            if is_dir:
                icon = get_folder_icon(name)
                nodes.append(TreeNode(
                    node_id,
                    f"{icon}  {name}",
                    children=[],  # not loaded yet
                    loaded=False,
                    data={"path": full_path, "type": "dir", "name": name},
                    buttons=_dir_buttons(),
                ))
            else:
                icon = get_file_icon(name)
                nodes.append(TreeNode(
                    node_id,
                    f"{icon}  {name}",
                    data={"path": full_path, "type": "file", "name": name},
                    buttons=_file_buttons(),
                ))

        return nodes

    # ------------------------------------------------------------------
    # Lazy loading handler
    # ------------------------------------------------------------------

    def on_node_needs_children(self, msg: NodeNeedsChildren) -> None:
        """Load children for a lazy directory node."""
        msg.stop()
        path = msg.node.data.get("path", "")
        if not path or not os.path.isdir(path):
            return

        children = self._scan_dir(path)
        msg.node.children = children
        msg.node.loaded = True
        self._tree.rebuild()
        self._tree.expand_node(msg.node_id)

    # ------------------------------------------------------------------
    # Button handlers — root actions
    # ------------------------------------------------------------------

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        btn_id = event.button.id

        if btn_id == "fb-new-file":
            self._prompt_add_file(self._wd)
        elif btn_id == "fb-new-dir":
            self._prompt_add_dir(self._wd)
        elif btn_id == "fb-refresh":
            self._rebuild()

    # ------------------------------------------------------------------
    # ActionRow button handlers — per-node actions
    # ------------------------------------------------------------------

    def on_tree_row_button_pressed(self, event: TreeRow.ButtonPressed) -> None:
        """Handle inline button presses on tree nodes."""
        event.stop()
        action = event.action_id
        node = event.node
        path = node.data.get("path", "")
        ntype = node.data.get("type", "")

        if action == _OPEN:
            self._open_file(path)
        elif action == _ADD_FILE and ntype == "dir":
            self._prompt_add_file(path)
        elif action == _ADD_DIR and ntype == "dir":
            self._prompt_add_dir(path)
        elif action == _RENAME:
            self._prompt_rename(path, node.data.get("name", ""))
        elif action == _DEL:
            self._prompt_delete(path, node.data.get("name", ""))

    # ------------------------------------------------------------------
    # Actions — Open
    # ------------------------------------------------------------------

    def _open_file(self, path: str) -> None:
        """Post a files.open event with the file path."""
        self.post_message(CodyEvent("files.open", {"path": path}))

    # ------------------------------------------------------------------
    # Actions — Add File
    # ------------------------------------------------------------------

    def _prompt_add_file(self, dir_path: str) -> None:
        """Prompt for a new file name and create it."""
        from ui.widgets.input_modal import InputModal

        async def do_add() -> None:
            modal = InputModal("New file name:", "Filename")
            result = await self.app.push_screen_wait(modal)
            if not result:
                return
            filepath = os.path.join(dir_path, result)
            try:
                # Create empty file (or touch existing)
                with open(filepath, "a"):
                    os.utime(filepath, None)
            except OSError:
                return
            self._rebuild()

        self.app.run_worker(do_add())

    # ------------------------------------------------------------------
    # Actions — Add Directory
    # ------------------------------------------------------------------

    def _prompt_add_dir(self, dir_path: str) -> None:
        """Prompt for a new directory name and create it."""
        from ui.widgets.input_modal import InputModal

        async def do_add() -> None:
            modal = InputModal("New directory name:", "Dirname")
            result = await self.app.push_screen_wait(modal)
            if not result:
                return
            dirpath = os.path.join(dir_path, result)
            try:
                os.makedirs(dirpath, exist_ok=True)
            except OSError:
                return
            self._rebuild()

        self.app.run_worker(do_add())

    # ------------------------------------------------------------------
    # Actions — Rename
    # ------------------------------------------------------------------

    def _prompt_rename(self, path: str, old_name: str) -> None:
        """Prompt for a new name and rename on disk."""
        from ui.widgets.input_modal import InputModal

        async def do_rename() -> None:
            modal = InputModal("Rename:", "New name", default=old_name)
            result = await self.app.push_screen_wait(modal)
            if not result or result == old_name:
                return
            parent = os.path.dirname(path)
            new_path = os.path.join(parent, result)
            try:
                os.rename(path, new_path)
            except OSError:
                return
            self._rebuild()

        self.app.run_worker(do_rename())

    # ------------------------------------------------------------------
    # Actions — Delete
    # ------------------------------------------------------------------

    def _prompt_delete(self, path: str, name: str) -> None:
        """Prompt for confirmation and delete on disk."""
        from ui.widgets.input_modal import InputModal

        async def do_delete() -> None:
            modal = InputModal(f"Delete '{name}'? Type 'yes' to confirm:", "Confirm")
            result = await self.app.push_screen_wait(modal)
            if result != "yes":
                return
            try:
                if os.path.isdir(path):
                    import shutil
                    shutil.rmtree(path)
                else:
                    os.remove(path)
            except OSError:
                return
            self._rebuild()

        self.app.run_worker(do_delete())