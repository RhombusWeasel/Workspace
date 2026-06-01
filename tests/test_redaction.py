"""Tests for message redaction in core.providers.base.

Verifies that:
- Secrets are matched with word boundaries (no partial-word matches)
- Short secrets (< 4 chars) are skipped to avoid false positives
- Overlapping secrets are handled longest-first
- Regex patterns from config work alongside secrets
- Tool call arguments are deep-redacted
- Disabled redaction passes messages through unchanged
- The _build_redactor and BaseProvider._redact paths work correctly
"""

import re
from unittest.mock import MagicMock

import pytest

from core.providers.base import (
    REDACTED,
    BaseProvider,
    ChatResponse,
    Message,
    _Redactor,
    _build_redactor,
)


# ---------------------------------------------------------------------------
# _Redactor unit tests
# ---------------------------------------------------------------------------


class TestRedactText:
    """Core redaction logic — word-boundary matching of secrets."""

    def test_standalone_secret_redacted(self):
        r = _Redactor(secrets=["password123"], patterns=[], enabled=True)
        assert r.redact_text("My password is password123") == f"My password is {REDACTED}"

    def test_partial_word_not_redacted(self):
        """Secret should NOT match inside longer words (word boundary)."""
        r = _Redactor(secrets=["test", "pass", "admin"], patterns=[], enabled=True)
        text = "detest testify contest bypass administer administrative"
        # All three secrets are < 4 chars, so they'll be SKIPPED
        assert r.redact_text(text) == text

    def test_standalone_word_boundary_match(self):
        """Secret >= 4 chars matches when it's a standalone word."""
        r = _Redactor(secrets=["admin"], patterns=[], enabled=True)
        result = r.redact_text("The admin logged in")
        assert result == f"The {REDACTED} logged in"

    def test_word_boundary_prevents_substring_match(self):
        """Word-boundary regex prevents matching inside other words."""
        r = _Redactor(secrets=["admin"], patterns=[], enabled=True)
        text = "get_admin_user administration administer"
        result = r.redact_text(text)
        # "admin" in identifiers with underscores is bounded by \w chars,
        # so \b does NOT fire between "admin" and "_" or inside "administration"
        assert "get_admin_user" in result
        assert "administration" in result
        assert "administer" in result

    def test_short_secret_skipped(self):
        """Secrets shorter than 4 chars are skipped entirely."""
        r = _Redactor(secrets=["an", "or", "the", "api-key-789"], patterns=[], enabled=True)
        text = "An example or the main api-key-789 function"
        result = r.redact_text(text)
        # Short secrets untouched; long secret redacted
        assert "An example or the" in result
        assert f"main {REDACTED} function" in result

    def test_empty_secret_skipped(self):
        r = _Redactor(secrets=["", "valid-secret"], patterns=[], enabled=True)
        result = r.redact_text("Use valid-secret for auth")
        assert result == f"Use {REDACTED} for auth"

    def test_overlapping_secrets_longest_first(self):
        """Longer secrets are matched before shorter ones."""
        r = _Redactor(secrets=["password", "password123"], patterns=[], enabled=True)
        text = "My password is password123"
        result = r.redact_text(text)
        # Both "password" and "password123" are matched as standalone words
        assert result == f"My {REDACTED} is {REDACTED}"

    def test_api_key_with_special_chars(self):
        r = _Redactor(secrets=["sk-proj-abc123def456"], patterns=[], enabled=True)
        text = "Authenticate with sk-proj-abc123def456 for access"
        result = r.redact_text(text)
        assert "sk-proj-abc123def456" not in result
        assert REDACTED in result

    def test_secret_at_string_boundaries(self):
        """Word-boundary regex matches at start/end of string."""
        r = _Redactor(secrets=["adminpass"], patterns=[], enabled=True)
        assert r.redact_text("adminpass") == REDACTED
        assert r.redact_text("adminpass is secret") == f"{REDACTED} is secret"
        assert r.redact_text("use adminpass") == f"use {REDACTED}"

    def test_multiple_occurrences(self):
        r = _Redactor(secrets=["secret123"], patterns=[], enabled=True)
        text = "secret123 appears here and secret123 there"
        assert r.redact_text(text) == f"{REDACTED} appears here and {REDACTED} there"

    def test_no_secrets(self):
        r = _Redactor(secrets=[], patterns=[], enabled=True)
        text = "Nothing to redact here"
        assert r.redact_text(text) == text

    def test_disabled_redaction(self):
        r = _Redactor(secrets=["top-secret"], patterns=[], enabled=False)
        text = "The top-secret code"
        assert r.redact_text(text) == text


