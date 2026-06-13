"""Tests for sidebar panel refactoring — verify inline buttons on tree roots.

All sidebar panels should have their action buttons as RowButtons on
TreeNode roots or sections, not as separate Static/Button widgets above
the tree.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from textual.app import App, ComposeResult
from textual.containers import Container

from core.paths import collect_tcss
from ui.sidebar.registry import reset_sidebar_tabs


# ---------------------------------------------------------------------------
# File browser tests
# ---------------------------------------------------------------------------


class _MockFileBrowserContext:
    working_directory = os.path.dirname(os.path.abspath(__file__))


class _FileBrowserApp(App):
    CSS_PATH = collect_tcss(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )

    def compose(self) -> ComposeResult:
        from ui.sidebar.panels.file_browser import FileBrowserPanel
        yield Container(FileBrowserPanel())

    @property
    def context(self):
        return _MockFileBrowserContext()


@pytest.mark.asyncio
async def test_file_browser_no_static_header():
    """FileBrowserPanel must not contain a Static section-header."""
    reset_sidebar_tabs()
    app = _FileBrowserApp()
    async with app.run_test(size=(80, 40)):
        from ui.sidebar.panels.file_browser import FileBrowserPanel
        panel = app.query_one(FileBrowserPanel)
        statics = panel.query("Static.section-header")
        assert len(statics) == 0, (
            f"Found unexpected Static.section-header: {statics}"
        )


@pytest.mark.asyncio
async def test_file_browser_no_action_bar():
    """FileBrowserPanel must not contain the old action-bar Horizontal."""
    reset_sidebar_tabs()
    app = _FileBrowserApp()
    async with app.run_test(size=(80, 40)):
        from ui.sidebar.panels.file_browser import FileBrowserPanel
        panel = app.query_one(FileBrowserPanel)
        actions = panel.query(".file-browser-actions")
        assert len(actions) == 0, (
            f"Found unexpected .file-browser-actions: {actions}"
        )


@pytest.mark.asyncio
async def test_file_browser_root_has_refresh_button():
    """The file browser tree root should have a refresh RowButton."""
    reset_sidebar_tabs()
    app = _FileBrowserApp()
    async with app.run_test(size=(80, 40)):
        from ui.sidebar.panels.file_browser import FileBrowserPanel
        panel = app.query_one(FileBrowserPanel)
        tree = panel.query_one("Tree")
        root = tree.root
        refresh_buttons = [
            btn for btn in root.buttons if btn.action_id == "refresh"
        ]
        assert len(refresh_buttons) >= 1, (
            f"Expected root to have 'refresh' RowButton, buttons={root.buttons}"
        )


# ---------------------------------------------------------------------------
# Git panel tests
# ---------------------------------------------------------------------------


class _MockGitContext:
    working_directory = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config = None


class _GitPanelApp(App):
    CSS_PATH = collect_tcss(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )

    def compose(self) -> ComposeResult:
        # Must import late so git skill's register_sidebar_tab runs
        from skills.git.components.git_panel import GitPanel
        yield Container(GitPanel())

    @property
    def context(self):
        ctx = _MockGitContext()
        ctx.config = type("C", (), {"get": lambda self, k, d=None: d})()
        return ctx


@pytest.mark.asyncio
async def test_git_panel_no_static_header():
    """GitPanel must not contain a Static section-header."""
    reset_sidebar_tabs()
    app = _GitPanelApp()
    async with app.run_test(size=(80, 40)):
        from skills.git.components.git_panel import GitPanel
        panel = app.query_one(GitPanel)
        statics = panel.query("Static.section-header")
        assert len(statics) == 0, (
            f"Found unexpected Static.section-header: {statics}"
        )


@pytest.mark.asyncio
async def test_git_panel_no_action_bar():
    """GitPanel must not contain the old git-panel-actions Horizontal."""
    reset_sidebar_tabs()
    app = _GitPanelApp()
    async with app.run_test(size=(80, 40)):
        from skills.git.components.git_panel import GitPanel
        panel = app.query_one(GitPanel)
        actions = panel.query(".git-panel-actions")
        assert len(actions) == 0, (
            f"Found unexpected .git-panel-actions: {actions}"
        )


@pytest.mark.asyncio
async def test_git_panel_root_has_refresh_and_commit_buttons():
    """Git panel tree root should have refresh and commit RowButtons."""
    reset_sidebar_tabs()
    app = _GitPanelApp()
    async with app.run_test(size=(80, 40)):
        from skills.git.components.git_panel import GitPanel
        panel = app.query_one(GitPanel)
        tree = panel.query_one("Tree")
        root = tree.root
        action_ids = [btn.action_id for btn in root.buttons]
        assert "git-refresh" in action_ids, (
            f"Expected 'git-refresh' in root buttons, got {action_ids}"
        )
        assert "git-commit" in action_ids, (
            f"Expected 'git-commit' in root buttons, got {action_ids}"
        )


# ---------------------------------------------------------------------------
# Vault panel tests
# ---------------------------------------------------------------------------


class _MockVaultDB:
    def list_chats(self):
        return []


class _MockVaultContext:
    database = _MockVaultDB()
    vault = None


class _VaultPanelApp(App):
    CSS_PATH = collect_tcss(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )

    def compose(self) -> ComposeResult:
        from ui.sidebar.panels.vault_panel import VaultPanel
        yield Container(VaultPanel())

    @property
    def context(self):
        return _MockVaultContext()


@pytest.mark.asyncio
async def test_vault_no_static_headers():
    """VaultPanel must not contain Static vault-section-header widgets."""
    reset_sidebar_tabs()
    app = _VaultPanelApp()
    async with app.run_test(size=(80, 40)):
        from ui.sidebar.panels.vault_panel import VaultPanel
        panel = app.query_one(VaultPanel)
        headers = panel.query(".vault-section-header")
        assert len(headers) == 0, (
            f"Found unexpected .vault-section-header: {headers}"
        )


@pytest.mark.asyncio
async def test_vault_no_action_bars():
    """VaultPanel must not contain .vault-actions Horizontal bars."""
    reset_sidebar_tabs()
    app = _VaultPanelApp()
    async with app.run_test(size=(80, 40)):
        from ui.sidebar.panels.vault_panel import VaultPanel
        panel = app.query_one(VaultPanel)
        actions = panel.query(".vault-actions")
        assert len(actions) == 0, (
            f"Found unexpected .vault-actions: {actions}"
        )


@pytest.mark.asyncio
async def test_vault_no_standalone_buttons():
    """VaultPanel must not contain standalone #remove-local-vault or
    #create-local-vault buttons."""
    reset_sidebar_tabs()
    app = _VaultPanelApp()
    async with app.run_test(size=(80, 40)):
        from ui.sidebar.panels.vault_panel import VaultPanel
        panel = app.query_one(VaultPanel)
        remove_btn = panel.query("#remove-local-vault")
        create_btn = panel.query("#create-local-vault")
        assert len(remove_btn) == 0, f"Found unexpected #remove-local-vault: {remove_btn}"
        assert len(create_btn) == 0, f"Found unexpected #create-local-vault: {create_btn}"


