"""Tests for message redaction in core.providers.base.

Verifies that:
- Secrets are only redacted when they appear as the complete content
  between matching quote delimiters (', ", `)
- Secrets in prose, variable names, and code identifiers are NOT redacted
- Regex patterns from config still work for custom matching
- Tool call arguments are deep-redacted (quotes preserved)
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
# _Redactor unit tests — quoted-string matching
# ---------------------------------------------------------------------------


class TestQuotedStringMatching:
    """Core redaction: secrets are only redacted inside matching quotes."""

    def test_double_quoted_secret(self):
        r = _Redactor(secrets=["my-secret"], patterns=[], enabled=True)
        assert r.redact_text('password = "my-secret"') == f'password = "{REDACTED}"'

    def test_single_quoted_secret(self):
        r = _Redactor(secrets=["my-secret"], patterns=[], enabled=True)
        assert r.redact_text("password = 'my-secret'") == f"password = '{REDACTED}'"

    def test_backtick_quoted_secret(self):
        r = _Redactor(secrets=["my-secret"], patterns=[], enabled=True)
        assert r.redact_text("password: `my-secret`") == f"password: `{REDACTED}`"

    def test_mismatched_quotes_not_matched(self):
        """Opening and closing quotes must match."""
        r = _Redactor(secrets=["my-secret"], patterns=[], enabled=True)
        # ' opens, " closes → not a match
        assert r.redact_text("x = 'my-secret\"") == "x = 'my-secret\""

    def test_secret_in_prose_not_redacted(self):
        """Secret in unquoted prose should NOT be redacted."""
        r = _Redactor(secrets=["admin"], patterns=[], enabled=True)
        assert r.redact_text("The admin panel is ready") == "The admin panel is ready"

    def test_secret_in_identifier_not_redacted(self):
        """Secret inside a variable name should NOT be redacted."""
        r = _Redactor(secrets=["admin"], patterns=[], enabled=True)
        assert r.redact_text("get_admin_user()") == "get_admin_user()"

    def test_secret_as_substring_in_quotes_not_redacted(self):
        """Secret that is part of a longer quoted string should NOT be redacted."""
        r = _Redactor(secrets=["admin"], patterns=[], enabled=True)
        assert r.redact_text('"the admin user"') == '"the admin user"'

    def test_api_key_in_quotes(self):
        r = _Redactor(secrets=["sk-proj-abc123"], patterns=[], enabled=True)
        assert r.redact_text('api_key = "sk-proj-abc123"') == f'api_key = "{REDACTED}"'

    def test_password_with_special_chars(self):
        r = _Redactor(secrets=["P@ssw0rd!"], patterns=[], enabled=True)
        assert r.redact_text('password = "P@ssw0rd!"') == f'password = "{REDACTED}"'

    def test_password_in_url_not_redacted(self):
        """Password embedded in a URL (not in quotes) is NOT redacted."""
        r = _Redactor(secrets=["P@ssw0rd!"], patterns=[], enabled=True)
        # The password is embedded in the URL, not in matching quotes
        text = "postgresql://user:P@ssw0rd!@localhost/db"
        assert r.redact_text(text) == text

    def test_multiple_secrets(self):
        r = _Redactor(secrets=["key1", "key2"], patterns=[], enabled=True)
        text = 'db_password = "key1", api_key = \'key2\''
        result = r.redact_text(text)
        assert result == f'db_password = "{REDACTED}", api_key = \'{REDACTED}\''

    def test_same_secret_multiple_times(self):
        r = _Redactor(secrets=["my-secret"], patterns=[], enabled=True)
        text = 'a = "my-secret" and b = "my-secret"'
        result = r.redact_text(text)
        assert result == f'a = "{REDACTED}" and b = "{REDACTED}"'

    def test_overlapping_secrets(self):
        """Longer secret should not interfere with shorter one."""
        r = _Redactor(secrets=["password", "password123"], patterns=[], enabled=True)
        text = 'a = "password", b = "password123"'
        result = r.redact_text(text)
        # Both should be independently matched since each is the
        # complete content between its own quotes
        assert result == f'a = "{REDACTED}", b = "{REDACTED}"'

    def test_empty_string_secret_skipped(self):
        r = _Redactor(secrets=["", "my-secret"], patterns=[], enabled=True)
        text = 'x = "my-secret"'
        result = r.redact_text(text)
        assert result == f'x = "{REDACTED}"'

    def test_short_secrets_still_matched(self):
        """Short secrets are matched when in quotes — no minimum length."""
        r = _Redactor(secrets=["cat"], patterns=[], enabled=True)
        # In quotes: matched
        assert r.redact_text('name = "cat"') == f'name = "{REDACTED}"'
        # In prose: NOT matched
        assert r.redact_text("The cat sat on the mat") == "The cat sat on the mat"
        # In an identifier: NOT matched
        assert r.redact_text("category") == "category"

    def test_secret_at_string_boundaries(self):
        """Quoted secret at the start/end of the string."""
        r = _Redactor(secrets=["adminpass"], patterns=[], enabled=True)
        assert r.redact_text('"adminpass"') == f'"{REDACTED}"'
        assert r.redact_text('"adminpass" is set') == f'"{REDACTED}" is set'
        assert r.redact_text('value is "adminpass"') == f'value is "{REDACTED}"'


class TestQuotedStringNotMatched:
    """Verify that secrets are NOT redacted in various non-quoted contexts."""

    def test_variable_name(self):
        r = _Redactor(secrets=["test"], patterns=[], enabled=True)
        # Variable names don't have the secret in matching quotes
        assert r.redact_text("test_admin_access()") == "test_admin_access()"

    def test_prose_text(self):
        r = _Redactor(secrets=["admin"], patterns=[], enabled=True)
        assert r.redact_text("the admin panel") == "the admin panel"

    def test_substring_in_quoted_string(self):
        r = _Redactor(secrets=["admin"], patterns=[], enabled=True)
        # The string "the admin panel" is NOT just "admin" between quotes
        assert r.redact_text('"the admin panel"') == '"the admin panel"'

    def test_json_object(self):
        """Secret in a JSON value is redacted, but key is not."""
        r = _Redactor(secrets=["sk-123"], patterns=[], enabled=True)
        text = '{"api_key": "sk-123"}'
        result = r.redact_text(text)
        assert result == f'{{"api_key": "{REDACTED}"}}'

    def test_python_fstring(self):
        """Secret in an f-string value is redacted."""
        r = _Redactor(secrets=["sk-123"], patterns=[], enabled=True)
        text = 'f"Bearer {sk-123}"'
        # "Bearer {sk-123}" is not exactly "sk-123" between quotes
        assert r.redact_text(text) == text


class TestRegexPatterns:
    """Config regex patterns still work alongside quoted-secret matching."""

    def test_regex_pattern_still_works(self):
        r = _Redactor(
            secrets=[],
            patterns=[re.compile(r"\b\d{3}-\d{2}-\d{4}\b")],
            enabled=True,
        )
        text = "SSN: 123-45-6789 and phone: 12345-67890"
        result = r.redact_text(text)
        assert "123-45-6789" not in result
        assert REDACTED in result
        assert "12345-67890" in result  # Not SSN format

    def test_regex_and_secret_combined(self):
        r = _Redactor(
            secrets=["adminpass"],
            patterns=[re.compile(r"\b\d{3}-\d{2}-\d{4}\b")],
            enabled=True,
        )
        text = 'password = "adminpass" and SSN 123-45-6789'
        result = r.redact_text(text)
        assert "adminpass" not in result
        assert "123-45-6789" not in result


class TestRedactMessage:
    """Message-level redaction preserves quote characters."""

    def test_content_redacted_with_quotes_preserved(self):
        r = _Redactor(secrets=["secretkey"], patterns=[], enabled=True)
        msg = Message(role="user", content='Use "secretkey" for auth')
        result = r.redact_message(msg)
        assert result.content == f'Use "{REDACTED}" for auth'

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
                    arguments={"path": "/etc/config", "content": '"secretkey"'},
                )
            ],
        )
        result = r.redact_message(msg)
        assert result.tool_calls is not None
        assert result.tool_calls[0].arguments["content"] == f'"{REDACTED}"'
        assert result.tool_calls[0].arguments["path"] == "/etc/config"

    def test_tool_name_not_redacted(self):
        """Tool name field is NOT redacted — it's not secret data."""
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
            content='"secretkey" was found in config',
            name="read_file",
        )
        result = r.redact_message(msg)
        assert result.content == f'"{REDACTED}" was found in config'

    def test_nested_dict_redaction(self):
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
                        "options": {"content": '"secretkey"', "meta": {"key": '"secretkey"'}},
                    },
                )
            ],
        )
        result = r.redact_message(msg)
        args = result.tool_calls[0].arguments
        assert args["options"]["content"] == f'"{REDACTED}"'
        assert args["options"]["meta"]["key"] == f'"{REDACTED}"'

    def test_disabled_redaction(self):
        r = _Redactor(secrets=["secretkey"], patterns=[], enabled=False)
        msg = Message(role="user", content='Use "secretkey" for auth')
        result = r.redact_message(msg)
        assert result.content == 'Use "secretkey" for auth'