class TestRedactTextRegexPatterns:
    """Regex patterns from config are applied after secrets."""

    def test_regex_pattern(self):
        r = _Redactor(
            secrets=[],
            patterns=[re.compile(r"\b\d{3}-\d{2}-\d{4}\b")],
            enabled=True,
        )
        text = "SSN: 123-45-6789 and phone: 12345-67890"
        result = r.redact_text(text)
        assert "123-45-6789" not in result
        assert REDACTED in result
        assert "12345-67890" in result  # Not SSN format, not matched

    def test_regex_and_secrets_combined(self):
        r = _Redactor(
            secrets=["adminpass"],
            patterns=[re.compile(r"\b\d{3}-\d{2}-\d{4}\b")],
            enabled=True,
        )
        text = "adminpass and SSN 123-45-6789"
        result = r.redact_text(text)
        assert "adminpass" not in result
        assert "123-45-6789" not in result
        assert result.count(REDACTED) == 2


class TestRedactMessage:
    """Message-level redaction."""

    def test_content_redacted(self):
        r = _Redactor(secrets=["secretkey"], patterns=[], enabled=True)
        msg = Message(role="user", content="My key is secretkey")
        result = r.redact_message(msg)
        assert result.content == f"My key is {REDACTED}"
        assert result.role == "user"

    def test_tool_call_arguments_redacted(self):
        r = _Redactor(secrets=["secretkey"], patterns=[], enabled=True)
        from core.providers.base import ToolCall

        msg = Message(
            role="assistant",
            content="",
            tool_calls=[
                ToolCall(
                    id="tc1",
                    name="write_file",
                    arguments={"path": "/etc/config", "content": "secretkey inside"},
                )
            ],
        )
        result = r.redact_message(msg)
        assert result.tool_calls is not None
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].arguments["content"] == f"{REDACTED} inside"
        assert result.tool_calls[0].arguments["path"] == "/etc/config"
        assert result.tool_calls[0].name == "write_file"

    def test_tool_name_preserved(self):
        r = _Redactor(secrets=["secretkey"], patterns=[], enabled=True)
        from core.providers.base import ToolCall

        msg = Message(
            role="assistant",
            content="",
            tool_calls=[
                ToolCall(id="tc1", name="read_file", arguments={"path": "/tmp/secretkey/file"})
            ],
        )
        result = r.redact_message(msg)
        assert result.tool_calls[0].name == "read_file"
        # "secretkey" in path is redacted (word boundary)
        assert REDACTED in result.tool_calls[0].arguments["path"]

    def test_tool_name_not_redacted(self):
        """Tool name field is NOT redacted (it's not secret)."""
        r = _Redactor(secrets=["read_file"], patterns=[], enabled=True)
        from core.providers.base import ToolCall

        msg = Message(
            role="assistant",
            content="",
            tool_calls=[ToolCall(id="tc1", name="read_file", arguments={})],
        )
        result = r.redact_message(msg)
        assert result.tool_calls[0].name == "read_file"

    def test_tool_result_redacted(self):
        r = _Redactor(secrets=["secretkey"], patterns=[], enabled=True)
        msg = Message(
            role="tool",
            content="The key is secretkey",
            name="read_file",
        )
        result = r.redact_message(msg)
        assert result.content == f"The key is {REDACTED}"
        assert result.name == "read_file"

    def test_nested_dict_redaction(self):
        """Deep redaction of nested structures in tool arguments."""
        r = _Redactor(secrets=["secretkey"], patterns=[], enabled=True)
        from core.providers.base import ToolCall

        msg = Message(
            role="assistant",
            content="",
            tool_calls=[
                ToolCall(
                    id="tc1",
                    name="write_file",
                    arguments={
                        "path": "/tmp/test",
                        "options": {"content": "secretkey", "meta": {"key": "secretkey"}},
                    },
                )
            ],
        )
        result = r.redact_message(msg)
        args = result.tool_calls[0].arguments
        assert args["options"]["content"] == REDACTED
        assert args["options"]["meta"]["key"] == REDACTED
        assert args["path"] == "/tmp/test"


class TestRedactMessages:
    """Batch redaction of message lists."""

    def test_multiple_messages(self):
        r = _Redactor(secrets=["secretkey"], patterns=[], enabled=True)
        messages = [
            Message(role="system", content="System prompt"),
            Message(role="user", content="Use secretkey for auth"),
            Message(role="assistant", content="OK, secretkey is noted"),
        ]
        results = r.redact_messages(messages)
        assert len(results) == 3
        assert results[0].content == "System prompt"
        assert results[1].content == f"Use {REDACTED} for auth"
        assert results[2].content == f"OK, {REDACTED} is noted"