@pytest.mark.asyncio
async def test_vault_roots_have_refresh_buttons():
    """Both vault trees should have refresh RowButtons on their roots."""
    reset_sidebar_tabs()
    app = _VaultPanelApp()
    async with app.run_test(size=(80, 40)):
        from ui.sidebar.panels.vault_panel import VaultPanel
        panel = app.query_one(VaultPanel)
        global_tree = panel.query_one("#global-tree")
        local_tree = panel.query_one("#local-tree")

        for tree_label, tree in [("global", global_tree), ("local", local_tree)]:
            refresh_buttons = [
                btn for btn in tree.root.buttons if btn.action_id == "refresh"
            ]
            assert len(refresh_buttons) >= 1, (
                f"{tree_label} tree root should have 'refresh' RowButton, "
                f"buttons={[b.action_id for b in tree.root.buttons]}"
            )


@pytest.mark.asyncio
async def test_vault_section_nodes_have_add_buttons():
    """Credential/Notes section nodes should have add RowButtons."""
    reset_sidebar_tabs()
    app = _VaultPanelApp()
    async with app.run_test(size=(80, 40)):
        from ui.sidebar.panels.vault_panel import VaultPanel
        panel = app.query_one(VaultPanel)
        global_tree = panel.query_one("#global-tree")

        # Find credential and notes section nodes
        root = global_tree.root
        child_ids = [child.id for child in root.children] if root.children else []

        # Should have section nodes with add buttons
        for child in (root.children or []):
            action_ids = [btn.action_id for btn in child.buttons]
            if "creds" in child.id:
                assert any("add-cred" in aid for aid in action_ids), (
                    f"Credentials section should have add-cred button, got {action_ids}"
                )
            elif "notes" in child.id:
                assert any("add-note" in aid for aid in action_ids), (
                    f"Notes section should have add-note button, got {action_ids}"
                )