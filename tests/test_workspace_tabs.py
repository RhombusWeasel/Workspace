"""Tests for WorkspaceTabs — custom tabbed container with closeable tabs.

Tests cover: opening tabs, closing tabs, switching tabs,
closing the active tab, closing a non-active tab, double-opening
the same tab, closing all tabs.
"""

import pytest
from textual.app import App, ComposeResult
from textual.containers import Container
from textual.widgets import Input, Label, Static

from ui.workspace.tabs import WorkspaceTabs, TabState, TabInfo


# ---------------------------------------------------------------------------
# Test app
# ---------------------------------------------------------------------------


class TabsTestApp(App):
    """Minimal app hosting WorkspaceTabs for testing."""

    CSS = """
    WorkspaceTabs {
        height: 100%;
        width: 100%;
    }
    """

    def compose(self) -> ComposeResult:
        self.tabs = WorkspaceTabs()
        yield self.tabs


def _label(text: str) -> Label:
    """Create a simple Label widget for tab content."""
    safe_id = text.replace(" ", "_").replace(".", "_")
    return Label(text, id=f"lbl-{safe_id}")


def _state(label: str = "") -> TabState:
    """Create a bare TabState for testing."""
    return TabState()


def _factory_for_label(text: str):
    """Create a content factory that returns a Label with the given text."""
    def factory(s: TabState) -> Label:
        return _label(text)
    return factory


# ---------------------------------------------------------------------------
# Opening tabs
# ---------------------------------------------------------------------------


class TestOpenTab:
    async def test_open_single_tab(self):
        """Opening a tab creates it and shows its content."""
        async with TabsTestApp().run_test() as pilot:
            tabs = pilot.app.tabs
            await pilot.pause()

            tabs.open_tab("t1", "File 1", state=_state(), content=_label("Content 1"))
            await pilot.pause()

            assert tabs.tab_count == 1
            assert tabs.active_tab_id == "t1"

    async def test_open_multiple_tabs(self):
        """Opening multiple tabs creates them all; last is active."""
        async with TabsTestApp().run_test() as pilot:
            tabs = pilot.app.tabs
            await pilot.pause()

            tabs.open_tab("t1", "File 1", state=_state(), content=_label("Content 1"))
            tabs.open_tab("t2", "File 2", state=_state(), content=_label("Content 2"))
            await pilot.pause()

            assert tabs.tab_count == 2
            assert tabs.active_tab_id == "t2"

    async def test_open_existing_tab_switches_to_it(self):
        """Opening a tab with an existing id switches to it instead of duplicating."""
        async with TabsTestApp().run_test() as pilot:
            tabs = pilot.app.tabs
            await pilot.pause()

            tabs.open_tab("t1", "File 1", state=_state(), content=_label("Content 1"))
            tabs.open_tab("t2", "File 2", state=_state(), content=_label("Content 2"))
            await pilot.pause()

            # Opening t1 again should switch to it, not add a new tab
            tabs.open_tab("t1", "File 1", state=_state(), content=_label("Content 1"))
            await pilot.pause()

            assert tabs.tab_count == 2
            assert tabs.active_tab_id == "t1"


# ---------------------------------------------------------------------------
# Switching tabs
# ---------------------------------------------------------------------------


class TestSwitchTab:
    async def test_switch_to_existing_tab(self):
        """switch_tab changes the active tab."""
        async with TabsTestApp().run_test() as pilot:
            tabs = pilot.app.tabs
            await pilot.pause()

            tabs.open_tab("t1", "File 1", state=_state(), content=_label("Content 1"))
            tabs.open_tab("t2", "File 2", state=_state(), content=_label("Content 2"))
            await pilot.pause()

            tabs.switch_tab("t1")
            await pilot.pause()

            assert tabs.active_tab_id == "t1"

    async def test_switch_posts_tab_switched(self):
        """switch_tab posts a TabSwitched message."""
        messages = []

        class SwitchApp(App):
            CSS = "WorkspaceTabs { height: 100%; width: 100%; }"

            def compose(self) -> ComposeResult:
                self.tabs = WorkspaceTabs()
                yield self.tabs

            def on_workspace_tabs_tab_switched(self, msg: WorkspaceTabs.TabSwitched) -> None:
                messages.append(msg)

        async with SwitchApp().run_test() as pilot:
            tabs = pilot.app.tabs
            await pilot.pause()

            tabs.open_tab("t1", "File 1", state=_state(), content=_label("Content 1"))
            tabs.open_tab("t2", "File 2", state=_state(), content=_label("Content 2"))
            await pilot.pause()

            tabs.switch_tab("t1")
            await pilot.pause()

            switched = [m for m in messages if m.tab_id == "t1"]
            assert len(switched) >= 1

    async def test_switch_to_nonexistent_tab_ignored(self):
        """switch_tab to a non-existent tab id is ignored."""
        async with TabsTestApp().run_test() as pilot:
            tabs = pilot.app.tabs
            await pilot.pause()

            tabs.open_tab("t1", "File 1", state=_state(), content=_label("Content 1"))
            await pilot.pause()

            tabs.switch_tab("nonexistent")
            assert tabs.active_tab_id == "t1"


