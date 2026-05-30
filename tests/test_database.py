"""Tests for the database system (core/database.py)."""

import json
import os
import pytest


@pytest.fixture
def db(tmp_path):
    """Create a fresh DatabaseManager backed by a temp SQLite file."""
    from core.database import DatabaseManager

    db_path = str(tmp_path / "test.db")
    manager = DatabaseManager(db_path)
    yield manager
    manager.close()


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------


class TestInitialization:
    def test_creates_database_file(self, tmp_path):
        from core.database import DatabaseManager

        db_path = str(tmp_path / "test.db")
        DatabaseManager(db_path)
        assert os.path.isfile(db_path)

    def test_creates_tables(self, db):
        """All expected tables exist after construction."""
        tables = db._execute("SELECT name FROM sqlite_master WHERE type='table'")
        names = {row[0] for row in tables}
        assert "chats" in names
        assert "messages" in names
        assert "agents" in names
        assert "todos" in names
        assert "input_history" in names

    def test_double_initialization_is_idempotent(self, tmp_path):
        from core.database import DatabaseManager

        db_path = str(tmp_path / "test.db")
        mgr1 = DatabaseManager(db_path)
        mgr1.close()
        mgr2 = DatabaseManager(db_path)
        # Should not raise
        tables = mgr2._execute("SELECT name FROM sqlite_master WHERE type='table'")
        assert len(list(tables)) >= 5  # 5 user tables + sqlite_sequence
        mgr2.close()


# ---------------------------------------------------------------------------
# Chat CRUD
# ---------------------------------------------------------------------------


class TestChatCRUD:
    def test_create_chat_returns_id(self, db):
        chat_id = db.create_chat("Test Chat")
        assert chat_id
        assert isinstance(chat_id, str)

    def test_create_chat_default_title(self, db):
        chat_id = db.create_chat()
        chat = db.get_chat(chat_id)
        assert chat["title"] == ""

    def test_get_chat_returns_dict(self, db):
        chat_id = db.create_chat("My Chat")
        chat = db.get_chat(chat_id)
        assert chat["id"] == chat_id
        assert chat["title"] == "My Chat"
        assert "created_at" in chat
        assert "updated_at" in chat

    def test_get_chat_missing_returns_none(self, db):
        assert db.get_chat("nonexistent") is None

    def test_list_chats_empty(self, db):
        assert db.list_chats() == []

    def test_list_chats_returns_all(self, db):
        db.create_chat("A")
        db.create_chat("B")
        chats = db.list_chats()
        assert len(chats) == 2
        titles = {c["title"] for c in chats}
        assert titles == {"A", "B"}

    def test_list_chats_ordered_by_updated(self, db):
        id1 = db.create_chat("First")
        id2 = db.create_chat("Second")
        db.update_chat(id1, "First Updated")

        chats = db.list_chats()
        # Most recently updated first
        assert chats[0]["id"] == id1
        assert chats[1]["id"] == id2

    def test_update_chat_title(self, db):
        chat_id = db.create_chat("Old")
        db.update_chat(chat_id, "New")
        assert db.get_chat(chat_id)["title"] == "New"

    def test_update_chat_missing_does_nothing(self, db):
        # Should not raise
        db.update_chat("nonexistent", "Nope")

    def test_delete_chat_removes_it(self, db):
        chat_id = db.create_chat("DeleteMe")
        db.delete_chat(chat_id)
        assert db.get_chat(chat_id) is None

    def test_delete_chat_cascades_messages(self, db):
        chat_id = db.create_chat("WithMessages")
        db.save_section(chat_id, "t1", "user", "hello")
        db.delete_chat(chat_id)
        assert db.load_sections(chat_id) == []

    def test_delete_chat_missing_does_not_raise(self, db):
        db.delete_chat("nonexistent")


# ---------------------------------------------------------------------------
# Message CRUD
# ---------------------------------------------------------------------------


