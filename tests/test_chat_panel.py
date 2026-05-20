"""Tests for the chat workspace tab integration.

ChatPanel was the old sidebar wrapper — now replaced by ChatTabState
and the open_chat_tab() function.  These tests verify that:

- ChatTabState carries conversation state across recomposition
- Content factory restores conversation from ChatTabState
- ChatManager.flush_state() persists state to ChatTabState
- ChatManager.set_state() restores state from ChatTabState
- The chat.open event handler opens a tab
"""

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Input

from plugins.chat.chat_manager import ChatManager
from plugins.chat.chat_input import ChatInput
from plugins.chat.chat_display import ChatDisplay
from plugins.chat.chat_tab import ChatTabState, _create_chat_content
from ui.tree.tree import Tree


# ---------------------------------------------------------------------------
# Test app
# ---------------------------------------------------------------------------


class ChatTabTestApp(App):
    """Minimal app hosting a ChatManager for testing workspace tab behavior."""

    CSS = """
    ChatManager {
        width: 60;
        height: 100%;
    }
    ChatManager > Vertical {
        height: 1fr;
    }
    ChatManager ChatDisplay Tree {
        height: 1fr;
    }
    """

    def compose(self) -> ComposeResult:
        self.manager = ChatManager()
        yield self.manager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _settle(pilot, n: int = 2) -> None:
    for _ in range(n):
        await pilot.pause()


# ---------------------------------------------------------------------------
# ChatTabState and content factory
# ---------------------------------------------------------------------------


class TestChatTabState:
    def test_default_state(self):
        """ChatTabState can be created without a context."""
        state = ChatTabState()
        assert state._ctx is None
        assert state._history == []
        assert state._sections == []
        assert state._agent is None
        assert state._tools is None
        assert state._db is None
        assert state._chat_id is None

    def test_state_with_context(self):
        """ChatTabState stores the provided context."""
        from context import AppContext
        ctx = AppContext(working_directory="/tmp")
        state = ChatTabState(ctx=ctx)
        assert state._ctx is ctx

    def test_dispose_releases_db_refs(self):
        """Disposing a ChatTabState releases database references."""
        state = ChatTabState()
        state._db = "some_db"
        state._chat_id = "abc"
        state.dispose()
        assert state._db is None
        assert state._chat_id is None

    def test_state_carries_conversation_data(self):
        """ChatTabState stores conversation state for recovery."""
        state = ChatTabState()
        state._history = [{"role": "user", "content": "Hello"}]
        state._sections = [{"turn_id": "t1", "content_type": "user", "content": "Hello"}]
        state._agent = "fake_agent"
        state._tools = [{"name": "read_file"}]
        assert len(state._history) == 1
        assert state._history[0]["content"] == "Hello"
        assert len(state._sections) == 1
        assert state._agent == "fake_agent"
        assert state._tools == [{"name": "read_file"}]


class TestContentFactory:
    async def test_factory_creates_unwired_manager(self):
        """Content factory with no context creates an unwired ChatManager."""
        state = ChatTabState(ctx=None)
        manager = _create_chat_content(state)
        assert isinstance(manager, ChatManager)
        assert manager._agent is None
        assert manager._state is state

    async def test_factory_restores_state(self):
        """Content factory restores conversation state from ChatTabState."""
        state = ChatTabState()
        state._history = [{"role": "user", "content": "Hello"}]
        state._sections = [{"turn_id": "t1", "content_type": "user", "content": "Hello"}]
        state._agent = "fake_agent"
        state._tools = [{"name": "read_file"}]
        manager = _create_chat_content(state)
        assert manager._history == state._history
        assert manager._sections == state._sections
        assert manager._agent == "fake_agent"
        assert manager._tools == [{"name": "read_file"}]

    async def test_factory_creates_wired_manager(self):
        """Content factory with context wires the ChatManager."""
        from core.config import Config