# ---------------------------------------------------------------------------
# Closing tabs
# ---------------------------------------------------------------------------


class TestCloseTab:
    async def test_close_active_tab(self):
        """Closing the active tab switches to the neighboring tab."""
        async with TabsTestApp().run_test() as pilot:
            tabs = pilot.app.tabs
            await pilot.pause()

            tabs.open_tab("t1", "File 1", state=_state(), content=_label("Content 1"))
            tabs.open_tab("t2", "File 2", state=_state(), content=_label("Content 2"))
            tabs.open_tab("t3", "File 3", state=_state(), content=_label("Content 3"))
            await pilot.pause()

            tabs.close_tab("t2")  # Close active
            await pilot.pause()

            assert tabs.tab_count == 2
            # Should switch to a remaining tab
            assert tabs.active_tab_id in ("t1", "t3")

    async def test_close_non_active_tab(self):
        """Closing a non-active tab doesn't change the active tab."""
        async with TabsTestApp().run_test() as pilot:
            tabs = pilot.app.tabs
            await pilot.pause()

            tabs.open_tab("t1", "File 1", state=_state(), content=_label("Content 1"))
            tabs.open_tab("t2", "File 2", state=_state(), content=_label("Content 2"))
            await pilot.pause()

            tabs.close_tab("t1")  # Close non-active
            await pilot.pause()

            assert tabs.tab_count == 1
            assert tabs.active_tab_id == "t2"

    async def test_close_last_tab(self):
        """Closing the last tab leaves no active tab."""
        async with TabsTestApp().run_test() as pilot:
            tabs = pilot.app.tabs
            await pilot.pause()

            tabs.open_tab("t1", "File 1", state=_state(), content=_label("Content 1"))
            await pilot.pause()

            tabs.close_tab("t1")
            await pilot.pause()

            assert tabs.tab_count == 0
            assert tabs.active_tab_id is None

    async def test_close_posts_tab_closed(self):
        """Closing a tab posts a TabClosed message."""
        messages = []

        class CloseApp(App):
            CSS = "WorkspaceTabs { height: 100%; width: 100%; }"

            def compose(self) -> ComposeResult:
                self.tabs = WorkspaceTabs()
                yield self.tabs

            def on_workspace_tabs_tab_closed(self, msg: WorkspaceTabs.TabClosed) -> None:
                messages.append(msg)

        async with CloseApp().run_test() as pilot:
            tabs = pilot.app.tabs
            await pilot.pause()

            tabs.open_tab("t1", "File 1", state=_state(), content=_label("Content 1"))
            await pilot.pause()

            tabs.close_tab("t1")
            await pilot.pause()

            closed = [m for m in messages if m.tab_id == "t1"]
            assert len(closed) >= 1

    async def test_close_nonexistent_tab_ignored(self):
        """Closing a non-existent tab is a no-op."""
        async with TabsTestApp().run_test() as pilot:
            tabs = pilot.app.tabs
            await pilot.pause()

            tabs.open_tab("t1", "File 1", state=_state(), content=_label("Content 1"))
            await pilot.pause()

            tabs.close_tab("nonexistent")
            assert tabs.tab_count == 1
            assert tabs.active_tab_id == "t1"


# ---------------------------------------------------------------------------
# Tab info
# ---------------------------------------------------------------------------


