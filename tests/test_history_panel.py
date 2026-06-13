"""Tests for HistoryPanel — verify inline refresh button on tree root."""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from textual.app import App, ComposeResult
from textual.containers import Container

from core.paths import collect_tcss
from ui.sidebar.registry import register_sidebar_tab, reset_sidebar_tabs
from ui.sidebar.panels.history_panel import HistoryPanel
from ui.tree.tree_row import TreeNode, RowButton


# ---------------------------------------------------------------------------
# Helpers — lightweight mock database
# ---------------------------------------------------------------------------


class _MockDB:
    """Minimal mock that satisfies HistoryPanel._rebuild()."""

    def list_chats(self):
        return []

    def load_sections(self, chat_id):
        return []

    def reconstruct_history(self, chat_id):
        return []


class _MockContext:
    database = _MockDB()


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------


class _HistoryApp(App):
    CSS_PATH = collect_tcss(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )

    def compose(self) -> ComposeResult:
        yield Container(HistoryPanel())


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_static_header_above_tree():
    """HistoryPanel must not contain a Static section-header widget."""
    reset_sidebar_tabs()
    app = _HistoryApp()
    async with app.run_test(size=(80, 40)):
        panel = app.query_one(HistoryPanel)
        # The old layout had a Static with class "section-header"
        statics = panel.query("Static.section-header")
        assert len(statics) == 0, (
            f"Found unexpected Static.section-header widgets: {statics}"
        )


@pytest.mark.asyncio
async def test_no_history_actions_horizontal():
    """HistoryPanel must not contain the old history-actions Horizontal bar."""
    reset_sidebar_tabs()
    app = _HistoryApp()
    async with app.run_test(size=(80, 40)):
        panel = app.query_one(HistoryPanel)
        actions = panel.query(".history-actions")
        assert len(actions) == 0, (
            f"Found unexpected .history-actions widgets: {actions}"
        )


@pytest.mark.asyncio
async def test_no_separate_refresh_button():
    """HistoryPanel must not contain a standalone refresh Button widget."""
    reset_sidebar_tabs()
    app = _HistoryApp()
    async with app.run_test(size=(80, 40)):
        panel = app.query_one(HistoryPanel)
        buttons = panel.query("#history-refresh")
        assert len(buttons) == 0, (
            f"Found unexpected #history-refresh button: {buttons}"
        )


@pytest.mark.asyncio
async def test_root_node_has_refresh_button():
    """The tree root node should have a refresh RowButton."""
    reset_sidebar_tabs()
    app = _HistoryApp()
    async with app.run_test(size=(80, 40)):
        panel = app.query_one(HistoryPanel)
        tree = panel.query_one("Tree")
        root = tree.root

        refresh_buttons = [
            btn for btn in root.buttons if btn.action_id == "refresh"
        ]
        assert len(refresh_buttons) >= 1, (
            f"Expected root TreeNode to have a 'refresh' RowButton, "
            f"but buttons={root.buttons}"
        )


@pytest.mark.asyncio
async def test_rebuild_wires_context_and_db():
    """On mount, HistoryPanel should wire _ctx and _db from the app context."""
    reset_sidebar_tabs()

    # Patch the app so that app.context returns our mock
    class _CtxApp(_HistoryApp):
        @property
        def context(self):
            return _MockContext()

    app = _CtxApp()
    async with app.run_test(size=(80, 40)):
        panel = app.query_one(HistoryPanel)
        assert panel._db is not None, "Expected _db to be set after mount"
        assert panel._ctx is not None, "Expected _ctx to be set after mount"