"""Tests for slash command dispatch in ChatManager.

Tests that:
- /command text is dispatched to the command registry
- Unknown commands show an error message
- Command results appear as system messages
- /new resets the conversation
"""

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Input

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


def _make_chunk(**kwargs):
    defaults = {"thinking": "", "content": "", "tool_calls": None}
    defaults.update(kwargs)
    return type("C", (), defaults)()


# ---------------------------------------------------------------------------
# Tests — slash command detection
# ---------------------------------------------------------------------------


class TestCommandDispatch:
    async def test_slash_command_dispatched(self):
        """Typing /help dispatches to the command registry."""
        from core.commands import register_command, reset_commands

        reset_commands()

        results = []

        @register_command(name="testcmd", description="A test command")
        async def testcmd(app, args: str) -> str:
            results.append(args)
            return f"result: {args}"

        try:
            async with ChatManagerTestApp().run_test() as pilot:
                await pilot.pause()

                mgr = pilot.app.manager
                chat_input = mgr.query_one(ChatInput)
                inp = chat_input.query_one(Input)

                # Simulate typing /testcmd hello
                inp.value = "/testcmd hello"
                inp.post_message(Input.Submitted(inp, "/testcmd hello"))
                await _settle(pilot, n=10)

                # Command should have been called with args "hello"
                assert results == ["hello"]
        finally:
            reset_commands()

    async def test_unknown_command_shows_error(self):
        """Typing an unknown /command shows an error system message."""
        from core.commands import reset_commands

        reset_commands()

        async with ChatManagerTestApp().run_test() as pilot:
            await pilot.pause()

            mgr = pilot.app.manager
            chat_input = mgr.query_one(ChatInput)
            inp = chat_input.query_one(Input)

            inp.value = "/unknown"
            inp.post_message(Input.Submitted(inp, "/unknown"))
            await _settle(pilot, n=10)

            # The display should have a system message with "Unknown command"
            display = mgr.query_one(ChatDisplay)
            tree = display.query_one(Tree)
            root = tree._node_map["chat-display-root"]

            # First child is the user message showing "/unknown"
            # Second child should be a system message
            assert len(root.children) >= 2
            system_node = root.children[1]
            assert system_node.data["role"] == "system"
            md = system_node.children[0].content
            assert "Unknown command" in (md._markdown or "")

    async def test_command_with_no_args(self):
        """A /command with no arguments passes empty string as args."""
        from core.commands import register_command, reset_commands

        reset_commands()

        captured_args = []

        @register_command(name="ping", description="Ping")
        async def ping(app, args: str) -> str:
            captured_args.append(args)
            return "pong"

        try:
            async with ChatManagerTestApp().run_test() as pilot:
                await pilot.pause()

                mgr = pilot.app.manager
                chat_input = mgr.query_one(ChatInput)
                inp = chat_input.query_one(Input)

                inp.value = "/ping"
                inp.post_message(Input.Submitted(inp, "/ping"))
                await _settle(pilot, n=10)

                assert captured_args == [""]
        finally:
            reset_commands()

    async def test_command_result_shown_as_system_message(self):
        """The return value of a command is shown as a system message."""
        from core.commands import register_command, reset_commands

        reset_commands()

        @register_command(name="greet", description="Greet")
        async def greet(app, args: str) -> str:
            return f"Hello, {args}!"

        try:
            async with ChatManagerTestApp().run_test() as pilot:
                await pilot.pause()

                mgr = pilot.app.manager
                chat_input = mgr.query_one(ChatInput)
                inp = chat_input.query_one(Input)

                inp.value = "/greet World"
                inp.post_message(Input.Submitted(inp, "/greet World"))
                await _settle(pilot, n=10)

                display = mgr.query_one(ChatDisplay)
                tree = display.query_one(Tree)
                root = tree._node_map["chat-display-root"]

                # Second child should be a system message with the result
                system_node = root.children[1]
                assert system_node.data["role"] == "system"
                md = system_node.children[0].content
                assert "Hello, World!" in (md._markdown or "")
        finally:
            reset_commands()

    async def test_command_with_none_result_shows_nothing(self):
        """When a command returns None, no system message is shown."""
        from core.commands import register_command, reset_commands

        reset_commands()

        @register_command(name="silent", description="No output")
        async def silent(app, args: str) -> None:
            pass

        try:
            async with ChatManagerTestApp().run_test() as pilot:
                await pilot.pause()

                mgr = pilot.app.manager
                chat_input = mgr.query_one(ChatInput)
                inp = chat_input.query_one(Input)

                inp.value = "/silent"
                inp.post_message(Input.Submitted(inp, "/silent"))
                await _settle(pilot, n=10)

                display = mgr.query_one(ChatDisplay)
                tree = display.query_one(Tree)
                root = tree._node_map["chat-display-root"]

                # Only the user message showing "/silent" should exist
                # (no system message since result was None/empty)
                assert len(root.children) == 1
                assert root.children[0].data["role"] == "user"
        finally:
            reset_commands()

    async def test_command_error_shown_as_system_message(self):
        """When a command raises an exception, the error is shown."""
        from core.commands import register_command, reset_commands

        reset_commands()

        @register_command(name="boom", description="Explode")
        async def boom(app, args: str) -> str:
            raise RuntimeError("Kaboom!")

        try:
            async with ChatManagerTestApp().run_test() as pilot:
                await pilot.pause()

                mgr = pilot.app.manager
                chat_input = mgr.query_one(ChatInput)
                inp = chat_input.query_one(Input)

                inp.value = "/boom"
                inp.post_message(Input.Submitted(inp, "/boom"))
                await _settle(pilot, n=10)

                display = mgr.query_one(ChatDisplay)
                tree = display.query_one(Tree)
                root = tree._node_map["chat-display-root"]

                # System message with error
                system_node = root.children[1]
                assert system_node.data["role"] == "system"
                md = system_node.children[0].content
                assert "Error" in (md._markdown or "") or "Kaboom" in (md._markdown or "")
        finally:
            reset_commands()

    async def test_regular_text_not_treated_as_command(self):
        """Text that doesn't start with / goes through the normal chat flow."""
        from core.commands import register_command, reset_commands

        reset_commands()

        # No agent — should show "No agent configured" rather than
        # trying to dispatch as a command.
        async with ChatManagerTestApp().run_test() as pilot:
            await pilot.pause()

            mgr = pilot.app.manager
            chat_input = mgr.query_one(ChatInput)
            inp = chat_input.query_one(Input)

            inp.value = "Hello, not a command"
            inp.post_message(Input.Submitted(inp, "Hello, not a command"))
            await _settle(pilot, n=10)

            display = mgr.query_one(ChatDisplay)
            tree = display.query_one(Tree)
            root = tree._node_map["chat-display-root"]

            # Should have a user message + assistant response (no system)
            assert len(root.children) >= 2
            user_node = root.children[0]
            assert user_node.data["role"] == "user"

    async def test_slash_with_spaces_not_command(self):
        """Text that has / but not at position 0 is not a command.

        Actually, '/ help' (with space) IS treated as a command with
        name being empty string or the first word.  But '/help' is a
        proper command.  The key distinction is that the text starts
        with '/'.
        """
        from core.commands import reset_commands

        reset_commands()

        async with ChatManagerTestApp().run_test() as pilot:
            await pilot.pause()

            mgr = pilot.app.manager
            chat_input = mgr.query_one(ChatInput)
            inp = chat_input.query_one(Input)

            # "/ help" with a space after slash — command name is empty string
            inp.value = "/ help"
            inp.post_message(Input.Submitted(inp, "/ help"))
            await _settle(pilot, n=10)

            display = mgr.query_one(ChatDisplay)
            tree = display.query_one(Tree)
            root = tree._node_map["chat-display-root"]

            # Should show an "Unknown command" message since "" is not registered
            assert len(root.children) >= 2
            system_node = root.children[1]
            assert system_node.data["role"] == "system"


