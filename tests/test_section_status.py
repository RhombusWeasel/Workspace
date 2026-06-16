"""Tests for the section status column and per-section completion flag."""

from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.database import DatabaseManager


@pytest.fixture
def db():
	"""Create an in-memory database for testing."""
	return DatabaseManager(":memory:")


class TestStatusColumn:
	"""Tests for the status column on the messages table."""

	def test_fresh_db_has_status_column(self, db):
		"""A freshly created database should have the status column."""
		rows = db._execute("PRAGMA table_info(messages)")
		column_names = {row[1] for row in rows}
		assert "status" in column_names

	def test_save_section_defaults_to_complete(self, db):
		"""save_section (one-shot insert) should set status='complete'."""
		chat_id = db.create_chat()
		db.save_section(chat_id, "t1", "user", "Hello")
		sections = db.load_sections(chat_id)
		assert len(sections) == 1
		assert sections[0]["status"] == "complete"

	def test_upsert_streaming_section_defaults_to_streaming(self, db):
		"""upsert_streaming_section should set status='streaming' by default."""
		chat_id = db.create_chat()
		db.upsert_streaming_section(chat_id, "t1", "t1-response-1", "response", "Hello")
		sections = db.load_sections(chat_id)
		assert len(sections) == 1
		assert sections[0]["status"] == "streaming"

	def test_finalize_section_marks_complete(self, db):
		"""finalize_section should set status='complete' for a specific section."""
		chat_id = db.create_chat()
		db.upsert_streaming_section(chat_id, "t1", "t1-response-1", "response", "Hello")
		# Section should be streaming initially.
		sections = db.load_sections(chat_id)
		assert sections[0]["status"] == "streaming"

		# Finalize the section.
		db.finalize_section(chat_id, "t1", "t1-response-1")
		sections = db.load_sections(chat_id)
		assert sections[0]["status"] == "complete"

	def test_finalize_section_does_not_affect_other_sections(self, db):
		"""Finalizing one section should not change other sections."""
		chat_id = db.create_chat()
		db.upsert_streaming_section(chat_id, "t1", "t1-thinking-1", "thinking", "Hmm...")
		db.upsert_streaming_section(chat_id, "t1", "t1-response-1", "response", "Hello")
		# Finalize only the thinking section.
		db.finalize_section(chat_id, "t1", "t1-thinking-1")

		sections = db.load_sections(chat_id)
		thinking = [s for s in sections if s["content_type"] == "thinking"]
		response = [s for s in sections if s["content_type"] == "response"]
		assert thinking[0]["status"] == "complete"
		assert response[0]["status"] == "streaming"

	def test_finalize_sections_for_turn_marks_all(self, db):
		"""finalize_sections_for_turn should mark all streaming sections as complete."""
		chat_id = db.create_chat()
		db.upsert_streaming_section(chat_id, "t1", "t1-thinking-1", "thinking", "Hmm...")
		db.upsert_streaming_section(chat_id, "t1", "t1-response-1", "response", "Hello")
		db.upsert_streaming_section(chat_id, "t1", "t1-response-2", "response", "World")

		db.finalize_sections_for_turn(chat_id, "t1")

		sections = db.load_sections(chat_id)
		for s in sections:
			assert s["status"] == "complete"

	def test_finalize_sections_for_turn_only_affects_target_turn(self, db):
		"""finalize_sections_for_turn should only affect the specified turn."""
		chat_id = db.create_chat()
		db.upsert_streaming_section(chat_id, "t1", "t1-response-1", "response", "First")
		db.upsert_streaming_section(chat_id, "t2", "t2-response-1", "response", "Second")

		db.finalize_sections_for_turn(chat_id, "t1")

		sections = db.load_sections(chat_id)
		t1 = [s for s in sections if s["turn_id"] == "t1"]
		t2 = [s for s in sections if s["turn_id"] == "t2"]
		assert t1[0]["status"] == "complete"
		assert t2[0]["status"] == "streaming"

	def test_finalize_sections_for_turn_is_idempotent(self, db):
		"""Calling finalize_sections_for_turn multiple times should be safe."""
		chat_id = db.create_chat()
		db.upsert_streaming_section(chat_id, "t1", "t1-response-1", "response", "Hello")

		db.finalize_sections_for_turn(chat_id, "t1")
		db.finalize_sections_for_turn(chat_id, "t1")  # Should not error.

		sections = db.load_sections(chat_id)
		assert sections[0]["status"] == "complete"

	def test_save_section_with_explicit_section_id_is_complete(self, db):
		"""save_section with an explicit section_id should still be 'complete'."""
		chat_id = db.create_chat()
		db.save_section(chat_id, "t1", "user", "Hello", section_id="t1-user-1")
		sections = db.load_sections(chat_id)
		assert sections[0]["status"] == "complete"

	def test_load_sections_includes_status(self, db):
		"""load_sections should include the status field in each row."""
		chat_id = db.create_chat()
		db.save_section(chat_id, "t1", "user", "Hello")
		sections = db.load_sections(chat_id)
		assert "status" in sections[0]
		assert sections[0]["status"] == "complete"


class TestStatusMigration:
	"""Tests for the status column migration on existing databases."""

	def test_migration_adds_status_column(self):
		"""An existing DB without the status column should get it via migration."""
		from core.database import SQLiteProvider
		provider = SQLiteProvider()
		import sqlite3
		conn = sqlite3.connect(":memory:")
		conn.row_factory = sqlite3.Row
		conn.execute("PRAGMA journal_mode=WAL")
		conn.execute("PRAGMA foreign_keys=ON")
		# Create tables WITHOUT the status column (old schema).
		conn.executescript("""
			CREATE TABLE IF NOT EXISTS chats (
				id TEXT PRIMARY KEY, title TEXT NOT NULL DEFAULT '',
				created_at TEXT NOT NULL, updated_at TEXT NOT NULL
			);
			CREATE TABLE IF NOT EXISTS messages (
				id INTEGER PRIMARY KEY AUTOINCREMENT,
				chat_id TEXT NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
				turn_id TEXT NOT NULL,
				section_id TEXT NOT NULL DEFAULT '',
				content_type TEXT NOT NULL,
				content TEXT NOT NULL DEFAULT '',
				created_at TEXT NOT NULL
			);
			CREATE INDEX IF NOT EXISTS idx_messages_chat ON messages(chat_id, id);
			CREATE INDEX IF NOT EXISTS idx_messages_section ON messages(chat_id, turn_id, section_id);
		""")
		# Insert some data without status.
		conn.execute(
			"INSERT INTO chats (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
			("c1", "Test", "2024-01-01", "2024-01-01"),
		)
		conn.execute(
			"INSERT INTO messages (chat_id, turn_id, section_id, content_type, content, created_at) "
			"VALUES (?, ?, ?, ?, ?, ?)",
			("c1", "t1", "", "user", "Hello", "2024-01-01"),
		)
		conn.commit()
		provider._conn = conn

		# Now run the migration.
		provider._migrate_messages_table()

		# The status column should exist with default 'complete'.
		rows = conn.execute("SELECT status FROM messages").fetchall()
		assert len(rows) == 1
		assert rows[0][0] == "complete"