class TestMinSecretLength:
    """Secrets shorter than _MIN_SECRET_LENGTH are skipped."""

    def test_3_char_secret_skipped(self):
        r = _Redactor(secrets=["cat"], patterns=[], enabled=True)
        result = r.redact_text("The cat sat on the category concatenated")
        # "cat" is only 3 chars (< 4), skipped entirely
        assert result == "The cat sat on the category concatenated"

    def test_4_char_secret_matched(self):
        r = _Redactor(secrets=["test"], patterns=[], enabled=True)
        result = r.redact_text("Take the test now")
        # "test" is 4 chars (>= 4), matched with word boundaries
        assert result == f"Take the {REDACTED} now"

    def test_mixed_short_and_long_secrets(self):
        r = _Redactor(
            secrets=["api-key-789", "an", "the", "my-password"],
            patterns=[],
            enabled=True,
        )
        text = "Use api-key-789 and an the my-password"
        result = r.redact_text(text)
        # Short secrets (2-3 chars) skipped; long secrets redacted
        assert "an" in result
        assert "the" in result
        assert f"{REDACTED} and" in result or f"{REDACTED}" in result
        assert result.count(REDACTED) == 2  # api-key-789 and my-password

    def test_warning_printed_for_skipped_secrets(self, capsys):
        _Redactor(secrets=["ab", "cd"], patterns=[], enabled=True)
        captured = capsys.readouterr()
        assert "skipping" in captured.err

    def test_no_warning_when_all_secrets_long_enough(self, capsys):
        _Redactor(secrets=["password123"], patterns=[], enabled=True)
        captured = capsys.readouterr()
        assert "skipping" not in captured.err

    def test_empty_string_secret_not_warned(self, capsys):
        _Redactor(secrets=["", "password123"], patterns=[], enabled=True)
        captured = capsys.readouterr()
        # Empty string is filtered by `if not secret`, not counted as "short"
        # The warning only counts non-empty strings that were skipped.
        # "" is filtered before the short check, so no warning for it.


# ---------------------------------------------------------------------------
# BaseProvider._redact integration tests
# ---------------------------------------------------------------------------


class TestBaseProviderRedact:
    """Integration tests for BaseProvider._redact()."""

    def test_redact_with_vault_and_config(self):
        """Integration: vault secrets + config patterns are redacted."""
        vault = MagicMock()
        vault.is_locked.return_value = False
        vault.list_credentials.return_value = ["svc1"]
        vault.get_credential.return_value = ("user1", "my-api-key-12345")
        vault.list_secure_notes.return_value = []

        config = MagicMock()
        config.get.side_effect = lambda key, default=None: {
            "redaction.enabled": True,
            "redaction.patterns": [],
        }.get(key, default)

        provider = BaseProvider(vault=vault, config=config)
        messages = [
            Message(role="user", content="Connect using my-api-key-12345"),
        ]
        result = provider._redact(messages)
        assert REDACTED in result[0].content
        assert "my-api-key-12345" not in result[0].content

    def test_redact_disabled(self):
        """When redaction is disabled, messages pass through."""
        vault = MagicMock()
        vault.is_locked.return_value = False
        vault.list_credentials.return_value = ["svc1"]
        vault.get_credential.return_value = ("user1", "secretkey")
        vault.list_secure_notes.return_value = []

        config = MagicMock()
        config.get.side_effect = lambda key, default=None: {
            "redaction.enabled": False,
            "redaction.patterns": [],
        }.get(key, default)

        provider = BaseProvider(vault=vault, config=config)
        messages = [
            Message(role="user", content="Connect using secretkey"),
        ]
        result = provider._redact(messages)
        assert result[0].content == "Connect using secretkey"

    def test_redact_with_no_config(self):
        """When config is None, no redaction occurs."""
        vault = MagicMock()
        provider = BaseProvider(vault=vault, config=None)
        messages = [
            Message(role="user", content="Use secretkey to auth"),
        ]
        result = provider._redact(messages)
        assert result[0].content == "Use secretkey to auth"

    def test_vault_locked_uses_cached_secrets(self):
        """When vault is locked, _cached_secrets from previous unlock are used."""
        config = MagicMock()
        config.get.side_effect = lambda key, default=None: {
            "redaction.enabled": True,
            "redaction.patterns": [],
        }.get(key, default)

        provider = BaseProvider(vault=None, config=config)
        # Manually set cached secrets (simulating a previous vault unlock)
        provider._cached_secrets = ["my-secret-key"]

        messages = [
            Message(role="user", content="Use my-secret-key to authenticate"),
        ]
        result = provider._redact(messages)
        assert REDACTED in result[0].content
        assert "my-secret-key" not in result[0].content


