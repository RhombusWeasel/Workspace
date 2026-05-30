"""Tests for FileBrowserPanel — sidebar panel for browsing project files."""

import os
import shutil
import pytest
import tempfile
from textual.app import App, ComposeResult

from textual.widgets import Button

from ui.sidebar.panels.file_browser import FileBrowserPanel, _IGNORED_NAMES
from ui.tree.tree import Tree, NodeSelected
from ui.tree.tree_row import TreeNode, TreeRow


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_test_dir():
    """Create a temp directory structure for testing.
    
    tmpdir/
    ├── src/
    │   ├── main.py
    │   └── utils.py
    ├── tests/
    │   └── test_main.py
    ├── README.md
    └── pyproject.toml
    """
    tmpdir = tempfile.mkdtemp()
    src_dir = os.path.join(tmpdir, "src")
    tests_dir = os.path.join(tmpdir, "tests")
    os.makedirs(src_dir)
    os.makedirs(tests_dir)
    
    with open(os.path.join(src_dir, "main.py"), "w") as f:
        f.write("print('hello')")
    with open(os.path.join(src_dir, "utils.py"), "w") as f:
        f.write("def helper(): pass")
    with open(os.path.join(tests_dir, "test_main.py"), "w") as f:
        f.write("def test_it(): pass")
    with open(os.path.join(tmpdir, "README.md"), "w") as f:
        f.write("# Test Project")
    with open(os.path.join(tmpdir, "pyproject.toml"), "w") as f:
        f.write("[project]\nname = 'test'\n")
    
    return tmpdir


def _create_test_dir_with_gitignore():
    """Create a temp dir with a .git directory (should be ignored)."""
    tmpdir = tempfile.mkdtemp()
    git_dir = os.path.join(tmpdir, ".git")
    os.makedirs(git_dir)
    with open(os.path.join(git_dir, "HEAD"), "w") as f:
        f.write("ref: refs/heads/main\n")
    with open(os.path.join(tmpdir, "hello.py"), "w") as f:
        f.write("print('hi')")
    
    return tmpdir


def _create_test_dir_with_hidden():
    """Create a temp dir with hidden files and directories.

    tmpdir/
    ├── .env
    ├── .github/
    │   └── workflows/
    ├── .gitignore
    ├── .hidden_dir/
    │   └── secret.py
    ├── src/
    │   └── main.py
    └── app.py
    """
    tmpdir = tempfile.mkdtemp()
    github_dir = os.path.join(tmpdir, ".github", "workflows")
    hidden_dir = os.path.join(tmpdir, ".hidden_dir")
    src_dir = os.path.join(tmpdir, "src")

    os.makedirs(github_dir)
    os.makedirs(hidden_dir)
    os.makedirs(src_dir)

    with open(os.path.join(tmpdir, ".env"), "w") as f:
        f.write("KEY=value\n")
    with open(os.path.join(tmpdir, ".gitignore"), "w") as f:
        f.write("*.pyc\n")
    with open(os.path.join(hidden_dir, "secret.py"), "w") as f:
        f.write("secret = True\n")
    with open(os.path.join(src_dir, "main.py"), "w") as f:
        f.write("print('main')\n")
    with open(os.path.join(tmpdir, "app.py"), "w") as f:
        f.write("print('app')\n")

    return tmpdir


def _make_panel():
    """Create a FileBrowserPanel without mounting (for unit tests).

    Uses ``__new__`` to skip Textual compose, then sets required
    attributes so that ``_scan_dir`` works in isolation.
    """
    panel = FileBrowserPanel.__new__(FileBrowserPanel)
    panel._show_hidden = False
    return panel


# ---------------------------------------------------------------------------
# Directory scanning
# ---------------------------------------------------------------------------


