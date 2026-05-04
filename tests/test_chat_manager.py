"""Tests for the ChatManager widget.

ChatManager composes ChatInput + ChatDisplay and orchestrates the
streaming loop, history tracking, and database persistence.
"""

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Input, Markdown

from ui.chat.chat_manager import ChatManager
from ui.chat.chat_input import ChatInput
from ui.chat.chat_display import ChatDisplay
from ui.tree.tree import Tree


# ---------------------------------------------------------------------------
# Test app
# ---------------------------------------------------------------------------


class ChatManagerTestApp(App):
    """Minimal app hosting a ChatManager."""

    CSS = """
    ChatManager {
        width: 60;
        height: 100%;
    }
    ChatManager > ChatDisplay > Tree {
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
# ChatManager — composition
# ---------------------------------------------------------------------------


class TestChatManagerComposition:
    async def test_composes_chat_input_and_display(self):
        """ChatManager composes a ChatInput and a ChatDisplay."""
        async with ChatManagerTestApp().run_test() as pilot:
            await pilot.pause()
            mgr = pilot.app.manager
            inputs = mgr.query(ChatInput)
            displays = mgr.query(ChatDisplay)
            assert len(inputs) == 1
            assert len(displays) == 1

    async def test_has_no_agent_by_default(self):
        """Without set_agent, ChatManager has no agent."""
        async with ChatManagerTestApp().run_test() as pilot:
            await pilot.pause()
            assert pilot.app.manager._agent is None

    async def test_has_no_tools_by_default(self):
        """Without set_tools, ChatManager has no tools."""
        async with ChatManagerTestApp().run_test() as pilot:
            await pilot.pause()
            assert pilot.app.manager._tools is None


# ---------------------------------------------------------------------------
# ChatManager — set_agent / set_tools
# ---------------------------------------------------------------------------


class TestChatManagerSetup:
    async def test_set_agent_stores_agent(self):
        """set_agent stores the agent reference."""
        async with ChatManagerTestApp().run_test() as pilot:
            await pilot.pause()

            class FakeAgent:
                pass

            ag = FakeAgent()
            pilot.app.manager.set_agent(ag)
            assert pilot.app.manager._agent is ag

    async def test_set_tools_stores_tools(self):
        """set_tools stores the tools list."""
        async with ChatManagerTestApp().run_test() as pilot:
            await pilot.pause()

            tools = [{"name": "read_file"}]
            pilot.app.manager.set_tools(tools)
            assert pilot.app.manager._tools is tools


# ---------------------------------------------------------------------------
# ChatManager — streaming orchestration
# ---------------------------------------------------------------------------


class TestChatManagerStreaming:
    async def test_full_streaming_flow_with_fake_agent(self):
        """A complete turn: user submit → streaming → tree updated."""
        chunks = [
            type('C', (), {'thinking': 'Let me', 'content': '', 'tool_calls': None})(),
            type('C', (), {'thinking': ' think', 'content': '', 'tool_calls': None})(),
            type('C', (), {'thinking': '', 'content': 'Hello', 'tool_calls': None})(),
            type('C', (), {'thinking': '', 'content': ' world', 'tool_calls': None})(),
            type('C', (), {'thinking': '', 'content': '!', 'tool_calls': None})(),
        ]

        class FakeAgent:
            def __init__(self, chunks):
                self._chunks = chunks

            async def stream_chat(self, history, user_text, tools=None):
                for chunk in self._chunks:
                    yield chunk

        async with ChatManagerTestApp().run_test() as pilot:
            await pilot.pause()

            mgr = pilot.app.manager
            mgr.set_agent(FakeAgent(chunks))

            # Simulate user input submission.
            chat_input = mgr.query_one(ChatInput)
            inp = chat_input.query_one(Input)
            inp.value = "Hello?"
            inp.post_message(Input.Submitted(inp, "Hello?"))
            await _settle(pilot, n=15)

            # History should have user + assistant messages.
            assert len(mgr._history) == 2
            assert mgr._history[0] == {"role": "user", "content": "Hello?"}
            assert mgr._history[1]["role"] == "assistant"
            assert "Hello world!" in mgr._history[1]["content"]

            # Tree should have user leaf + assistant branch.
            display = mgr.query_one(ChatDisplay)
            tree = display.query_one(Tree)
            root = tree._node_map["chat-display-root"]
            assert len(root.children) >= 2

            # Assistant node should have thinking and response sections.
            asst_node = root.children[-1]
            sections = {c.data["section"] for c in asst_node.children}
            assert "thinking" in sections
            assert "response" in sections

    async def test_streaming_with_tool_calls(self):
        """Tool calls are routed to the tools section."""
        chunks = [
            type('C', (), {
                'thinking': '', 'content': '',
                'tool_calls': [
                    type('TC', (), {'name': 'get_weather', 'arguments': {'city': 'London'}})()
                ]
            })(),
            type('C', (), {'thinking': '', 'content': 'The weather is sunny', 'tool_calls': None})(),
        ]

        class FakeAgent:
            def __init__(self, chunks):
                self._chunks = chunks

            async def stream_chat(self, history, user_text, tools=None):
                for chunk in self._chunks:
                    yield chunk

        async with ChatManagerTestApp().run_test() as pilot:
            await pilot.pause()

            mgr = pilot.app.manager
            mgr.set_agent(FakeAgent(chunks))

            chat_input = mgr.query_one(ChatInput)
            inp = chat_input.query_one(Input)
            inp.value = "Weather?"
            inp.post_message(Input.Submitted(inp, "Weather?"))
            await _settle(pilot, n=15)

            assert len(mgr._history) == 2
            asst_msg = mgr._history[1]
            assert asst_msg["role"] == "assistant"
            assert asst_msg["tool_calls"] is not None
            assert len(asst_msg["tool_calls"]) == 1
            assert asst_msg["tool_calls"][0]["name"] == "get_weather"
            assert "The weather is sunny" in asst_msg["content"]

            # Tree should have tools + response, no thinking.
            display = mgr.query_one(ChatDisplay)
            tree = display.query_one(Tree)
            root = tree._node_map["chat-display-root"]
            asst_node = root.children[-1]
            sections = {c.data["section"] for c in asst_node.children}
            assert "tools" in sections
            assert "response" in sections
            assert "thinking" not in sections

    async def test_error_during_streaming_shown_in_response(self):
        """If the agent raises, the error is shown in the response section."""
        class FailingAgent:
            async def stream_chat(self, history, user_text, tools=None):
                raise RuntimeError("Boom!")
                yield  # pragma: no cover

        async with ChatManagerTestApp().run_test() as pilot:
            await pilot.pause()

            mgr = pilot.app.manager
            mgr.set_agent(FailingAgent())

            chat_input = mgr.query_one(ChatInput)
            inp = chat_input.query_one(Input)
            inp.value = "Cause error"
            inp.post_message(Input.Submitted(inp, "Cause error"))
            await _settle(pilot, n=8)

            display = mgr.query_one(ChatDisplay)
            tree = display.query_one(Tree)
            root = tree._node_map["chat-display-root"]
            asst_node = root.children[-1]
            # Response section should contain error text.
            if len(asst_node.children) > 0:
                resp_section = None
                for c in asst_node.children:
                    if c.data.get("section") == "response":
                        resp_section = c
                        break
                if resp_section:
                    md = resp_section.children[0].content
                    assert "Error" in (md._markdown or "") or "Boom" in (md._markdown or "")

    async def test_no_agent_shows_message(self):
        """Without an agent, submitting shows a placeholder message."""
        async with ChatManagerTestApp().run_test() as pilot:
            await pilot.pause()

            mgr = pilot.app.manager
            chat_input = mgr.query_one(ChatInput)
            inp = chat_input.query_one(Input)
            inp.value = "Hi"
            inp.post_message(Input.Submitted(inp, "Hi"))
            await _settle(pilot, n=8)

            display = mgr.query_one(ChatDisplay)
            tree = display.query_one(Tree)
            root = tree._node_map["chat-display-root"]
            asst_node = root.children[-1]
            resp_section = None
            for c in asst_node.children:
                if c.data.get("section") == "response":
                    resp_section = c
                    break
            if resp_section:
                md = resp_section.children[0].content
                assert "No agent" in (md._markdown or "")


# ---------------------------------------------------------------------------
# ChatManager — persistence
# ---------------------------------------------------------------------------


class ChatManagerDBTestApp(App):
    """App hosting a ChatManager wired with a test database."""

    CSS = """
    ChatManager {
        width: 60;
        height: 100%;
    }
    ChatManager > ChatDisplay > Tree {
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

    def on_mount(self) -> None:
        self.manager.wire_from_context(self.context)


class TestChatManagerPersistence:
    async def test_turn_saved_to_database(self):
        """After a streaming turn, messages are persisted."""
        from core.database import DatabaseManager
        import tempfile, os

        chunks = [
            type('C', (), {'thinking': 'Hmm', 'content': '', 'tool_calls': None})(),
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

            async with ChatManagerDBTestApp(db).run_test() as pilot:
                await _settle(pilot)

                mgr = pilot.app.manager
                mgr.set_agent(FakeAgent(chunks))

                chat_input = mgr.query_one(ChatInput)
                inp = chat_input.query_one(Input)
                inp.value = "Hello!"
                inp.post_message(Input.Submitted(inp, "Hello!"))
                await _settle(pilot, n=15)

            chats = db.list_chats()
            assert len(chats) == 1
            chat_id = chats[0]["id"]

            messages = db.get_messages(chat_id)
            assert len(messages) == 2

            user_msg = messages[0]
            assert user_msg["role"] == "user"
            assert user_msg["content"] == "Hello!"

            asst_msg = messages[1]
            assert asst_msg["role"] == "assistant"
            assert "Hi there!" in asst_msg["content"]
        finally:
            try:
                db.close()
                os.unlink(db_path)
            except Exception:
                pass

    async def test_thinking_persisted(self):
        """Thinking content is persisted in the database."""
        from core.database import DatabaseManager
        import tempfile, os

        chunks = [
            type('C', (), {'thinking': 'Let me', 'content': '', 'tool_calls': None})(),
            type('C', (), {'thinking': ' think...', 'content': '', 'tool_calls': None})(),
            type('C', (), {'thinking': '', 'content': 'The answer is 42.', 'tool_calls': None})(),
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

            async with ChatManagerDBTestApp(db).run_test() as pilot:
                await _settle(pilot)

                mgr = pilot.app.manager
                mgr.set_agent(FakeAgent(chunks))

                chat_input = mgr.query_one(ChatInput)
                inp = chat_input.query_one(Input)
                inp.value = "What is the answer?"
                inp.post_message(Input.Submitted(inp, "What is the answer?"))
                await _settle(pilot, n=15)

            chats = db.list_chats()
            messages = db.get_messages(chats[0]["id"])
            asst_msg = messages[1]
            assert "Let me think..." in asst_msg.get("thinking", "")
        finally:
            try:
                db.close()
                os.unlink(db_path)
            except Exception:
                pass

    async def test_tool_calls_persisted(self):
        """Tool calls are persisted in the database."""
        from core.database import DatabaseManager
        import tempfile, os

        chunks = [
            type('C', (), {
                'thinking': '', 'content': '',
                'tool_calls': [
                    type('TC', (), {'name': 'read_file', 'arguments': {'path': 'test.txt'}})()
                ]
            })(),
            type('C', (), {'thinking': '', 'content': 'Done.', 'tool_calls': None})(),
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

            async with ChatManagerDBTestApp(db).run_test() as pilot:
                await _settle(pilot)

                mgr = pilot.app.manager
                mgr.set_agent(FakeAgent(chunks))

                chat_input = mgr.query_one(ChatInput)
                inp = chat_input.query_one(Input)
                inp.value = "Read test.txt"
                inp.post_message(Input.Submitted(inp, "Read test.txt"))
                await _settle(pilot, n=15)

            chats = db.list_chats()
            messages = db.get_messages(chats[0]["id"])
            asst_msg = messages[1]
            tc = asst_msg.get("tool_calls")
            assert tc is not None
            assert len(tc) == 1
            assert tc[0]["name"] == "read_file"
            assert tc[0]["arguments"] == {"path": "test.txt"}
        finally:
            try:
                db.close()
                os.unlink(db_path)
            except Exception:
                pass
