"""Tests for the ChatPanel sidebar tab wrapper.

ChatPanel is a thin sidebar tab that composes a ChatManager and wires
it from AppContext on mount.  These tests verify the integration: that
the tab renders correctly and streams conversations through the manager.
"""

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Input

from ui.chat.chat_manager import ChatManager
from ui.chat.chat_input import ChatInput
from ui.chat.chat_display import ChatDisplay
from ui.sidebar.panels.chat_panel import ChatPanel
from ui.tree.tree import Tree


# ---------------------------------------------------------------------------
# Test app
# ---------------------------------------------------------------------------


class ChatPanelTestApp(App):
    """Minimal app hosting a ChatPanel for integration testing."""

    CSS = """
    ChatPanel {
        width: 60;
        height: 100%;
    }
    ChatPanel > ChatManager > ChatDisplay > Tree {
        height: 1fr;
    }
    """

    def compose(self) -> ComposeResult:
        self.panel = ChatPanel()
        yield self.panel


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _settle(pilot, n: int = 2) -> None:
    for _ in range(n):
        await pilot.pause()


# ---------------------------------------------------------------------------
# ChatPanel — sidebar tab integration
# ---------------------------------------------------------------------------


class TestChatPanel:
    async def test_composes_chat_manager(self):
        """ChatPanel composes a ChatManager (which in turn has input + display)."""
        async with ChatPanelTestApp().run_test() as pilot:
            await pilot.pause()
            panel = pilot.app.panel
            managers = panel.query(ChatManager)
            assert len(managers) == 1
            # ChatManager composes ChatInput + ChatDisplay.
            mgr = managers.first()
            assert len(mgr.query(ChatInput)) == 1
            assert len(mgr.query(ChatDisplay)) == 1

    async def test_has_input_and_tree(self):
        """ChatPanel's composed tree has an Input and Tree widget."""
        async with ChatPanelTestApp().run_test() as pilot:
            await pilot.pause()
            panel = pilot.app.panel
            assert len(panel.query("Input")) == 1
            assert len(panel.query(Tree)) == 1

    async def test_input_focuses_on_mount(self):
        """The input field is focused after mounting."""
        async with ChatPanelTestApp().run_test() as pilot:
            await pilot.pause()
            focused = pilot.app.focused
            assert focused is not None
            assert isinstance(focused, Input)


# ---------------------------------------------------------------------------
# ChatPanel — streaming integration
# ---------------------------------------------------------------------------


class TestChatPanelStreaming:
    async def test_full_streaming_through_wrapper(self):
        """Streaming works end-to-end through ChatPanel → ChatManager."""
        chunks = [
            type('C', (), {'thinking': 'Let me think', 'content': '', 'tool_calls': None})(),
            type('C', (), {'thinking': '', 'content': 'Hello!', 'tool_calls': None})(),
        ]

        class FakeAgent:
            def __init__(self, chunks):
                self._chunks = chunks

            async def stream_chat(self, history, user_text, tools=None):
                for chunk in self._chunks:
                    yield chunk

        async with ChatPanelTestApp().run_test() as pilot:
            await pilot.pause()

            panel = pilot.app.panel
            mgr = panel.query_one(ChatManager)
            mgr.set_agent(FakeAgent(chunks))

            inp = panel.query_one(Input)
            inp.value = "Hi"
            inp.post_message(Input.Submitted(inp, "Hi"))
            await _settle(pilot, n=15)

            # Verify conversation is in the tree.
            display = mgr.query_one(ChatDisplay)
            tree = display.query_one(Tree)
            root = tree._node_map["chat-display-root"]
            assert len(root.children) >= 2

    async def test_streaming_with_tool_calls_through_wrapper(self):
        """Tool calls stream correctly through the wrapper pipeline."""
        chunks = [
            type('C', (), {
                'thinking': '', 'content': '',
                'tool_calls': [
                    type('TC', (), {'name': 'get_weather', 'arguments': {'city': 'London'}})()
                ]
            })(),
            type('C', (), {'thinking': '', 'content': 'Sunny!', 'tool_calls': None})(),
        ]

        class FakeAgent:
            def __init__(self, chunks):
                self._chunks = chunks

            async def stream_chat(self, history, user_text, tools=None):
                for chunk in self._chunks:
                    yield chunk

        async with ChatPanelTestApp().run_test() as pilot:
            await pilot.pause()

            panel = pilot.app.panel
            mgr = panel.query_one(ChatManager)
            mgr.set_agent(FakeAgent(chunks))

            inp = panel.query_one(Input)
            inp.value = "Weather?"
            inp.post_message(Input.Submitted(inp, "Weather?"))
            await _settle(pilot, n=15)

            display = mgr.query_one(ChatDisplay)
            tree = display.query_one(Tree)
            root = tree._node_map["chat-display-root"]
            asst_node = root.children[-1]
            sections = {c.data["section"] for c in asst_node.children}
            assert "tools" in sections
            assert "response" in sections


# ---------------------------------------------------------------------------
# ChatPanel — persistence through wrapper
# ---------------------------------------------------------------------------


class ChatPanelDBTestApp(App):
    """App hosting ChatPanel with a test database in AppContext."""

    CSS = """
    ChatPanel {
        width: 60;
        height: 100%;
    }
    ChatPanel > ChatManager > ChatDisplay > Tree {
        height: 1fr;
    }
    """

    def __init__(self, db):
        self._test_db = db
        from core.config import Config
        cfg = Config([])
        from context import AppContext
        self.context = AppContext(
            database=db,
            config=cfg,
            working_directory="/tmp",
        )
        super().__init__()

    def compose(self) -> ComposeResult:
        self.panel = ChatPanel()
        yield self.panel


class TestChatPanelPersistence:
    async def test_turn_saved_through_wrapper(self):
        """A full turn through ChatPanel is persisted to the database."""
        from core.database import DatabaseManager
        import tempfile, os

        chunks = [
            type('C', (), {'thinking': '', 'content': 'Hi there!', 'tool_calls': None})(),
        ]

        class FakeAgent:
            def __init__(self, chunks):
                self._chunks = chunks

            async def stream_chat(self, history, user_text, tools=None):
                for chunk in self._chunks:
                    yield chunk

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
            db_path = tf.name

        try:
            db = DatabaseManager(db_path)

            async with ChatPanelDBTestApp(db).run_test() as pilot:
                await _settle(pilot)

                panel = pilot.app.panel
                mgr = panel.query_one(ChatManager)
                mgr.set_agent(FakeAgent(chunks))

                inp = panel.query_one(Input)
                inp.value = "Hello!"
                inp.post_message(Input.Submitted(inp, "Hello!"))
                await _settle(pilot, n=15)

            chats = db.list_chats()
            assert len(chats) == 1
            messages = db.get_messages(chats[0]["id"])
            assert len(messages) == 2
            assert messages[0]["role"] == "user"
            assert messages[0]["content"] == "Hello!"
            assert "Hi there!" in messages[1]["content"]
        finally:
            try:
                db.close()
                os.unlink(db_path)
            except Exception:
                pass