class TestScanDirectory:
    def test_scan_finds_files_and_dirs(self):
        """_scan_dir finds both files and directories."""
        tmpdir = _create_test_dir()
        try:
            panel = _make_panel()
            nodes = panel._scan_dir(tmpdir)
            labels = [n.label for n in nodes]
            # Should find src/, tests/, README.md, pyproject.toml
            assert len(nodes) == 4
            assert any("src" in l for l in labels)
            assert any("tests" in l for l in labels)
            assert any("README" in l for l in labels)
        finally:
            shutil.rmtree(tmpdir)

    def test_scan_creates_lazy_nodes_for_dirs(self):
        """Directories are created as lazy branch nodes (loaded=False)."""
        tmpdir = _create_test_dir()
        try:
            panel = _make_panel()
            nodes = panel._scan_dir(tmpdir)
            src_node = [n for n in nodes if "src" in n.label][0]
            assert not src_node.loaded  # Lazy — not yet scanned
            assert src_node.data["type"] == "dir"
        finally:
            shutil.rmtree(tmpdir)

    def test_scan_creates_leaf_nodes_for_files(self):
        """Files are created as leaf nodes with action buttons."""
        tmpdir = _create_test_dir()
        try:
            panel = _make_panel()
            nodes = panel._scan_dir(tmpdir)
            readme_node = [n for n in nodes if "README" in n.label][0]
            assert readme_node.data["type"] == "file"
            assert len(readme_node.buttons) > 0
        finally:
            shutil.rmtree(tmpdir)

    def test_scan_ignores_hidden_dirs(self):
        """Hidden directories (.git, etc.) are ignored when show_hidden=False."""
        tmpdir = _create_test_dir_with_gitignore()
        try:
            panel = _make_panel()
            nodes = panel._scan_dir(tmpdir)
            labels = [n.label for n in nodes]
            assert not any(".git" in l for l in labels)
            # hello.py should still be found
            assert any("hello" in l for l in labels)
        finally:
            shutil.rmtree(tmpdir)

    def test_scan_file_icons(self):
        """Files get appropriate icons in their labels."""
        tmpdir = _create_test_dir()
        try:
            panel = _make_panel()
            nodes = panel._scan_dir(tmpdir)
            # Check that file nodes have icons (non-empty labels)
            file_nodes = [n for n in nodes if n.data.get("type") == "file"]
            assert len(file_nodes) >= 2  # README.md and pyproject.toml
            for fn in file_nodes:
                assert fn.label  # Label should be non-empty (has icon + name)
        finally:
            shutil.rmtree(tmpdir)

    def test_scan_sorts_entries_by_name(self):
        """Entries are sorted directories-first, then alphabetically by name."""
        tmpdir = _create_test_dir()
        try:
            panel = _make_panel()
            nodes = panel._scan_dir(tmpdir)
            names = [n.data.get("name", "") for n in nodes]
            # Dirs come first, then files. Within each group,
            # case-insensitive alphabetical (matching .lower() sort).
            dir_names = [n for n in names if os.path.isdir(os.path.join(tmpdir, n))]
            file_names = [n for n in names if not os.path.isdir(os.path.join(tmpdir, n))]
            assert dir_names == sorted(dir_names, key=str.casefold)
            assert file_names == sorted(file_names, key=str.casefold)
            # All dirs precede all files.
            last_dir_idx = max(names.index(d) for d in dir_names) if dir_names else -1
            first_file_idx = min(names.index(f) for f in file_names) if file_names else len(names)
            assert last_dir_idx < first_file_idx
        finally:
            shutil.rmtree(tmpdir)

    def test_scan_sorts_by_name_not_label(self):
        """Sorting uses the node's name, not its label (which includes an icon).

        Labels have icon prefixes like '  src' that would break
        alphabetical order if used as the sort key.
        """
        tmpdir = _create_test_dir()
        try:
            panel = _make_panel()
            nodes = panel._scan_dir(tmpdir)
            # All names should be in proper alphabetical order within their group
            dir_names = [n.data["name"] for n in nodes if n.data["type"] == "dir"]
            file_names = [n.data["name"] for n in nodes if n.data["type"] == "file"]
            assert dir_names == sorted(dir_names, key=str.casefold)
            assert file_names == sorted(file_names, key=str.casefold)
        finally:
            shutil.rmtree(tmpdir)

    def test_scan_empty_dir(self):
        """Scanning an empty directory returns no nodes."""
        tmpdir = tempfile.mkdtemp()
        try:
            panel = _make_panel()
            nodes = panel._scan_dir(tmpdir)
            assert nodes == []
        finally:
            shutil.rmtree(tmpdir)

    def test_scan_dir_nodes_have_add_buttons(self):
        """Directory nodes have Add File and Add Dir buttons."""
        tmpdir = _create_test_dir()
        try:
            panel = _make_panel()
            nodes = panel._scan_dir(tmpdir)
            src_node = [n for n in nodes if "src" in n.label][0]
            action_ids = [b.action_id for b in src_node.buttons]
            assert "add_file" in action_ids
            assert "add_dir" in action_ids
        finally:
            shutil.rmtree(tmpdir)

    def test_scan_file_nodes_have_rename_and_delete_buttons(self):
        """File nodes have Rename and Delete buttons (Edit removed — click label to open)."""
        tmpdir = _create_test_dir()
        try:
            panel = _make_panel()
            nodes = panel._scan_dir(tmpdir)
            readme_node = [n for n in nodes if "README" in n.label][0]
            action_ids = [b.action_id for b in readme_node.buttons]
            assert "rename" in action_ids
            assert "del" in action_ids
            assert "edit" not in action_ids  # Edit button removed; click label to open
        finally:
            shutil.rmtree(tmpdir)