class TestRedactMessages:
    """Batch redaction of message lists."""

    def test_multiple_messages(self):
        r = _Redactor(secrets=["secretkey"], patterns=[], enabled=True)
        messages = [
            Message(role="system", content="System prompt"),
            Message(role="user", content='Use "secretkey" for auth'),
            Message(role="assistant", content='OK, "secretkey" is noted'),
        ]
        results = r.redact_messages(messages)
        assert len(results) == 3
        assert results[0].content == "System prompt"
        assert results[1].content == f'Use "{REDACTED}" for auth'
        assert results[2].content == f'OK, "{REDACTED}" is noted'


class TestBaseProviderRedact:
    """Integration tests for BaseProvider._redact()."""

    def test_redact_with_vault_and_config(self):
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
            Message(role="user", content='Connect using "my-api-key-12345"'),
        ]
        result = provider._redact(messages)
        assert REDACTED in result[0].content
        assert "my-api-key-12345" not in result[0].content

    def test_redact_disabled(self):
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
            Message(role="user", content='Use "secretkey" for auth'),
        ]
        result = provider._redact(messages)
        assert result[0].content == 'Use "secretkey" for auth'

    def test_redact_with_no_config(self):
        vault = MagicMock()
        provider = BaseProvider(vault=vault, config=None)
        messages = [
            Message(role="user", content='Use "secretkey" for auth'),
        ]
        result = provider._redact(messages)
        assert result[0].content == 'Use "secretkey" for auth'

    def test_vault_locked_uses_cached_secrets(self):
        config = MagicMock()
        config.get.side_effect = lambda key, default=None: {
            "redaction.enabled": True,
            "redaction.patterns": [],
        }.get(key, default)

        provider = BaseProvider(vault=None, config=config)
        provider._cached_secrets = ["my-secret-key"]

        messages = [
            Message(role="user", content='Authenticate with "my-secret-key"'),
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
        text = 'db_password = "secret-password"'
        result = r.redact_text(text)
        assert result == f'db_password = "{REDACTED}"'

    def test_build_with_locked_vault(self):
        vault = MagicMock()
        vault.is_locked.return_value = True

        config = MagicMock()
        config.get.side_effect = lambda key, default=None: {
            "redaction.enabled": True,
            "redaction.patterns": [],
        }.get(key, default)

        r = _build_redactor(vault, config)
        text = '"secret-password"'
        assert r.redact_text(text) == '"secret-password"'


class TestEmptyPatternBug:
    """Regression: empty-string config patterns must be skipped.

    An empty-string regex (re.compile('')) matches at every position,
    inserting REDACTED between every character and catastrophically
    expanding the text.  This was triggered by `"redaction": {"patterns": [""]}``
    in user config.
    """

    def test_empty_pattern_skipped_in_redactor(self):
        """_Redactor must skip empty compiled patterns."""
        empty = re.compile('')
        r = _Redactor(secrets=[], patterns=[empty], enabled=True)
        text = "/mnt/storage/repos/python/Workspace"
        result = r.redact_text(text)
        assert result == text  # No expansion, no REDACTED

    def test_empty_pattern_string_skipped_in_build(self):
        """_build_redactor must skip empty/blank pattern strings."""
        vault = MagicMock()
        vault.is_locked.return_value = True

        config = MagicMock()
        config.get.side_effect = lambda key, default=None: {
            "redaction.enabled": True,
            "redaction.patterns": [""],  # empty string pattern
        }.get(key, default)

        r = _build_redactor(vault, config)
        text = "/mnt/storage/repos/python/Workspace"
        result = r.redact_text(text)
        assert result == text

    def test_blank_pattern_string_skipped(self):
        """Whitespace-only pattern strings must also be skipped."""
        vault = MagicMock()
        vault.is_locked.return_value = True

        config = MagicMock()
        config.get.side_effect = lambda key, default=None: {
            "redaction.enabled": True,
            "redaction.patterns": ["   "],  # whitespace-only
        }.get(key, default)

        r = _build_redactor(vault, config)
        text = "hello world"
        result = r.redact_text(text)
        assert result == text

    def test_empty_pattern_in_base_provider(self):
        """BaseProvider._redact must skip empty/blank pattern strings."""
        config = MagicMock()
        config.get.side_effect = lambda key, default=None: {
            "redaction.enabled": True,
            "redaction.patterns": [""],
        }.get(key, default)

        provider = BaseProvider(vault=None, config=config)
        messages = [
            Message(role="user", content="/mnt/storage/repos/python/Workspace"),
        ]
        result = provider._redact(messages)
        assert result[0].content == "/mnt/storage/repos/python/Workspace"

    def test_valid_pattern_still_works_after_empty_skipped(self):
        """Valid patterns still work when empty patterns are present."""
        vault = MagicMock()
        vault.is_locked.return_value = True

        config = MagicMock()
        config.get.side_effect = lambda key, default=None: {
            "redaction.enabled": True,
            "redaction.patterns": ["", r"\b\d{3}-\d{2}-\d{4}\b", "   "],
        }.get(key, default)

        r = _build_redactor(vault, config)
        text = "SSN: 123-45-6789, path: /home/user"
        result = r.redact_text(text)
        assert "123-45-6789" not in result
        assert REDACTED in result
        assert "/home/user" in result


class TestCodeRedaction:
    """Realistic scenarios: redacting secrets in source code and config."""

    def test_python_code_with_api_key(self):
        """API key in quoted string is redacted; variable names are not."""
        r = _Redactor(secrets=["sk-proj-abc123def456"], patterns=[], enabled=True)
        code = '''import openai

client = openai.Client(api_key="sk-proj-abc123def456")

def get_admin_session():
    """Get an admin session for testing."""
    return client.sessions.create(role="admin")
'''
        result = r.redact_text(code)
        assert "sk-proj-abc123def456" not in result
        assert f'"{REDACTED}"' in result
        assert "get_admin_session" in result
        assert '"admin"' in result  # "admin" is not a secret in this test

    def test_password_in_env_var(self):
        r = _Redactor(secrets=["db_pass_123"], patterns=[], enabled=True)
        text = 'DB_PASSWORD="db_pass_123"'
        result = r.redact_text(text)
        assert result == f'DB_PASSWORD="{REDACTED}"'

    def test_config_file(self):
        r = _Redactor(secrets=["adminpass", "sk-xyz789"], patterns=[], enabled=True)
        text = '''[database]
host = "localhost"
password = "adminpass"
api_key = 'sk-xyz789'
debug = true'''
        result = r.redact_text(text)
        assert f'password = "{REDACTED}"' in result
        assert f"api_key = '{REDACTED}'" in result
        assert '"localhost"' in result  # Not a secret

    def test_log_output(self):
        r = _Redactor(
            secrets=["bearer-token-xyz"],
            patterns=[re.compile(r"\b\d{4}-\d{4}-\d{4}\b")],
            enabled=True,
        )
        log_line = '2024-01-15 [INFO] Auth with "bearer-token-xyz", card 1234-5678-9012'
        result = r.redact_text(log_line)
        assert "bearer-token-xyz" not in result
        assert "1234-5678-9012" not in result
        assert REDACTED in result

    def test_no_false_positives_in_code(self):
        """Verify common code patterns don't trigger false redaction."""
        r = _Redactor(secrets=["test", "admin", "password"], patterns=[], enabled=True)
        code = """def test_admin_access(password_tester):
    admin = get_admin_user()
    password_hash = hash_password(password_tester)
    return admin, password_hash"""
        # None of these should be redacted - secrets are not in matching quotes
        result = r.redact_text(code)
        assert result == code