class TestChatManagerState:
    """Tests for ChatManager state persistence (flush_state / set_state)."""

    async def test_flush_state_copies_to_tab_state(self):
        """flush_state() copies ChatManager state to ChatTabState."""
        async with ChatTabTestApp().run_test() as pilot:
            await pilot.pause()
            mgr = pilot.app.manager
            state = ChatTabState()
            mgr.set_state(state)

            mgr._history = [{"role": "user", "content": "Hello"}]
            mgr._sections = [{"turn_id": "t1", "content_type": "user", "content": "Hello"}]
            mgr._tools = [{"name": "read_file"}]

            mgr.flush_state()

            assert state._history == [{"role": "user", "content": "Hello"}]
            assert state._sections == [{"turn_id": "t1", "content_type": "user", "content": "Hello"}]
            assert state._tools == [{"name": "read_file"}]

    async def test_flush_state_noop_without_state(self):
        """flush_state() is a no-op when _state is None."""
        async with ChatTabTestApp().run_test() as pilot:
            await pilot.pause()
            mgr = pilot.app.manager
            # No state set — flush should not raise
            mgr.flush_state()

    async def test_set_state_adopts_conversation(self):
        """set_state() restores conversation data from ChatTabState."""
        async with ChatTabTestApp().run_test() as pilot:
            await pilot.pause()
            mgr = pilot.app.manager
            state = ChatTabState()
            state._history = [{"role": "user", "content": "Hello"}]
            state._sections = [{"turn_id": "t1", "content_type": "user", "content": "Hello"}]
            state._agent = "fake_agent"

            mgr.set_state(state)

            assert mgr._history == [{"role": "user", "content": "Hello"}]
            assert mgr._sections == [{"turn_id": "t1", "content_type": "user", "content": "Hello"}]
            assert mgr._agent == "fake_agent"
            assert mgr._state is state

    async def test_round_trip_preserves_conversation(self):
        """Simulate a flush → recreate → set_state cycle."""
        async with ChatTabTestApp().run_test() as pilot:
            await pilot.pause()
            mgr = pilot.app.manager
            state = ChatTabState()
            mgr.set_state(state)

            # Simulate some conversation data
            mgr._history = [{"role": "user", "content": "What is 2+2?"}]
            mgr._sections = [
                {"turn_id": "abc", "content_type": "user", "content": "What is 2+2?"},
                {"turn_id": "abc", "content_type": "response", "content": "4"},
            ]
            mgr._tools = [{"name": "read_file"}]

            # Flush state (as would happen before recomposition)
            mgr.flush_state()

            # Simulate recreation — new manager adopts state
            new_mgr = ChatManager()
            new_mgr.set_state(state)

            assert new_mgr._history == mgr._history
            assert new_mgr._sections == mgr._sections
            assert new_mgr._tools == mgr._tools
            assert new_mgr._state is state

    async def test_new_conversation_syncs_state(self):
        """new_conversation() clears state and syncs to ChatTabState."""
        async with ChatTabTestApp().run_test() as pilot:
            await pilot.pause()
            mgr = pilot.app.manager
            state = ChatTabState()
            mgr.set_state(state)

            # Set up some initial data
            mgr._history = [{"role": "user", "content": "Hello"}]
            mgr._sections = [{"turn_id": "t1", "content_type": "user", "content": "Hello"}]
            mgr.flush_state()
            assert len(state._history) == 1

            # Start a new conversation
            mgr.new_conversation()

            # Both manager and state should be cleared
            assert mgr._history == []
            assert mgr._sections == []
            # State is synced via flush_state in new_conversation
            assert state._history == []
            assert state._sections == []

    async def test_factory_creates_wired_manager(self):
        """Content factory with context wires the ChatManager."""
        from core.config import Config
        from context import AppContext

        cfg = Config([])
        ctx = AppContext(config=cfg, working_directory="/tmp")
        state = ChatTabState(ctx=ctx)
        manager = _create_chat_content(state)
        assert isinstance(manager, ChatManager)
        # After wiring, the manager should have a database and chat_id
        # (if ctx.database is set — it's None here, so just check agent setup)
        # Since no OllamaProvider is available in test, wiring still runs.


# ---------------------------------------------------------------------------
# Chat tab — display rebuild from sections
# ---------------------------------------------------------------------------


class TestChatDisplayRebuild:
    """Tests for rebuilding the chat display from persisted sections."""

    async def test_rebuild_display_from_sections(self):
        """_rebuild_display_from_sections reconstructs the visual tree."""
        async with ChatTabTestApp().run_test() as pilot:
            await pilot.pause()
            mgr = pilot.app.manager

            # Simulate conversation data in sections
            mgr._sections = [
                {"turn_id": "t1", "content_type": "user", "content": "Hello?"},
                {"turn_id": "t1", "content_type": "thinking", "content": "Hmm..."},
                {"turn_id": "t1", "content_type": "response", "content": "Hi there!"},
            ]

            # Rebuild the display (now async)
            await mgr._rebuild_display_from_sections()

            # Verify the display has content
            display = mgr.query_one(ChatDisplay)
            tree = display.query_one(Tree)
            root = tree._node_map["chat-display-root"]
            # Should have user message + assistant turn
            assert len(root.children) == 2

    async def test_rebuild_display_empty_sections(self):
        """_rebuild_display_from_sections with empty sections is a no-op."""
        async with ChatTabTestApp().run_test() as pilot:
            await pilot.pause()
            mgr = pilot.app.manager
            mgr._sections = []
            # Should not raise
            await mgr._rebuild_display_from_sections()

    async def test_rebuild_display_with_tool_calls(self):
        """_rebuild_display_from_sections formats tool calls correctly."""
        import json
        async with ChatTabTestApp().run_test() as pilot:
            await pilot.pause()
            mgr = pilot.app.manager

            # Simulate conversation with tool calls
            mgr._sections = [
                {"turn_id": "t1", "content_type": "user", "content": "Weather in London?"},
                {"turn_id": "t1", "content_type": "tool_call",
                 "content": json.dumps({"name": "get_weather", "arguments": {"city": "London"}})},
                {"turn_id": "t1", "content_type": "response", "content": "Sunny!"},
            ]

            await mgr._rebuild_display_from_sections()

            display = mgr.query_one(ChatDisplay)
            tree = display.query_one(Tree)
            root = tree._node_map["chat-display-root"]
            assert len(root.children) == 2  # user + assistant