# ---------------------------------------------------------------------------
# Show hidden toggle
# ---------------------------------------------------------------------------


class TestShowHidden:
    def test_hidden_entries_excluded_by_default(self):
        """When show_hidden=False, entries starting with . are excluded."""
        tmpdir = _create_test_dir_with_hidden()
        try:
            panel = _make_panel()
            panel._show_hidden = False
            nodes = panel._scan_dir(tmpdir)
            names = [n.data.get("name", "") for n in nodes]
            # Hidden entries should not appear
            assert ".env" not in names
            assert ".gitignore" not in names
            assert ".hidden_dir" not in names
            assert ".github" not in names
            # Regular entries should appear
            assert "src" in names
            assert "app.py" in names
        finally:
            shutil.rmtree(tmpdir)

    def test_hidden_entries_included_when_toggled_on(self):
        """When show_hidden=True, entries starting with . are included."""
        tmpdir = _create_test_dir_with_hidden()
        try:
            panel = _make_panel()
            panel._show_hidden = True
            nodes = panel._scan_dir(tmpdir)
            names = [n.data.get("name", "") for n in nodes]
            # Hidden entries should now appear
            assert ".env" in names
            assert ".gitignore" in names
            assert ".hidden_dir" in names
            assert ".github" in names
            # Regular entries should still be there
            assert "src" in names
            assert "app.py" in names
        finally:
            shutil.rmtree(tmpdir)

    def test_ignored_names_always_excluded_even_with_show_hidden(self):
        """Entries in _IGNORED_NAMES are excluded even when show_hidden=True.

        .git is both a dot-entry AND in _IGNORED_NAMES.  Even with
        show_hidden=True it must remain hidden because it is explicitly
        ignored.
        """
        tmpdir = _create_test_dir_with_gitignore()
        try:
            panel = _make_panel()
            panel._show_hidden = True
            nodes = panel._scan_dir(tmpdir)
            names = [n.data.get("name", "") for n in nodes]
            # .git is in _IGNORED_NAMES — should be excluded even with show_hidden=True
            assert ".git" not in names
            # hello.py should still appear
            assert "hello.py" in names
        finally:
            shutil.rmtree(tmpdir)

    def test_hidden_dirs_are_lazy_nodes(self):
        """Hidden directories, when shown, are lazy branch nodes."""
        tmpdir = _create_test_dir_with_hidden()
        try:
            panel = _make_panel()
            panel._show_hidden = True
            nodes = panel._scan_dir(tmpdir)
            hidden_dir_node = [n for n in nodes if n.data.get("name") == ".hidden_dir"]
            assert len(hidden_dir_node) == 1
            assert hidden_dir_node[0].loaded is False
            assert hidden_dir_node[0].data["type"] == "dir"
        finally:
            shutil.rmtree(tmpdir)

    def test_hidden_files_sort_alphabetically(self):
        """Hidden entries should be sorted alphabetically among regular entries."""
        tmpdir = _create_test_dir_with_hidden()
        try:
            panel = _make_panel()
            panel._show_hidden = True
            nodes = panel._scan_dir(tmpdir)
            names = [n.data.get("name", "") for n in nodes]
            # Dirs should be first (including .github, .hidden_dir, src), sorted alphabetically
            dir_names = [n for n in names if os.path.isdir(os.path.join(tmpdir, n))]
            file_names = [n for n in names if not os.path.isdir(os.path.join(tmpdir, n))]
            assert dir_names == sorted(dir_names, key=str.casefold)
            assert file_names == sorted(file_names, key=str.casefold)
        finally:
            shutil.rmtree(tmpdir)

    async def test_toggle_hidden_flips_state(self):
        """_toggle_hidden flips _show_hidden and updates the button label."""
        tmpdir = _create_test_dir()
        try:
            class FBApp(App):
                CSS = "FileBrowserPanel { width: 40; height: 100%; }"

                def compose(self) -> ComposeResult:
                    self.panel = FileBrowserPanel(working_directory=tmpdir)
                    yield self.panel

            async with FBApp().run_test() as pilot:
                await pilot.pause()
                panel = pilot.app.panel
                from utils.icons import EYE, EYE_OFF
                btn = panel.query_one("#fb-show-hidden", Button)

                # Initially hidden
                assert panel._show_hidden is False
                assert btn.label == EYE_OFF

                # Toggle on
                panel._toggle_hidden()
                assert panel._show_hidden is True
                assert btn.label == EYE

                # Toggle off
                panel._toggle_hidden()
                assert panel._show_hidden is False
                assert btn.label == EYE_OFF
        finally:
            shutil.rmtree(tmpdir)


