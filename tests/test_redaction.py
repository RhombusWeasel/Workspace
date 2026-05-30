"""Tests for core.redaction — message redaction before sending to LLMs."""

import json
import os
import re
from unittest.mock import MagicMock

import pytest

from core.config import Config
from core.providers.base import ChatResponse, Message, ToolCall
from core.redaction import REDACTED, Redactor, create_redactor
from core.vault import Vault, VaultManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(tmp_path, overrides: dict | None = None) -> Config:
    path = str(tmp_path / "config.json")
    if overrides:
        tmp_path.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(overrides, f)
    return Config([path])


def _make_vault(tmp_path, unlocked: bool = True) -> VaultManager:
    master_path = str(tmp_path / "vault.enc")
    mgr = VaultManager(master_path, str(tmp_path))
    mgr.initialize_master("pw")
    if not unlocked:
        mgr.lock()
    return mgr


# ---------------------------------------------------------------------------
# Redactor — text redaction
# ---------------------------------------------------------------------------


class TestRedactText:
    """Tests for Redactor.redact_text()."""

    def test_no_secrets_no_patterns(self):
        """Text passes through unchanged when there are no secrets or patterns."""
        r = Redactor(secrets=[], patterns=[])
        assert r.redact_text("hello world") == "hello world"

    def test_single_secret_replaced(self):
        """A single vault secret is replaced with REDACTED."""
        r = Redactor(secrets=["hunter2"], patterns=[])
        assert r.redact_text("my password is hunter2") == f"my password is {REDACTED}"

    def test_multiple_secrets_replaced(self):
        """Multiple vault secrets are all replaced."""
        r = Redactor(secrets=["secret1", "secret2"], patterns=[])
        text = "login with secret1 and secret2"
        assert r.redact_text(text) == f"login with {REDACTED} and {REDACTED}"

    def test_overlapping_secrets_longest_first(self):
        """Longer secrets are replaced before shorter ones to avoid partial matches."""
        r = Redactor(secrets=["password", "password123"], patterns=[])
        # "password123" is longer and should be replaced first
        text = "my pass is password123"
        assert r.redact_text(text) == f"my pass is {REDACTED}"

    def test_overlapping_secrets_shorter_substring(self):
        """When only the shorter secret is present, it is still replaced."""
        r = Redactor(secrets=["password", "password123"], patterns=[])
        text = "my pass is password"
        assert r.redact_text(text) == f"my pass is {REDACTED}"

    def test_secret_multiple_occurrences(self):
        """All occurrences of a secret are replaced."""
        r = Redactor(secrets=["abc"], patterns=[])
        text = "abc at start, abc in middle, and abc at end"
        expected = f"{REDACTED} at start, {REDACTED} in middle, and {REDACTED} at end"
        assert r.redact_text(text) == expected

    def test_empty_secret_ignored(self):
        """Empty strings in the secrets list are ignored (no infinite replace)."""
        r = Redactor(secrets=["", "real_secret"], patterns=[])
        assert r.redact_text("use real_secret") == f"use {REDACTED}"

    def test_single_pattern_replaced(self):
        """A single regex pattern replaces matches with REDACTED."""
        pattern = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")  # SSN-like
        r = Redactor(secrets=[], patterns=[pattern])
        text = "SSN: 123-45-6789"
        assert r.redact_text(text) == f"SSN: {REDACTED}"

    def test_multiple_patterns_applied(self):
        """Multiple patterns are all applied in order."""
        p1 = re.compile(r"\b[A-F0-9]{8}-[A-F0-9]{4}\b")  # UUID prefix
        p2 = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")  # SSN-like
        r = Redactor(secrets=[], patterns=[p1, p2])
        text = "uuid A1B2C3D4-E5F6 and ssn 123-45-6789"
        assert r.redact_text(text) == f"uuid {REDACTED} and ssn {REDACTED}"

    def test_secrets_and_patterns_both_applied(self):
        """Vault secrets are replaced first, then regex patterns."""
        pattern = re.compile(r"\bAPI_KEY_[A-Z]+\b")
        r = Redactor(secrets=["hunter2"], patterns=[pattern])
        text = "password=hunter2 and API_KEY_PROD"
        expected = f"password={REDACTED} and {REDACTED}"
        assert r.redact_text(text) == expected

    def test_disabled_redactor_passes_through(self):
        """When enabled=False, text passes through unchanged."""
        r = Redactor(secrets=["secret"], patterns=[re.compile(r"\d+")], enabled=False)
        text = "secret 123"
        assert r.redact_text(text) == "secret 123"

    def test_no_match_leaves_text_unchanged(self):
        """Text with no matching secrets or patterns is unchanged."""
        r = Redactor(secrets=["topsecret"], patterns=[re.compile(r"\bXRAY\b")])
        assert r.redact_text("nothing to see here") == "nothing to see here"