class TestMessageCRUD:
    def test_save_section_returns_id(self, db):
        chat_id = db.create_chat()
        msg_id = db.save_section(chat_id, "t1", "user", "hello")
        assert isinstance(msg_id, int)

    def test_save_section_stores_data(self, db):
        chat_id = db.create_chat()
        db.save_section(chat_id, "t1", "user", "hello")
        sections = db.load_sections(chat_id)
        assert len(sections) == 1
        assert sections[0]["content_type"] == "user"
        assert sections[0]["content"] == "hello"
        assert sections[0]["turn_id"] == "t1"

    def test_save_section_tool_call_json(self, db):
        chat_id = db.create_chat()
        tc = '{"name": "read_file", "arguments": {"path": "/x"}}'
        db.save_section(chat_id, "t1", "tool_call", tc)

        sections = db.load_sections(chat_id)
        assert sections[0]["content_type"] == "tool_call"
        assert sections[0]["content"] == tc

    def test_load_sections_empty_chat(self, db):
        chat_id = db.create_chat()
        assert db.load_sections(chat_id) == []

    def test_load_sections_ordered_by_id(self, db):
        chat_id = db.create_chat()
        db.save_section(chat_id, "t1", "user", "first")
        db.save_section(chat_id, "t1", "response", "second")

        sections = db.load_sections(chat_id)
        assert sections[0]["content"] == "first"
        assert sections[1]["content"] == "second"

    def test_load_sections_unknown_chat_returns_empty(self, db):
        assert db.load_sections("nonexistent") == []

    def test_delete_messages(self, db):
        chat_id = db.create_chat()
        db.save_section(chat_id, "t1", "user", "hello")
        db.delete_messages(chat_id)
        assert db.load_sections(chat_id) == []

    def test_reconstruct_history_basic_turn(self, db):
        """reconstruct_history builds user + assistant dicts from flat sections."""
        chat_id = db.create_chat()
        db.save_section(chat_id, "t1", "user", "What is 2+2?")
        db.save_section(chat_id, "t1", "thinking", "Hmm...")
        db.save_section(chat_id, "t1", "response", "4")

        history = db.reconstruct_history(chat_id)
        assert len(history) == 2
        assert history[0] == {"role": "user", "content": "What is 2+2?"}
        asst = history[1]
        assert asst["role"] == "assistant"
        assert asst["content"] == "4"
        assert asst["thinking"] == "Hmm..."

    def test_reconstruct_history_tool_calls(self, db):
        """Tool-call sections are decoded from JSON."""
        chat_id = db.create_chat()
        db.save_section(chat_id, "t1", "user", "Read foo.py")
        db.save_section(
            chat_id, "t1", "tool_call",
            '{"name": "read_file", "arguments": {"path": "foo.py"}}'
        )
        db.save_section(chat_id, "t1", "response", "Here is the file.")

        history = db.reconstruct_history(chat_id)
        asst = history[1]
        assert asst["tool_calls"] == [
            {"name": "read_file", "arguments": {"path": "foo.py"}}
        ]

    def test_reconstruct_history_multiple_thinking_sections(self, db):
        """Multiple thinking sections in one turn are concatenated."""
        chat_id = db.create_chat()
        db.save_section(chat_id, "t1", "user", "Go")
        db.save_section(chat_id, "t1", "thinking", "First thought ")
        db.save_section(chat_id, "t1", "tool_call", '{"name": "run", "arguments": {"cmd": "ls"}}')
        db.save_section(chat_id, "t1", "thinking", "Second thought")
        db.save_section(chat_id, "t1", "response", "Done.")

        history = db.reconstruct_history(chat_id)
        asst = history[1]
        assert asst["thinking"] == "First thought Second thought"

    def test_reconstruct_history_system_messages(self, db):
        """System sections become system-role messages."""
        chat_id = db.create_chat()
        db.save_section(chat_id, "t1", "user", "Hello")
        db.save_section(chat_id, "t1", "system", "Chat cleared.")

        history = db.reconstruct_history(chat_id)
        assert history[0]["role"] == "user"
        assert history[1]["role"] == "system"
        assert history[1]["content"] == "Chat cleared."

    def test_reconstruct_history_empty_chat(self, db):
        chat_id = db.create_chat()
        assert db.reconstruct_history(chat_id) == []

    def test_reconstruct_history_strips_internal_turn_id(self, db):
        """The _turn_id field is internal and does not leak to callers."""
        chat_id = db.create_chat()
        db.save_section(chat_id, "t1", "user", "Hi")
        db.save_section(chat_id, "t1", "response", "Hey")

        history = db.reconstruct_history(chat_id)
        asst = history[1]
        assert "_turn_id" in asst  # internal, used for grouping
        assert asst["role"] == "assistant"
        assert asst["content"] == "Hey"


# ---------------------------------------------------------------------------
# Agent CRUD
# ---------------------------------------------------------------------------


