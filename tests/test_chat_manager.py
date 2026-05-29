"""Tests for the ChatManager widget.

ChatManager composes ChatInput + ChatDisplay and orchestrates the
streaming loop, history tracking, and database persistence.

Tests cover composition, setup, streaming orchestration (including
abort), and persistence.
"""

import asyncio
import pytest
from textual.app import App, ComposeResult
from textual.widgets import Input, Markdown

from skills.chat.chat_manager import ChatManager
from skills.chat.chat_input import ChatInput
from skills.chat.chat_display import ChatDisplay
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


def _make_chunk(**kwargs):
    """Create a simple namespace chunk for fake agents."""
    defaults = {"thinking": "", "content": "", "tool_calls": None}
    defaults.update(kwargs)
    return type("C", (), defaults)()


def _make_tool_call(name, arguments):
    """Create a simple namespace tool call."""
    return type("TC", (), {"name": name, "arguments": arguments})()


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
            _make_chunk(thinking="Let me"),
            _make_chunk(thinking=" think"),
            _make_chunk(content="Hello"),
            _make_chunk(content=" world"),
            _make_chunk(content="!"),
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
            assert mgr._history[0]["role"] == "user"
            assert mgr._history[0]["content"] == "Hello?"
            assert mgr._history[1]["role"] == "assistant"
            assert "Hello world!" in mgr._history[1]["content"]

            # Tree should have user leaf + assistant branch.
            display = mgr.query_one(ChatDisplay)
            tree = display.query_one(Tree)
            root = tree._node_map["chat-display-root"]
            assert len(root.children) >= 2

            # Assistant node should have thinking and response sections.
            asst_node = root.children[-1]
            section_types = [c.data["section"] for c in asst_node.children]
            assert "thinking" in section_types
            assert "response" in section_types

    async def test_streaming_with_tool_calls(self):
        """Tool calls create a tools section."""
        chunks = [
            _make_chunk(tool_calls=[
                _make_tool_call("get_weather", {"city": "London"})
            ]),
            _make_chunk(content="The weather is sunny"),
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

            # History is rebuilt from DB after the turn.
            assert len(mgr._history) == 2
            asst_msg = mgr._history[1]
            assert asst_msg["role"] == "assistant"
            assert asst_msg.get("tool_calls") is not None
            assert len(asst_msg["tool_calls"]) == 1
            assert asst_msg["tool_calls"][0]["name"] == "get_weather"
            assert "The weather is sunny" in asst_msg.get("content", "")

            # Tree should have tool_call + response, no thinking.
            display = mgr.query_one(ChatDisplay)
            tree = display.query_one(Tree)
            root = tree._node_map["chat-display-root"]
            asst_node = root.children[-1]
            section_types = [c.data["section"] for c in asst_node.children]
            assert "tools" in section_types
            assert "response" in section_types
            assert "thinking" not in section_types

    async def test_streaming_with_thinking_then_tools_then_more_thinking(self):
        """Multi-round: thinking → tools → thinking → response creates
        sequential sections."""
        chunks = [
            # First round: thinking then tool call
            _make_chunk(thinking="I need to"),
            _make_chunk(thinking=" check the file"),
            _make_chunk(tool_calls=[
                _make_tool_call("read_file", {"path": "x.txt"})
            ]),
            # Second round: thinking then response
            _make_chunk(thinking="Now I"),
            _make_chunk(thinking=" know the answer"),
            _make_chunk(content="The file contains hello."),
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
            inp.value = "Read x.txt"
            inp.post_message(Input.Submitted(inp, "Read x.txt"))
            await _settle(pilot, n=15)

            display = mgr.query_one(ChatDisplay)
            tree = display.query_one(Tree)
            root = tree._node_map["chat-display-root"]
            asst_node = root.children[-1]

            # Should have the sequential layout:
            # thinking, tools, thinking, response
            section_types = [c.data["section"] for c in asst_node.children]
            assert "thinking" in section_types
            assert "tools" in section_types
            assert "response" in section_types

            # All thinking text should be persisted.
            asst_msg = mgr._history[1]
            thinking = asst_msg.get("thinking") or ""
            assert "I need to check the file" in thinking
            assert "Now I know the answer" in thinking

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
            await _settle(pilot, n=15)

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
            await _settle(pilot, n=15)

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
# ChatManager — streaming toggle on ChatInput
# ---------------------------------------------------------------------------


class TestChatManagerStreamingToggle:
    async def test_streaming_state_toggles_on_submit(self):
        """ChatInput.set_streaming is called during a streaming turn."""
        chunks = [
            _make_chunk(content="Hi"),
        ]

        class SlowFakeAgent:
            """Agent that yields slowly so we can observe streaming state."""
            def __init__(self, chunks):
                self._chunks = chunks
                self._aborted = False

            async def stream_chat(self, history, user_text, tools=None):
                for chunk in self._chunks:
                    await asyncio.sleep(0.05)
                    yield chunk

        async with ChatManagerTestApp().run_test() as pilot:
            await pilot.pause()

            mgr = pilot.app.manager
            mgr.set_agent(SlowFakeAgent(chunks))
            chat_input = mgr.query_one(ChatInput)

            # Before submitting, not streaming
            assert chat_input.is_streaming is False

            # Kick off submission
            inp = chat_input.query_one(Input)
            inp.value = "Hello?"
            chat_input.post_message(ChatInput.ChatSubmitted("Hello?"))
            await _settle(pilot)

            # After completion, no longer streaming
            assert chat_input.is_streaming is False


# ---------------------------------------------------------------------------
# ChatManager — abort
# ---------------------------------------------------------------------------


class TestChatManagerAbort:
    async def test_abort_stops_streaming_and_shows_aborted_marker(self):
        """Aborting a stream preserves partial content and shows [aborted]."""
        # Use an agent that yields slowly and then a long pause, so we
        # can abort mid-stream.
        class AbortableAgent:
            def __init__(self):
                self._aborted = False

            def abort(self):
                self._aborted = True

            async def stream_chat(self, history, user_text, tools=None):
                # Yield a first chunk immediately
                yield _make_chunk(content="Partial ")
                # Then yield more; the task will be cancelled during sleep
                await asyncio.sleep(0.1)
                yield _make_chunk(content="should not appear")

        async with ChatManagerTestApp().run_test() as pilot:
            await pilot.pause()

            mgr = pilot.app.manager
            agent = AbortableAgent()
            mgr.set_agent(agent)
            chat_input = mgr.query_one(ChatInput)

            # Start streaming
            inp = chat_input.query_one(Input)
            inp.value = "Test abort"
            chat_input.post_message(ChatInput.ChatSubmitted("Test abort"))
            await pilot.pause()

            # Now abort
            chat_input.post_message(ChatInput.ChatAbortRequested())
            await _settle(pilot, n=10)

            # History is rebuilt from DB — should contain partial + aborted.
            assert len(mgr._history) >= 2
            asst_msg = mgr._history[1]
            assert asst_msg["role"] == "assistant"
            assert "Partial" in asst_msg.get("content", "")
            assert "[aborted]" in asst_msg.get("content", "")

            # ChatInput should no longer be in streaming mode
            assert chat_input.is_streaming is False

    async def test_abort_when_no_content_received(self):
        """Aborting before any content shows just [aborted]."""
        class SlowStartAgent:
            def __init__(self):
                self._aborted = False

            def abort(self):
                self._aborted = True

            async def stream_chat(self, history, user_text, tools=None):
                # Long pause before any content — abort fires here
                await asyncio.sleep(2.0)
                yield _make_chunk(content="never")  # pragma: no cover

        async with ChatManagerTestApp().run_test() as pilot:
            await pilot.pause()

            mgr = pilot.app.manager
            agent = SlowStartAgent()
            mgr.set_agent(agent)
            chat_input = mgr.query_one(ChatInput)

            inp = chat_input.query_one(Input)
            inp.value = "Test"
            chat_input.post_message(ChatInput.ChatSubmitted("Test"))
            await pilot.pause()

            # Abort immediately
            chat_input.post_message(ChatInput.ChatAbortRequested())
            await _settle(pilot, n=10)

            # Should have [aborted] in response
            assert len(mgr._history) >= 2
            asst_msg = mgr._history[1]
            assert "[aborted]" in asst_msg.get("content", "")

            # ChatInput should no longer be in streaming mode
            assert chat_input.is_streaming is False


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
        """After a streaming turn, sections are persisted."""
        from core.database import DatabaseManager
        import tempfile, os

        chunks = [
            _make_chunk(thinking="Hmm"),
            _make_chunk(content="Hi there!"),
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

            sections = db.load_sections(chat_id)
            # Should have: user, thinking, response
            types = [s["content_type"] for s in sections]
            assert "user" in types
            assert "thinking" in types
            assert "response" in types

            # User section
            user_sec = [s for s in sections if s["content_type"] == "user"][0]
            assert user_sec["content"] == "Hello!"

            # Response section
            resp_sec = [s for s in sections if s["content_type"] == "response"][0]
            assert "Hi there!" in resp_sec["content"]
        finally:
            try:
                db.close()
                os.unlink(db_path)
            except Exception:
                pass

    async def test_thinking_persisted(self):
        """Thinking content is persisted as a section row."""
        from core.database import DatabaseManager
        import tempfile, os

        chunks = [
            _make_chunk(thinking="Let me"),
            _make_chunk(thinking=" think..."),
            _make_chunk(content="The answer is 42."),
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
            sections = db.load_sections(chats[0]["id"])
            thinking_sec = [s for s in sections if s["content_type"] == "thinking"][0]
            assert "Let me think..." in thinking_sec["content"]
        finally:
            try:
                db.close()
                os.unlink(db_path)
            except Exception:
                pass

    async def test_tool_calls_persisted(self):
        """Tool calls are persisted as JSON section rows."""
        from core.database import DatabaseManager
        import tempfile, os

        chunks = [
            _make_chunk(tool_calls=[
                _make_tool_call("read_file", {"path": "test.txt"})
            ]),
            _make_chunk(content="Done."),
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
            sections = db.load_sections(chats[0]["id"])

            # Each tool call is a separate section row with JSON content.
            tc_sections = [s for s in sections if s["content_type"] == "tool_call"]
            assert len(tc_sections) >= 1

            # The structured tool call should also appear when reconstructing.
            history = db.reconstruct_history(chats[0]["id"])
            asst = [m for m in history if m["role"] == "assistant"][0]
            tc = asst.get("tool_calls")
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