# ---------------------------------------------------------------------------
# Redactor — message redaction
# ---------------------------------------------------------------------------


class TestRedactMessage:
    """Tests for Redactor.redact_message()."""

    def test_content_redacted(self):
        """Message content is redacted."""
        r = Redactor(secrets=["password123"], patterns=[])
        msg = Message(role="user", content="my password is password123")
        result = r.redact_message(msg)
        assert result.content == f"my password is {REDACTED}"

    def test_role_preserved(self):
        """Message role is not redacted."""
        r = Redactor(secrets=["system"], patterns=[])
        msg = Message(role="system", content="hello")
        result = r.redact_message(msg)
        assert result.role == "system"

    def test_name_preserved(self):
        """Message name field is not redacted (it's a tool name)."""
        r = Redactor(secrets=["read_file"], patterns=[])
        msg = Message(role="tool", content="result", name="read_file")
        result = r.redact_message(msg)
        assert result.name == "read_file"

    def test_tool_call_arguments_redacted(self):
        """String values inside tool call arguments are redacted."""
        r = Redactor(secrets=["secret_path"], patterns=[])
        msg = Message(
            role="assistant",
            content="",
            tool_calls=[
                ToolCall(
                    id="call_1",
                    name="read_file",
                    arguments={"path": "/secret_path/data", "mode": "r"},
                )
            ],
        )
        result = r.redact_message(msg)
        assert result.tool_calls is not None
        assert len(result.tool_calls) == 1
        tc = result.tool_calls[0]
        assert tc.id == "call_1"
        assert tc.name == "read_file"
        assert tc.arguments["path"] == f"/{REDACTED}/data"
        assert tc.arguments["mode"] == "r"

    def test_tool_call_id_and_name_preserved(self):
        """Tool call id and name are not redacted."""
        r = Redactor(secrets=["call_1"], patterns=[])
        msg = Message(
            role="assistant",
            content="",
            tool_calls=[
                ToolCall(id="call_1", name="read_file", arguments={})
            ],
        )
        result = r.redact_message(msg)
        assert result.tool_calls[0].id == "call_1"
        assert result.tool_calls[0].name == "read_file"

    def test_no_tool_calls(self):
        """Message without tool calls is handled correctly."""
        r = Redactor(secrets=["secret"], patterns=[])
        msg = Message(role="user", content="the secret is out")
        result = r.redact_message(msg)
        assert result.tool_calls is None
        assert result.content == f"the {REDACTED} is out"

    def test_disabled_returns_same_message(self):
        """Disabled redactor returns the message unchanged."""
        r = Redactor(secrets=[], patterns=[], enabled=False)
        msg = Message(role="user", content="password123")
        result = r.redact_message(msg)
        assert result.content == "password123"

    def test_nested_arguments_redacted(self):
        """Deeply nested values in tool arguments are redacted."""
        r = Redactor(secrets=["nested_secret"], patterns=[])
        msg = Message(
            role="assistant",
            content="",
            tool_calls=[
                ToolCall(
                    id="tc1",
                    name="run_command",
                    arguments={
                        "command": "echo nested_secret",
                        "env": {"SECRET_KEY": "nested_secret"},
                        "flags": ["--secret=nested_secret"],
                    },
                )
            ],
        )
        result = r.redact_message(msg)
        args = result.tool_calls[0].arguments
        assert REDACTED in args["command"]
        assert args["env"]["SECRET_KEY"] == REDACTED
        assert REDACTED in args["flags"][0]