# ---------------------------------------------------------------------------
# Tests — new conversation
# ---------------------------------------------------------------------------


class TestNewConversation:
    async def test_new_conversation_clears_display(self):
        """new_conversation() clears the display."""
        async with ChatManagerTestApp().run_test() as pilot:
            await pilot.pause()

            mgr = pilot.app.manager

            # Add some content first
            mgr._chat_display.add_user_message("Hello")
            await _settle(pilot)

            display = mgr.query_one(ChatDisplay)
            tree = display.query_one(Tree)
            root = tree._node_map["chat-display-root"]
            assert len(root.children) >= 1

            mgr.new_conversation()
            await _settle(pilot)

            root = tree._node_map["chat-display-root"]
            # Display is cleared, then a system message is added
            assert len(root.children) == 1
            assert root.children[0].data["role"] == "system"

    async def test_new_conversation_resets_history(self):
        """new_conversation() resets the internal history."""
        async with ChatManagerTestApp().run_test() as pilot:
            await pilot.pause()

            mgr = pilot.app.manager
            mgr._history.append({"role": "user", "content": "test"})

            mgr.new_conversation()

            assert mgr._history == []

    async def test_new_conversation_creates_new_db_chat(self):
        """new_conversation() creates a new chat in the database."""
        from core.database import DatabaseManager
        import tempfile, os
        from core.config import Config
        from context import AppContext

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
            db_path = tf.name

        try:
            db = DatabaseManager(db_path)
            cfg = Config([])

            class DBTestApp(App):
                CSS = """
                ChatManager { width: 60; height: 100%; }
                ChatManager > ChatDisplay > Tree { height: 1fr; }
                """

                def __init__(self, db):
                    self._test_db = db
                    self.context = AppContext(
                        database=db, config=cfg, working_directory="/tmp",
                    )
                    super().__init__()

                def compose(self) -> ComposeResult:
                    self.manager = ChatManager()
                    yield self.manager

                def on_mount(self) -> None:
                    self.manager.wire_from_context(self.context)

            async with DBTestApp(db).run_test() as pilot:
                await _settle(pilot)

                mgr = pilot.app.manager
                old_chat_id = mgr._chat_id

                mgr.new_conversation()
                await _settle(pilot)

                new_chat_id = mgr._chat_id
                assert new_chat_id is not None
                assert new_chat_id != old_chat_id

                # There should be two chats in the database
                chats = db.list_chats()
                assert len(chats) == 2
        finally:
            try:
                db.close()
                os.unlink(db_path)
            except Exception:
                pass