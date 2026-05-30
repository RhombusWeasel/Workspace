"""Tests for BaseProvider's secret caching — secrets survive vault lock.

These tests verify that secrets read from an unlocked vault are cached
on the provider instance so that redaction continues to work even after
the vault is locked.
"""

from unittest.mock import MagicMock

import pytest

from core.providers.base import ChatResponse, Message, REDACTED


def _make_provider_with_vault(vault, config):
    """Create a minimal BaseProvider subclass for testing redaction."""
    from core.providers.base import BaseProvider

    class _TestProvider(BaseProvider):
        async def _do_chat(self, messages, model, tools=None):
            return ChatResponse(content="ok")

        async def _do_stream_chat(self, messages, model, tools=None):
            yield  # pragma: no cover

    return _TestProvider(vault=vault, config=config)


class TestProviderSecretCaching:
    """Tests for the BaseProvider's _cached_secrets mechanism."""

    @pytest.mark.asyncio
    async def test_cached_secrets_survive_vault_lock(self):
        """Secrets cached during unlock persist even after vault is locked."""
        mock_vault = MagicMock()
        mock_config = MagicMock()

        # Start with vault unlocked
        mock_vault.is_locked.return_value = False
        mock_vault.list_credentials.return_value = ["db"]
        mock_vault.get_credential.return_value = ("admin", "cached_pw")
        mock_vault.list_secure_notes.return_value = []

        mock_config.get.side_effect = lambda key, default=None: {
            "redaction.enabled": True,
            "redaction.patterns": [],
        }.get(key, default)

        provider = _make_provider_with_vault(mock_vault, mock_config)

        # First call — vault unlocked, secrets should be cached
        redacted = provider._redact(
            [Message(role="user", content="Password is cached_pw")]
        )
        assert "cached_pw" not in redacted[0].content
        assert REDACTED in redacted[0].content

        # Now lock the vault
        mock_vault.is_locked.return_value = True
        mock_vault.list_credentials.side_effect = RuntimeError("Locked")
        mock_vault.list_secure_notes.side_effect = RuntimeError("Locked")

        # Second call — vault locked, but cached secrets should still work
        redacted = provider._redact(
            [Message(role="user", content="Password is cached_pw")]
        )
        assert "cached_pw" not in redacted[0].content, (
            "Secret should still be redacted even when vault is locked "
            "because it was cached from the previous unlock"
        )
        assert REDACTED in redacted[0].content

    @pytest.mark.asyncio
    async def test_vault_unlock_refreshes_cache(self):
        """When vault is unlocked again, cache is refreshed with new secrets."""
        mock_vault = MagicMock()
        mock_config = MagicMock()

        # Start with one credential
        mock_vault.is_locked.return_value = False
        mock_vault.list_credentials.return_value = ["db"]
        mock_vault.get_credential.return_value = ("admin", "original_pw")
        mock_vault.list_secure_notes.return_value = []

        mock_config.get.side_effect = lambda key, default=None: {
            "redaction.enabled": True,
            "redaction.patterns": [],
        }.get(key, default)

        provider = _make_provider_with_vault(mock_vault, mock_config)

        # First call — caches "original_pw"
        redacted = provider._redact(
            [Message(role="user", content="Password is original_pw")]
        )
        assert "original_pw" not in redacted[0].content

        # Simulate vault being updated: new credential added
        mock_vault.list_credentials.return_value = ["db", "api"]
        mock_vault.get_credential.side_effect = lambda name: {
            "db": ("admin", "original_pw"),
            "api": ("user", "new_api_key"),
        }.get(name)

        # Second call — should pick up the new secret
        redacted = provider._redact(
            [Message(role="user", content="Using original_pw and new_api_key")]
        )
        assert "original_pw" not in redacted[0].content
        assert "new_api_key" not in redacted[0].content
        assert redacted[0].content.count(REDACTED) >= 2

    def test_empty_vault_caches_empty_list(self):
        """An unlocked vault with no entries caches an empty list."""
        mock_vault = MagicMock()
        mock_config = MagicMock()

        mock_vault.is_locked.return_value = False
        mock_vault.list_credentials.return_value = []
        mock_vault.list_secure_notes.return_value = []

        mock_config.get.side_effect = lambda key, default=None: {
            "redaction.enabled": True,
            "redaction.patterns": [],
        }.get(key, default)

        provider = _make_provider_with_vault(mock_vault, mock_config)

        # First call — empty vault caches empty list
        assert provider._cached_secrets == []
        redacted = provider._redact(
            [Message(role="user", content="No secrets here")]
        )
        assert provider._cached_secrets == []
        assert redacted[0].content == "No secrets here"

    def test_vault_locked_never_unlocked_no_secrets(self):
        """If vault was never unlocked, _cached_secrets stays empty."""
        mock_vault = MagicMock()
        mock_config = MagicMock()

        # Vault is locked and has never been unlocked
        mock_vault.is_locked.return_value = True

        mock_config.get.side_effect = lambda key, default=None: {
            "redaction.enabled": True,
            "redaction.patterns": [],
        }.get(key, default)

        provider = _make_provider_with_vault(mock_vault, mock_config)

        # No secrets cached because vault was never unlocked
        assert provider._cached_secrets == []
        redacted = provider._redact(
            [Message(role="user", content="My password is anything_goes")]
        )
        # No redaction happens — no secrets cached, vault never unlocked
        assert "anything_goes" in redacted[0].content

    def test_unlocked_then_locked_then_unlocked_again(self):
        """Secrets are refreshed each time vault is unlocked."""
        mock_vault = MagicMock()
        mock_config = MagicMock()

        # Phase 1: unlocked with one secret
        mock_vault.is_locked.return_value = False
        mock_vault.list_credentials.return_value = ["svc1"]
        mock_vault.get_credential.return_value = ("user", "secret1")
        mock_vault.list_secure_notes.return_value = []

        mock_config.get.side_effect = lambda key, default=None: {
            "redaction.enabled": True,
            "redaction.patterns": [],
        }.get(key, default)

        provider = _make_provider_with_vault(mock_vault, mock_config)

        # Phase 1: caches "secret1"
        redacted = provider._redact(
            [Message(role="user", content="secret1")]
        )
        assert "secret1" not in redacted[0].content

        # Phase 2: vault locked, but cache still has "secret1"
        mock_vault.is_locked.return_value = True
        redacted = provider._redact(
            [Message(role="user", content="secret1 still redacted")]
        )
        assert "secret1" not in redacted[0].content

        # Phase 3: vault unlocked with different secrets
        mock_vault.is_locked.return_value = False
        mock_vault.list_credentials.return_value = ["svc1", "svc2"]
        mock_vault.get_credential.side_effect = lambda name: {
            "svc1": ("user", "secret1"),
            "svc2": ("user", "secret2"),
        }.get(name)

        redacted = provider._redact(
            [Message(role="user", content="secret1 and secret2")]
        )
        assert "secret1" not in redacted[0].content
        assert "secret2" not in redacted[0].content