class TestRedactMessages:
    """Tests for Redactor.redact_messages()."""

    def test_all_messages_redacted(self):
        """Every message in the list is redacted."""
        r = Redactor(secrets=["pw1"], patterns=[])
        messages = [
            Message(role="system", content="system pw1"),
            Message(role="user", content="user pw1"),
            Message(role="assistant", content="assistant pw1"),
        ]
        result = r.redact_messages(messages)
        assert len(result) == 3
        for msg in result:
            assert REDACTED in msg.content

    def test_empty_list(self):
        """Empty message list returns empty list."""
        r = Redactor(secrets=["secret"], patterns=[])
        assert r.redact_messages([]) == []


# ---------------------------------------------------------------------------
# Redactor — value redaction (tool call arguments)
# ---------------------------------------------------------------------------


class TestRedactValue:
    """Tests for Redactor._redact_value()."""

    def test_string_value(self):
        """String values are redacted."""
        r = Redactor(secrets=["secret"], patterns=[])
        assert r._redact_value("hide secret") == f"hide {REDACTED}"

    def test_int_value(self):
        """Integer values pass through unchanged."""
        r = Redactor(secrets=["42"], patterns=[])
        assert r._redact_value(42) == 42

    def test_float_value(self):
        """Float values pass through unchanged."""
        r = Redactor(secrets=[], patterns=[])
        assert r._redact_value(3.14) == 3.14

    def test_bool_value(self):
        """Boolean values pass through unchanged."""
        r = Redactor(secrets=["true"], patterns=[])
        assert r._redact_value(True) is True

    def test_none_value(self):
        """None values pass through unchanged."""
        r = Redactor(secrets=[], patterns=[])
        assert r._redact_value(None) is None

    def test_dict_values_redacted(self):
        """Dict values are redacted, keys are not."""
        r = Redactor(secrets=["val1"], patterns=[])
        result = r._redact_value({"key1": "val1", "key2": "val2"})
        assert result == {"key1": REDACTED, "key2": "val2"}

    def test_dict_keys_not_redacted(self):
        """Dict keys are left alone even if they contain secrets."""
        r = Redactor(secrets=["password"], patterns=[])
        result = r._redact_value({"password": "value"})
        assert "password" in result
        assert result["password"] == "value"

    def test_nested_dict(self):
        """Deeply nested dicts have all string values redacted."""
        r = Redactor(secrets=["deep"], patterns=[])
        result = r._redact_value({"outer": {"inner": "deep", "safe": "ok"}})
        assert result["outer"]["inner"] == REDACTED
        assert result["outer"]["safe"] == "ok"

    def test_list_of_strings(self):
        """List items are redacted."""
        r = Redactor(secrets=["item"], patterns=[])
        result = r._redact_value(["item1", "safe", "item2"])
        assert REDACTED in result[0]
        assert result[1] == "safe"

    def test_mixed_nested_structure(self):
        """Mixed dicts and lists in nested structures are handled."""
        r = Redactor(secrets=["s3cr3t"], patterns=[re.compile(r"\bKEY\d+\b")])
        value = {
            "path": "/home/s3cr3t/data",
            "env": {"API_KEY": "KEY42"},
            "tags": ["s3cr3t", "public"],
            "count": 5,
        }
        result = r._redact_value(value)
        assert REDACTED in result["path"]
        assert result["env"]["API_KEY"] == REDACTED
        assert result["tags"][0] == REDACTED
        assert result["tags"][1] == "public"
        assert result["count"] == 5


# ---------------------------------------------------------------------------
# create_redactor — factory function
# ---------------------------------------------------------------------------


