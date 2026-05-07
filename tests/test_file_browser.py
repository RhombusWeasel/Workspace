"""Tests for FileBrowserPanel — sidebar panel for browsing project files."""

import os
import shutil
import pytest
import tempfile
from textual.app import App, ComposeResult

from ui.sidebar.panels.file_browser import FileBrowserPanel, _IGNORED_NAMES
from ui.tree.tree import Tree
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


# ---------------------------------------------------------------------------
# Directory scanning
# ---------------------------------------------------------------------------


class TestScanDirectory:
    def test_scan_finds_files_and_dirs(self):
        """_scan_dir finds both files and directories."""
        from ui.sidebar.panels.file_browser import FileBrowserPanel
        tmpdir = _create_test_dir()
        try:
            panel = FileBrowserPanel.__new__(FileBrowserPanel)
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
        from ui.sidebar.panels.file_browser import FileBrowserPanel
        tmpdir = _create_test_dir()
        try:
            panel = FileBrowserPanel.__new__(FileBrowserPanel)
            nodes = panel._scan_dir(tmpdir)
            src_node = [n for n in nodes if "src" in n.label][0]
            assert not src_node.loaded  # Lazy — not yet scanned
            assert src_node.data["type"] == "dir"
        finally:
            shutil.rmtree(tmpdir)

    def test_scan_creates_leaf_nodes_for_files(self):
        """Files are created as leaf nodes with action buttons."""
        from ui.sidebar.panels.file_browser import FileBrowserPanel
        tmpdir = _create_test_dir()
        try:
            panel = FileBrowserPanel.__new__(FileBrowserPanel)
            nodes = panel._scan_dir(tmpdir)
            readme_node = [n for n in nodes if "README" in n.label][0]
            assert readme_node.data["type"] == "file"
            assert len(readme_node.buttons) > 0
        finally:
            shutil.rmtree(tmpdir)

    def test_scan_ignores_hidden_dirs(self):
        """Hidden directories (.git, etc.) are ignored."""
        from ui.sidebar.panels.file_browser import FileBrowserPanel
        tmpdir = _create_test_dir_with_gitignore()
        try:
            panel = FileBrowserPanel.__new__(FileBrowserPanel)
            nodes = panel._scan_dir(tmpdir)
            labels = [n.label for n in nodes]
            assert not any(".git" in l for l in labels)
            # hello.py should still be found
            assert any("hello" in l for l in labels)
        finally:
            shutil.rmtree(tmpdir)

    def test_scan_file_icons(self):
        """Files get appropriate icons in their labels."""
        from ui.sidebar.panels.file_browser import FileBrowserPanel
        tmpdir = _create_test_dir()
        try:
            panel = FileBrowserPanel.__new__(FileBrowserPanel)
            nodes = panel._scan_dir(tmpdir)
            # Check that file nodes have icons (non-empty labels)
            file_nodes = [n for n in nodes if n.data.get("type") == "file"]
            assert len(file_nodes) >= 2  # README.md and pyproject.toml
            for fn in file_nodes:
                assert fn.label  # Label should be non-empty (has icon + name)
        finally:
            shutil.rmtree(tmpdir)

    def test_scan_sorts_entries(self):
        """Entries are sorted alphabetically."""
        from ui.sidebar.panels.file_browser import FileBrowserPanel
        tmpdir = _create_test_dir()
        try:
            panel = FileBrowserPanel.__new__(FileBrowserPanel)
            nodes = panel._scan_dir(tmpdir)
            names = [n.data.get("name", "") for n in nodes]
            assert names == sorted(names)
        finally:
            shutil.rmtree(tmpdir)

    def test_scan_empty_dir(self):
        """Scanning an empty directory returns no nodes."""
        from ui.sidebar.panels.file_browser import FileBrowserPanel
        tmpdir = tempfile.mkdtemp()
        try:
            panel = FileBrowserPanel.__new__(FileBrowserPanel)
            nodes = panel._scan_dir(tmpdir)
            assert nodes == []
        finally:
            shutil.rmtree(tmpdir)

    def test_scan_dir_nodes_have_add_buttons(self):
        """Directory nodes have Add File and Add Dir buttons."""
        from ui.sidebar.panels.file_browser import FileBrowserPanel
        tmpdir = _create_test_dir()
        try:
            panel = FileBrowserPanel.__new__(FileBrowserPanel)
            nodes = panel._scan_dir(tmpdir)
            src_node = [n for n in nodes if "src" in n.label][0]
            action_ids = [b.action_id for b in src_node.buttons]
            assert "add_file" in action_ids
            assert "add_dir" in action_ids
        finally:
            shutil.rmtree(tmpdir)

    def test_scan_file_nodes_have_open_button(self):
        """File nodes have an Open button."""
        from ui.sidebar.panels.file_browser import FileBrowserPanel
        tmpdir = _create_test_dir()
        try:
            panel = FileBrowserPanel.__new__(FileBrowserPanel)
            nodes = panel._scan_dir(tmpdir)
            readme_node = [n for n in nodes if "README" in n.label][0]
            action_ids = [b.action_id for b in readme_node.buttons]
            assert "open" in action_ids
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

    async def test_file_nodes_have_buttons(self):
        """File nodes have action buttons."""
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
                assert len(file_nodes[0].buttons) > 0
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
        from ui.sidebar.panels.file_browser import FileBrowserPanel
        tmpdir = tempfile.mkdtemp()
        try:
            pycache = os.path.join(tmpdir, "__pycache__")
            os.makedirs(pycache)
            with open(os.path.join(pycache, "test.pyc"), "w") as f:
                f.write("")
            with open(os.path.join(tmpdir, "app.py"), "w") as f:
                f.write("")
            
            panel = FileBrowserPanel.__new__(FileBrowserPanel)
            nodes = panel._scan_dir(tmpdir)
            labels = [n.label for n in nodes]
            assert not any("__pycache__" in l for l in labels)
            assert any("app.py" in l for l in labels)
        finally:
            shutil.rmtree(tmpdir)