class TestTabInfo:
    def test_tab_info_fields(self):
        info = TabInfo(id="f1", label="main.py", state=TabState())
        assert info.id == "f1"
        assert info.label == "main.py"
        assert info.content is None
        assert info.state is not None

    def test_tab_info_with_content(self):
        content = Label("Hello")
        state = TabState()
        info = TabInfo(id="f2", label="app.py", state=state, content=content)
        assert info.content is content


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    async def test_no_tabs_initially(self):
        """WorkspaceTabs starts with no tabs."""
        async with TabsTestApp().run_test() as pilot:
            tabs = pilot.app.tabs
            await pilot.pause()

            assert tabs.tab_count == 0
            assert tabs.active_tab_id is None

    async def test_open_then_close_then_reopen(self):
        """A tab can be re-opened after being closed."""
        async with TabsTestApp().run_test() as pilot:
            tabs = pilot.app.tabs
            await pilot.pause()

            tabs.open_tab("t1", "File 1", state=_state(), content=_label("Content A"))
            await pilot.pause()
            tabs.close_tab("t1")
            await pilot.pause()
            # Re-open with different content
            tabs.open_tab("t1", "File 1", state=_state(), content=_label("Content B"))
            await pilot.pause()

            assert tabs.tab_count == 1
            assert tabs.active_tab_id == "t1"


# ---------------------------------------------------------------------------
# Focus handling
# ---------------------------------------------------------------------------


class _FocusableContent(Container):
    """A container with an Input child, simulating a tab with focusable content."""

    DEFAULT_CSS = "_FocusableContent { height: auto; }"

    def __init__(self, input_id: str = "focus-input", **kwargs):
        super().__init__(**kwargs)
        self._input_id = input_id

    def compose(self) -> ComposeResult:
        yield Input(placeholder="Type here", id=self._input_id)


class FocusTabsApp(App):
    """App with WorkspaceTabs for focus testing."""

    CSS = """
    WorkspaceTabs {
        height: 100%;
        width: 100%;
    }
    """

    def compose(self) -> ComposeResult:
        self.tabs = WorkspaceTabs()
        yield self.tabs


def _focusable_factory(s: TabState) -> _FocusableContent:
    return _FocusableContent()


class TestFocusOnTabSwitch:
    async def test_open_tab_focuses_focusable_content(self):
        """Opening a tab with focusable content gives it keyboard focus."""
        async with FocusTabsApp().run_test() as pilot:
            tabs = pilot.app.tabs
            await pilot.pause()

            tabs.open_tab(
                "t1", "Editor", state=_state(),
                content_factory=_focusable_factory,
            )
            await pilot.pause()

            # The Input inside the tab should have focus.
            focused = pilot.app.focused
            assert focused is not None
            assert focused.id == "focus-input"

    async def test_switch_tab_moves_focus(self):
        """Switching to a tab moves focus to its focusable content."""
        async with FocusTabsApp().run_test() as pilot:
            tabs = pilot.app.tabs
            await pilot.pause()

            # Open two tabs, each with its own uniquely-identified Input.
            tabs.open_tab(
                "t1", "Editor 1", state=_state(),
                content=_FocusableContent(input_id="input-1"),
            )
            tabs.open_tab(
                "t2", "Editor 2", state=_state(),
                content=_FocusableContent(input_id="input-2"),
            )
            await pilot.pause()

            # t2 is active — its input should be focused.
            focused = pilot.app.focused
            assert focused is not None
            assert focused.id == "input-2"

            # Switch to t1.
            tabs.switch_tab("t1")
            await pilot.pause()

            # t1 is now active — its input should be focused.
            focused = pilot.app.focused
            assert focused is not None
            assert focused.id == "input-1"

    async def test_close_active_tab_focuses_remaining(self):
        """Closing the active tab focuses the next tab's content."""
        async with FocusTabsApp().run_test() as pilot:
            tabs = pilot.app.tabs
            await pilot.pause()

            # Open two tabs with uniquely identified inputs.
            tabs.open_tab(
                "t1", "Editor 1", state=_state(),
                content=_FocusableContent(input_id="input-1"),
            )
            tabs.open_tab(
                "t2", "Editor 2", state=_state(),
                content=_FocusableContent(input_id="input-2"),
            )
            await pilot.pause()

            # t2 is active and focused.
            assert pilot.app.focused is not None
            assert pilot.app.focused.id == "input-2"

            # Close t2 (the active tab) — should switch to t1.
            tabs.close_tab("t2")
            await pilot.pause()

            # t1 should now be active and its input focused.
            assert tabs.active_tab_id == "t1"
            focused = pilot.app.focused
            assert focused is not None
            assert focused.id == "input-1"