class TestCreateRedactor:
    """Tests for create_redactor()."""

    def _make_vault_manager(self, tmp_path):
        """Create a VaultManager with an initialized master vault."""
        master_path = str(tmp_path / "vault.enc")
        vm = VaultManager(master_path, str(tmp_path))
        vm.initialize_master("test_pass")
        return vm

    def _make_config(self, tmp_path, enabled=True, patterns=None):
        """Create a Config with redaction settings."""
        from core.config import Config
        import os

        config_path = str(tmp_path / "config.json")
        # Ensure parent dir exists
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        with open(config_path, "w") as f:
            import json
            json.dump({}, f)

        cfg = Config([config_path])
        cfg.set("redaction.enabled", enabled)
        cfg.set("redaction.patterns", patterns or [])
        cfg.apply_defaults()
        return cfg

    def test_unlocked_vault_secrets_gathered(self, tmp_path):
        """Secrets from an unlocked vault are included in the Redactor."""
        vm = self._make_vault_manager(tmp_path)
        vm.register_credential("db", "admin", "super_secret_pw")
        vm.register_secure_note("note1", "note_content_here")

        cfg = self._make_config(tmp_path)
        r = create_redactor(vm, cfg)

        assert r._enabled is True
        assert "super_secret_pw" in r._secrets
        assert "note_content_here" in r._secrets

    def test_locked_vault_secrets_skipped(self, tmp_path):
        """When vault is locked, no vault secrets are gathered."""
        master_path = str(tmp_path / "vault.enc")
        vm = VaultManager(master_path, str(tmp_path))
        vm.initialize_master("test_pass")
        vm.register_credential("db", "admin", "super_secret_pw")
        vm.lock()

        cfg = self._make_config(tmp_path)

        # Vault is locked — should skip secrets gracefully
        r = create_redactor(vm, cfg)

        assert r._enabled is True
        assert len(r._secrets) == 0

    def test_config_patterns_compiled(self, tmp_path):
        """Regex patterns from config are compiled and included."""
        vm = self._make_vault_manager(tmp_path)
        cfg = self._make_config(
            tmp_path,
            patterns=[r"\b\d{3}-\d{2}-\d{4}\b", r"API_[A-Z_]+"],
        )

        r = create_redactor(vm, cfg)

        assert len(r._patterns) == 2
        # Verify patterns work
        assert r.redact_text("SSN 123-45-6789") == f"SSN {REDACTED}"
        # API_[A-Z_]+ matches the whole "API_PROD_KEY"
        assert r.redact_text("key API_PROD_KEY") == f"key {REDACTED}"

    def test_invalid_pattern_skipped(self, tmp_path, capsys):
        """Invalid regex patterns are skipped with a warning."""
        vm = self._make_vault_manager(tmp_path)
        cfg = self._make_config(
            tmp_path,
            patterns=[r"\bvalid\b", "[invalid", r"\d+"],
        )

        r = create_redactor(vm, cfg)

        # Only valid patterns should be compiled
        assert len(r._patterns) == 2  # valid + digits, skipping [invalid
        # Warning should be printed to stderr
        captured = capsys.readouterr()
        assert "Warning" in captured.err or "invalid" in captured.err

    def test_redaction_disabled_in_config(self, tmp_path):
        """When redaction.enabled=False, the Redactor is disabled."""
        vm = self._make_vault_manager(tmp_path)
        vm.register_credential("test", "user", "password123")

        cfg = self._make_config(tmp_path, enabled=False)

        r = create_redactor(vm, cfg)

        assert r._enabled is False
        # Even though secrets are gathered, redaction is disabled
        assert r.redact_text("password123") == "password123"

    def test_vault_password_excluded_from_vault_keys(self, tmp_path):
        """Internal vault: passkeys are excluded from secrets."""
        vm = self._make_vault_manager(tmp_path)
        vm.register_credential("myapp", "admin", "app_password")

        cfg = self._make_config(tmp_path)
        r = create_redactor(vm, cfg)

        assert "app_password" in r._secrets
        # list_credentials doesn't return vault: keys, so they shouldn't appear
        assert not any(s.startswith("vault:") for s in r._secrets)

    def test_username_not_redacted(self, tmp_path):
        """Only passwords are gathered as secrets, not usernames."""
        vm = self._make_vault_manager(tmp_path)
        vm.register_credential("svc", "my_username", "my_password")

        cfg = self._make_config(tmp_path)
        r = create_redactor(vm, cfg)

        assert "my_password" in r._secrets
        assert "my_username" not in r._secrets


# ---------------------------------------------------------------------------
# Agent integration — build_messages redaction
# ---------------------------------------------------------------------------