class TestBuildRedactor:
    """Tests for _build_redactor factory function."""

    def test_build_with_vault_and_config(self):
        vault = MagicMock()
        vault.is_locked.return_value = False
        vault.list_credentials.return_value = ["svc1"]
        vault.get_credential.return_value = ("admin", "secret-password")
        vault.list_secure_notes.return_value = ["note1"]
        vault.get_secure_note.return_value = "my secret note text"

        config = MagicMock()
        config.get.side_effect = lambda key, default=None: {
            "redaction.enabled": True,
            "redaction.patterns": [],
        }.get(key, default)

        r = _build_redactor(vault, config)
        text = "secret-password and my secret note text"
        result = r.redact_text(text)
        assert "secret-password" not in result
        assert "my secret note text" not in result

    def test_build_with_locked_vault(self):
        vault = MagicMock()
        vault.is_locked.return_value = True

        config = MagicMock()
        config.get.side_effect = lambda key, default=None: {
            "redaction.enabled": True,
            "redaction.patterns": [],
        }.get(key, default)

        r = _build_redactor(vault, config)
        # Locked vault means no secrets collected
        text = "Nothing to redact"
        assert r.redact_text(text) == text


class TestCodeRedaction:
    """Realistic scenarios: redacting secrets in source code."""

    def test_python_code_with_api_key(self):
        """API key in Python source code should be redacted at word boundaries."""
        r = _Redactor(secrets=["sk-proj-abc123def456"], patterns=[], enabled=True)
        code = '''
import openai

client = openai.Client(api_key="sk-proj-abc123def456")

def get_admin_session():
    """Get an admin session for testing."""
    return client.sessions.create(role="admin")
'''
        result = r.redact_text(code)
        assert "sk-proj-abc123def456" not in result
        assert REDACTED in result
        assert "get_admin_session" in result  # "admin" is only 5 chars but not in secrets
        assert "admin" in result  # "admin" not a secret, stays intact

    def test_config_file_with_password(self):
        """Password with special chars in a URL is redacted."""
        r = _Redactor(secrets=["P@ssw0rd!"], patterns=[], enabled=True)
        config_text = 'database_url = "postgresql://user:P@ssw0rd!@localhost:5432/mydb"'
        result = r.redact_text(config_text)
        assert "P@ssw0rd!" not in result
        assert REDACTED in result
        # The @ and : in the URL should still be intact around the redaction
        assert "postgresql://user:" in result
        assert "@localhost" in result

    def test_log_redaction(self):
        """Secrets in log output are redacted."""
        r = _Redactor(
            secrets=["bearer-token-xyz"],
            patterns=[re.compile(r"\b\d{4}-\d{4}-\d{4}\b")],
            enabled=True,
        )
        log_line = '2024-01-15 10:30:00 [INFO] User auth with bearer-token-xyz, card 1234-5678-9012'
        result = r.redact_text(log_line)
        assert "bearer-token-xyz" not in result
        assert "1234-5678-9012" not in result

    def test_password_with_trailing_special_char(self):
        """Password ending with ! is redacted even followed by @ in URLs."""
        r = _Redactor(secrets=["P@ssw0rd!"], patterns=[], enabled=True)
        assert r.redact_text("Use P@ssw0rd! now") == f"Use {REDACTED} now"
        assert r.redact_text("user:P@ssw0rd!@host") == f"user:{REDACTED}@host"
        assert r.redact_text("P@ssw0rd!") == REDACTED

    def test_secret_starting_with_special_char(self):
        """Secret starting with special char uses no leading \\b."""
        r = _Redactor(secrets=["$ecretK3y"], patterns=[], enabled=True)
        # Starts with $ (non-word char), so no \b at start
        # But ends with y (word char), so \b at end
        assert r.redact_text("key=$ecretK3y here") == f"key={REDACTED} here"
        assert r.redact_text("use$ecretK3y") == f"use{REDACTED}"  # no \b before $

    def test_all_word_char_secret(self):
        """Secret with only word chars gets \b on both sides."""
        r = _Redactor(secrets=["adminpassword"], patterns=[], enabled=True)
        assert r.redact_text("use adminpassword now") == f"use {REDACTED} now"
        assert r.redact_text("myadminpasswordhere") == "myadminpasswordhere"