class TestAgentCRUD:
    def test_create_agent_returns_id(self, db):
        agent_id = db.create_agent("Helper", "A helpful agent", "You are helpful.")
        assert agent_id
        assert isinstance(agent_id, str)

    def test_create_agent_stores_all_fields(self, db):
        agent_id = db.create_agent("Helper", "Desc", "Prompt", model="llama3")
        agent = db.get_agent(agent_id)
        assert agent["name"] == "Helper"
        assert agent["description"] == "Desc"
        assert agent["template"] == "Prompt"
        assert agent["model"] == "llama3"

    def test_create_agent_default_model(self, db):
        agent_id = db.create_agent("X", "D", "P")
        assert db.get_agent(agent_id)["model"] == ""

    def test_get_agent_missing_returns_none(self, db):
        assert db.get_agent("nonexistent") is None

    def test_list_agents_empty(self, db):
        assert db.list_agents() == []

    def test_list_agents_returns_all(self, db):
        db.create_agent("A", "DA", "PA")
        db.create_agent("B", "DB", "PB")
        assert len(db.list_agents()) == 2

    def test_delete_agent(self, db):
        agent_id = db.create_agent("X", "D", "P")
        db.delete_agent(agent_id)
        assert db.get_agent(agent_id) is None

    def test_delete_agent_missing_does_not_raise(self, db):
        db.delete_agent("nonexistent")

    def test_seed_agents_inserts_new(self, db):
        agents = [
            {
                "id": "coding-assistant",
                "name": "Coding Assistant",
                "description": "Helps with code",
                "template": "You are a coding assistant.",
                "model": "codellama",
            }
        ]
        db.seed_agents(agents)
        assert db.get_agent("coding-assistant") is not None

    def test_seed_agents_does_not_overwrite_existing(self, db):
        db.create_agent("Original", "Original desc", "Original prompt", agent_id="existing")
        agents = [
            {
                "id": "existing",
                "name": "Overwrite Attempt",
                "description": "Should not appear",
                "template": "Should not appear",
            }
        ]
        db.seed_agents(agents)
        agent = db.get_agent("existing")
        assert agent["name"] == "Original"


# ---------------------------------------------------------------------------
# Todo CRUD
# ---------------------------------------------------------------------------


class TestTodoCRUD:
    def test_create_todo_returns_id(self, db):
        todo_id = db.create_todo("Buy milk")
        assert isinstance(todo_id, int)

    def test_create_todo_with_description(self, db):
        todo_id = db.create_todo("Task", description="Do the thing")
        todo = db.get_todo(todo_id)
        assert todo["title"] == "Task"
        assert todo["description"] == "Do the thing"
        assert todo["status"] == "pending"

    def test_get_todo_missing_returns_none(self, db):
        assert db.get_todo(999) is None

    def test_list_todos_empty(self, db):
        assert db.list_todos() == []

    def test_list_todos_filter_by_status(self, db):
        db.create_todo("Task 1")  # pending
        tid2 = db.create_todo("Task 2")
        db.update_todo(tid2, status="done")

        pending = db.list_todos(status="pending")
        assert len(pending) == 1
        assert pending[0]["title"] == "Task 1"

        done = db.list_todos(status="done")
        assert len(done) == 1
        assert done[0]["title"] == "Task 2"

    def test_list_todos_no_filter_returns_all(self, db):
        db.create_todo("A")
        db.create_todo("B")
        assert len(db.list_todos()) == 2

    def test_update_todo_status(self, db):
        todo_id = db.create_todo("Task")
        db.update_todo(todo_id, status="in_progress")
        assert db.get_todo(todo_id)["status"] == "in_progress"

    def test_update_todo_title(self, db):
        todo_id = db.create_todo("Old")
        db.update_todo(todo_id, title="New")
        assert db.get_todo(todo_id)["title"] == "New"

    def test_update_todo_multiple_fields(self, db):
        todo_id = db.create_todo("Task")
        db.update_todo(todo_id, title="Updated", status="done", description="Done!")
        todo = db.get_todo(todo_id)
        assert todo["title"] == "Updated"
        assert todo["status"] == "done"
        assert todo["description"] == "Done!"

    def test_delete_todo(self, db):
        todo_id = db.create_todo("DeleteMe")
        db.delete_todo(todo_id)
        assert db.get_todo(todo_id) is None

    def test_delete_todo_missing_does_not_raise(self, db):
        db.delete_todo(999)


# ---------------------------------------------------------------------------
# Input history
# ---------------------------------------------------------------------------


class TestInputHistory:
    def test_add_input_returns_id(self, db):
        input_id = db.add_input("hello")
        assert isinstance(input_id, int)

    def test_get_input_history_returns_items(self, db):
        db.add_input("first")
        db.add_input("second")
        history = db.get_input_history()
        assert history == ["second", "first"]

    def test_get_input_history_respects_limit(self, db):
        for i in range(10):
            db.add_input(f"msg{i}")
        history = db.get_input_history(limit=5)
        assert len(history) == 5
        # Most recent first
        assert history[0] == "msg9"

    def test_get_input_history_empty(self, db):
        assert db.get_input_history() == []

    def test_duplicate_input_not_stored(self, db):
        db.add_input("repeat")
        db.add_input("repeat")
        assert len(db.get_input_history()) == 1


# ---------------------------------------------------------------------------
# Provider swapping
# ---------------------------------------------------------------------------


class TestProvider:
    def test_sqlite_provider_is_default(self, db):
        from core.database import SQLiteProvider

        assert isinstance(db._provider, SQLiteProvider)