# ---------------------------------------------------------------------------
# File browser panel rendering
# ---------------------------------------------------------------------------


class TestFileBrowserPanelRendering:
    async def test_panel_composes_tree(self):
        """FileBrowserPanel renders a Tree widget."""
        tmpdir = _create_test_dir()
        try:
            class FBApp(App):
                CSS = "FileBrowserPanel { width: 40; height: 100%; }"

                def compose(self) -> ComposeResult:
                    self.panel = FileBrowserPanel(working_directory=tmpdir)
                    yield self.panel

            async with FBApp().run_test() as pilot:
                await pilot.pause()
                tree = pilot.app.panel.query_one(Tree)
                assert tree is not None
                assert len(tree.root.children) > 0
        finally:
            shutil.rmtree(tmpdir)

    async def test_panel_shows_root_as_working_dir(self):
        """The root node label includes the working directory name."""
        tmpdir = _create_test_dir()
        try:
            class FBApp(App):
                CSS = "FileBrowserPanel { width: 40; height: 100%; }"

                def compose(self) -> ComposeResult:
                    self.panel = FileBrowserPanel(working_directory=tmpdir)
                    yield self.panel

            async with FBApp().run_test() as pilot:
                await pilot.pause()
                tree = pilot.app.panel.query_one(Tree)
                assert tree.root.label  # Non-empty
        finally:
            shutil.rmtree(tmpdir)

    async def test_dir_nodes_are_lazy(self):
        """Directory nodes are created as lazy (loaded=False)."""
        tmpdir = _create_test_dir()
        try:
            class FBApp(App):
                CSS = "FileBrowserPanel { width: 40; height: 100%; }"

                def compose(self) -> ComposeResult:
                    self.panel = FileBrowserPanel(working_directory=tmpdir)
                    yield self.panel

            async with FBApp().run_test() as pilot:
                await pilot.pause()
                tree = pilot.app.panel.query_one(Tree)
                src_nodes = [c for c in tree.root.children if "src" in c.label]
                assert len(src_nodes) == 1
                assert src_nodes[0].loaded is False
        finally:
            shutil.rmtree(tmpdir)

    async def test_file_nodes_have_rename_delete_buttons(self):
        """File nodes have Rename and Delete buttons, not Edit."""
        tmpdir = _create_test_dir()
        try:
            class FBApp(App):
                CSS = "FileBrowserPanel { width: 40; height: 100%; }"

                def compose(self) -> ComposeResult:
                    self.panel = FileBrowserPanel(working_directory=tmpdir)
                    yield self.panel

            async with FBApp().run_test() as pilot:
                await pilot.pause()
                tree = pilot.app.panel.query_one(Tree)
                file_nodes = [c for c in tree.root.children if c.data.get("type") == "file"]
                assert len(file_nodes) > 0
                action_ids = [b.action_id for b in file_nodes[0].buttons]
                assert "rename" in action_ids
                assert "del" in action_ids
                assert "edit" not in action_ids
        finally:
            shutil.rmtree(tmpdir)

    async def test_dir_nodes_have_buttons(self):
        """Directory nodes have action buttons."""
        tmpdir = _create_test_dir()
        try:
            class FBApp(App):
                CSS = "FileBrowserPanel { width: 40; height: 100%; }"

                def compose(self) -> ComposeResult:
                    self.panel = FileBrowserPanel(working_directory=tmpdir)
                    yield self.panel

            async with FBApp().run_test() as pilot:
                await pilot.pause()
                tree = pilot.app.panel.query_one(Tree)
                dir_nodes = [c for c in tree.root.children if c.data.get("type") == "dir"]
                assert len(dir_nodes) > 0
                assert len(dir_nodes[0].buttons) > 0
        finally:
            shutil.rmtree(tmpdir)

    async def test_lazy_loading_expands_dir(self):
        """Expanding a lazy directory loads its children."""
        tmpdir = _create_test_dir()
        try:
            class FBApp(App):
                CSS = "FileBrowserPanel { width: 40; height: 100%; }"

                def compose(self) -> ComposeResult:
                    self.panel = FileBrowserPanel(working_directory=tmpdir)
                    yield self.panel

            async with FBApp().run_test() as pilot:
                await pilot.pause()
                tree = pilot.app.panel.query_one(Tree)
                
                # Find the src directory
                src_nodes = [c for c in tree.root.children if "src" in c.label]
                assert len(src_nodes) == 1
                src_id = src_nodes[0].id
                
                # Expand it (triggers NodeNeedsChildren → handler loads children)
                tree.expand_node(src_id)
                await pilot.pause()
                
                # After loading, src should have children
                src_node = tree._node_map.get(src_id)
                assert src_node is not None
                assert src_node.loaded is True
                assert len(src_node.children) > 0
                # Should contain main.py and utils.py
                child_labels = [c.label for c in src_node.children]
                assert any("main.py" in l for l in child_labels)
                assert any("utils.py" in l for l in child_labels)
        finally:
            shutil.rmtree(tmpdir)

    async def test_show_hidden_toggle_button_exists(self):
        """The panel has a show-hidden toggle button."""
        tmpdir = _create_test_dir()
        try:
            class FBApp(App):
                CSS = "FileBrowserPanel { width: 40; height: 100%; }"

                def compose(self) -> ComposeResult:
                    self.panel = FileBrowserPanel(working_directory=tmpdir)
                    yield self.panel

            async with FBApp().run_test() as pilot:
                await pilot.pause()
                from utils.icons import EYE_OFF
                btn = pilot.app.panel.query_one("#fb-show-hidden", Button)
                assert btn is not None
                assert btn.label == EYE_OFF
        finally:
            shutil.rmtree(tmpdir)

    async def test_click_file_label_opens_for_editing(self):
        """Clicking a file label (NodeSelected) posts a files.edit event."""
        tmpdir = _create_test_dir()
        try:
            events_fired = []

            class FBApp(App):
                CSS = "FileBrowserPanel { width: 40; height: 100%; }"

                def compose(self) -> ComposeResult:
                    self.panel = FileBrowserPanel(working_directory=tmpdir)
                    yield self.panel

                def on_workspace_event(self, event) -> None:
                    events_fired.append(event)

            async with FBApp().run_test() as pilot:
                await pilot.pause()
                tree = pilot.app.panel.query_one(Tree)
                file_nodes = [c for c in tree.root.children if c.data.get("type") == "file"]
                assert len(file_nodes) > 0

                # Select a file node — this posts NodeSelected, which the
                # panel handles by posting WorkspaceEvent("files.edit", ...)
                tree.select_node(file_nodes[0].id)
                await pilot.pause()

                # Should have fired a files.edit event
                edit_events = [e for e in events_fired if e.event_type == "files.edit"]
                assert len(edit_events) == 1
                assert edit_events[0].data.get("path") == file_nodes[0].data["path"]
        finally:
            shutil.rmtree(tmpdir)

    async def test_click_dir_label_does_not_open(self):
        """Clicking a directory label (Toggled) does NOT post a files.edit event."""
        tmpdir = _create_test_dir()
        try:
            events_fired = []

            class FBApp(App):
                CSS = "FileBrowserPanel { width: 40; height: 100%; }"

                def compose(self) -> ComposeResult:
                    self.panel = FileBrowserPanel(working_directory=tmpdir)
                    yield self.panel

                def on_workspace_event(self, event) -> None:
                    events_fired.append(event)

            async with FBApp().run_test() as pilot:
                await pilot.pause()
                tree = pilot.app.panel.query_one(Tree)
                dir_nodes = [c for c in tree.root.children if c.data.get("type") == "dir"]
                assert len(dir_nodes) > 0

                # Toggle a directory node — expands it, should NOT post files.edit
                tree.toggle_node(dir_nodes[0].id)
                await pilot.pause()

                edit_events = [e for e in events_fired if e.event_type == "files.edit"]
                assert len(edit_events) == 0
        finally:
            shutil.rmtree(tmpdir)


# ---------------------------------------------------------------------------
# Ignore list
# ---------------------------------------------------------------------------


class TestIgnoredNames:
    def test_common_ignored_names(self):
        """Common directories and files are in the ignore list."""
        assert "__pycache__" in _IGNORED_NAMES
        assert ".git" in _IGNORED_NAMES
        assert "node_modules" in _IGNORED_NAMES
        assert ".venv" in _IGNORED_NAMES

    def test_ignored_in_scan(self):
        """Ignored names are filtered out during scanning."""
        tmpdir = tempfile.mkdtemp()
        try:
            pycache = os.path.join(tmpdir, "__pycache__")
            os.makedirs(pycache)
            with open(os.path.join(pycache, "test.pyc"), "w") as f:
                f.write("")
            with open(os.path.join(tmpdir, "app.py"), "w") as f:
                f.write("")
            
            panel = _make_panel()
            nodes = panel._scan_dir(tmpdir)
            labels = [n.label for n in nodes]
            assert not any("__pycache__" in l for l in labels)
            assert any("app.py" in l for l in labels)
        finally:
            shutil.rmtree(tmpdir)