class TestProviderRedaction:
    """Tests for BaseProvider's automatic redaction in chat()/stream_chat()."""

    @pytest.mark.asyncio
    async def test_provider_chat_redacts_vault_secrets(self, tmp_path):
        """BaseProvider.chat() redacts vault secrets from messages."""
        from core.providers.ollama import OllamaProvider

        config = _make_config(tmp_path)
        vault = _make_vault(tmp_path)
        vault.register_credential("db", "admin", "super_secret")

        captured_messages = []

        class _CapturingProvider(OllamaProvider):
            async def _do_chat(self, messages, model, tools=None):
                captured_messages.extend(messages)
                return ChatResponse(content="ok")

        provider = _CapturingProvider(config=config, vault=vault)

        from core.providers.base import Message
        await provider.chat(
            messages=[Message(role="user", content="The password is super_secret")],
            model="test",
        )

        assert "super_secret" not in captured_messages[0].content
        assert REDACTED in captured_messages[0].content

    @pytest.mark.asyncio
    async def test_provider_chat_redacts_patterns(self, tmp_path):
        """BaseProvider.chat() redacts config regex patterns."""
        from core.providers.ollama import OllamaProvider

        config = _make_config(tmp_path, {"redaction": {"patterns": [r"\b\d{3}-\d{2}-\d{4}\b"]}})
        vault = _make_vault(tmp_path, unlocked=False)

        captured_messages = []

        class _CapturingProvider(OllamaProvider):
            async def _do_chat(self, messages, model, tools=None):
                captured_messages.extend(messages)
                return ChatResponse(content="ok")

        provider = _CapturingProvider(config=config, vault=vault)

        from core.providers.base import Message
        await provider.chat(
            messages=[Message(role="user", content="My SSN is 123-45-6789")],
            model="test",
        )

        assert "123-45-6789" not in captured_messages[0].content
        assert REDACTED in captured_messages[0].content

    @pytest.mark.asyncio
    async def test_provider_no_config_no_redaction(self, tmp_path):
        """Provider with no config does not redact."""
        from core.providers.ollama import OllamaProvider

        captured_messages = []

        class _CapturingProvider(OllamaProvider):
            async def _do_chat(self, messages, model, tools=None):
                captured_messages.extend(messages)
                return ChatResponse(content="ok")

        config = _make_config(tmp_path)
        provider = _CapturingProvider(config=config, vault=None)
        provider._config = None  # No config → no redaction

        from core.providers.base import Message
        await provider.chat(
            messages=[Message(role="user", content="secret_password_here")],
            model="test",
        )

        assert captured_messages[0].content == "secret_password_here"

    @pytest.mark.asyncio
    async def test_provider_chat_redacts_tool_call_args(self, tmp_path):
        """Tool call arguments are redacted by the provider."""
        from core.providers.ollama import OllamaProvider

        config = _make_config(tmp_path)
        vault = _make_vault(tmp_path)
        vault.register_credential("svc", "user", "vault_secret")

        captured_messages = []

        class _CapturingProvider(OllamaProvider):
            async def _do_chat(self, messages, model, tools=None):
                captured_messages.extend(messages)
                return ChatResponse(content="ok")

        provider = _CapturingProvider(config=config, vault=vault)

        from core.providers.base import Message, ToolCall
        await provider.chat(
            messages=[
                Message(
                    role="assistant",
                    content="",
                    tool_calls=[
                        ToolCall(
                            id="call_1",
                            name="run_command",
                            arguments={"command": "echo vault_secret"},
                        )
                    ],
                ),
                Message(role="tool", content="vault_secret output", name="run_command"),
            ],
            model="test",
        )

        # Content and tool call arguments should be redacted
        for msg in captured_messages:
            assert "vault_secret" not in msg.content or REDACTED in msg.content
            if msg.tool_calls:
                for tc in msg.tool_calls:
                    for val in tc.arguments.values():
                        if isinstance(val, str):
                            assert "vault_secret" not in val

    def test_agent_build_messages_returns_raw(self):
        """Agent.build_messages returns un-redacted messages (provider handles it)."""
        from core.agent import Agent

        mock_provider = MagicMock()

        agent = Agent(
            provider=mock_provider,
            template="You are an assistant.",
            model="test-model",
        )

        messages = agent.build_messages(
            history=[],
            user_text="my super_secret password",
        )

        # Messages are raw — provider will redact on chat()
        assert messages[1].content == "my super_secret password"