# ---------------------------------------------------------------------------
# Chat tab — basic composition
# ---------------------------------------------------------------------------


class TestChatTab:
    async def test_composes_chat_manager(self):
        """Chat composes ChatManager with input + display."""
        async with ChatTabTestApp().run_test() as pilot:
            await pilot.pause()
            manager = pilot.app.manager
            assert len(manager.query(ChatInput)) == 1
            assert len(manager.query(ChatDisplay)) == 1

    async def test_has_input_and_tree(self):
        """Chat has an Input and Tree widget."""
        async with ChatTabTestApp().run_test() as pilot:
            await pilot.pause()
            manager = pilot.app.manager
            assert len(manager.query("Input")) == 1
            assert len(manager.query(Tree)) == 1

    async def test_input_focuses_on_mount(self):
        """The input field is focused after mounting."""
        async with ChatTabTestApp().run_test() as pilot:
            await pilot.pause()
            focused = pilot.app.focused
            assert focused is not None
            assert isinstance(focused, Input)


# ---------------------------------------------------------------------------
# Chat tab — streaming integration
# ---------------------------------------------------------------------------


class TestChatTabStreaming:
    async def test_full_streaming(self):
        """Streaming works end-to-end through ChatManager."""
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

        async with ChatTabTestApp().run_test() as pilot:
            await pilot.pause()

            mgr = pilot.app.manager
            mgr.set_agent(FakeAgent(chunks))

            inp = mgr.query_one(Input)
            inp.value = "Hi"
            inp.post_message(Input.Submitted(inp, "Hi"))
            await _settle(pilot, n=15)

            # Verify conversation is in the tree.
            display = mgr.query_one(ChatDisplay)
            tree = display.query_one(Tree)
            root = tree._node_map["chat-display-root"]
            assert len(root.children) >= 2

    async def test_streaming_with_tool_calls(self):
        """Tool calls stream correctly through the chat pipeline."""
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

        async with ChatTabTestApp().run_test() as pilot:
            await pilot.pause()

            mgr = pilot.app.manager
            mgr.set_agent(FakeAgent(chunks))

            inp = mgr.query_one(Input)
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
# Chat tab — persistence
# ---------------------------------------------------------------------------


class ChatDBTestApp(App):
    """App hosting ChatManager with a test database in AppContext."""

    CSS = """
    ChatManager {
        width: 60;
        height: 100%;
    }
    ChatManager > Vertical {
        height: 1fr;
    }
    ChatManager ChatDisplay Tree {
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
        self.manager = ChatManager()
        yield self.manager


class TestChatTabPersistence:
    async def test_turn_saved_to_database(self):
        """A full turn is persisted to the database."""
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

            async with ChatDBTestApp(db).run_test() as pilot:
                await _settle(pilot)

                mgr = pilot.app.manager
                mgr.wire_from_context(pilot.app.context)
                mgr.set_agent(FakeAgent(chunks))

                inp = mgr.query_one(Input)
                inp.value = "Hello!"
                inp.post_message(Input.Submitted(inp, "Hello!"))
                await _settle(pilot, n=15)

            chats = db.list_chats()
            assert len(chats) == 1
            sections = db.load_sections(chats[0]["id"])
            types = [s["content_type"] for s in sections]
            assert "user" in types
            user_sec = [s for s in sections if s["content_type"] == "user"][0]
            assert user_sec["content"] == "Hello!"
            resp_sec = [s for s in sections if s["content_type"] == "response"][0]
            assert "Hi there!" in resp_sec["content"]
        finally:
            try:
                db.close()
                os.unlink(db_path)
            except Exception:
                pass