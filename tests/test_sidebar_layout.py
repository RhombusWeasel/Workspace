"""Tests for sidebar layout — verify no padding gap above ContentSwitcher."""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal
from textual.widgets import TabbedContent, TabPane, Header, Footer
from textual.widget import Widget
from textual.widgets._tabbed_content import ContentTabs

from core.paths import collect_tcss
from ui.sidebar.registry import (
    register_sidebar_tab,
    get_sidebar_tabs,
    reset_sidebar_tabs,
)
from ui.sidebar.sidebar import Sidebar, SidebarContainer


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@register_sidebar_tab(name="test", icon="T", side="left", tooltip="Test")
class _TestPanel(Widget):
    """Dummy panel for layout tests."""


class _SidebarApp(App):
    """Minimal app that mounts the sidebar with real CSS loaded."""

    CSS_PATH = collect_tcss(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    CSS = "SidebarContainer { width: 30 !important; }"

    def compose(self) -> ComposeResult:
        yield Header()
        left = SidebarContainer(
            Sidebar("left"), side="left", start_hidden=False, id="sidebar-left"
        )
        right = SidebarContainer(
            Sidebar("right"), side="right", id="sidebar-right"
        )
        with Horizontal():
            yield left
            yield Container()
            yield right
        yield Footer()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_content_tabs_has_no_margin():
    """ContentTabs must not inherit auto-margin from the Sidebar border."""
    reset_sidebar_tabs()
    register_sidebar_tab(name="test", icon="T", side="left", tooltip="Test")(
        _TestPanel
    )

    app = _SidebarApp()
    async with app.run_test(size=(120, 40)):
        ctabs = app.query_one(ContentTabs)
        margin = ctabs.styles.margin
        assert margin.top == 0, f"ContentTabs top margin should be 0, got {margin.top}"
        assert margin.bottom == 0, (
            f"ContentTabs bottom margin should be 0, got {margin.bottom}"
        )


@pytest.mark.asyncio
async def test_no_gap_between_tabs_and_content_switcher():
    """There should be zero visual gap between the tab bar and ContentSwitcher."""
    reset_sidebar_tabs()
    register_sidebar_tab(name="test", icon="T", side="left", tooltip="Test")(
        _TestPanel
    )

    app = _SidebarApp()
    async with app.run_test(size=(120, 40)):
        tc = app.query_one(TabbedContent)
        cs = tc.query_one("ContentSwitcher")
        ctabs = tc.query_one(ContentTabs)

        tabs_bottom = ctabs.region.y + ctabs.region.height
        cs_top = cs.region.y
        gap = cs_top - tabs_bottom

        assert gap == 0, (
            f"Expected no gap between ContentTabs and ContentSwitcher, got {gap} rows"
        )


@pytest.mark.asyncio
async def test_left_sidebar_visible_by_default():
    """Left sidebar should start visible (start_hidden=False)."""
    reset_sidebar_tabs()
    register_sidebar_tab(name="test", icon="T", side="left", tooltip="Test")(
        _TestPanel
    )

    app = _SidebarApp()
    async with app.run_test(size=(120, 40)):
        left = app.query_one("#sidebar-left", SidebarContainer)
        assert not left.is_hidden, "Left sidebar should be visible by default"


@pytest.mark.asyncio
async def test_right_sidebar_hidden_by_default():
    """Right sidebar should start hidden (start_hidden=True)."""
    reset_sidebar_tabs()
    register_sidebar_tab(name="test", icon="T", side="right", tooltip="Test")(
        _TestPanel
    )

    app = _SidebarApp()
    async with app.run_test(size=(120, 40)):
        right = app.query_one("#sidebar-right", SidebarContainer)
        assert right.is_hidden, "Right sidebar should be hidden by default"