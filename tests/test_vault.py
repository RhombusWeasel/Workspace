"""Tests for core.vault."""

import os
import tempfile

import pytest

from core.vault import Vault


@pytest.fixture
def vault_path():
    with tempfile.TemporaryDirectory() as tmp:
        yield os.path.join(tmp, "vault.enc")


@pytest.fixture
def unlocked_vault(vault_path):
    vault = Vault(vault_path)
    vault.initialize(MASTER)
    return vault


MASTER = "s3cret-p@ss!"
ALT = "different-password"


class TestInitialize:
    def test_creates_vault_file(self, vault_path):
        Vault(vault_path).initialize(MASTER)
        assert os.path.isfile(vault_path)

    def test_vault_is_unlocked_after_initialize(self, vault_path):
        vault = Vault(vault_path)
        vault.initialize(MASTER)
        assert not vault.is_locked()

    def test_initialize_overwrites_existing(self, vault_path):
        v1 = Vault(vault_path)
        v1.initialize(MASTER)
        v1.register_credential("a", "u", "p")

        v2 = Vault(vault_path)
        v2.initialize(ALT)
        assert v2.list_credentials() == []


class TestLockUnlock:
    def test_new_vault_is_not_locked(self, vault_path):
        vault = Vault(vault_path)
        assert not vault.is_locked()

    def test_lock_clears_session(self, unlocked_vault):
        unlocked_vault.lock()
        assert unlocked_vault.is_locked()

    def test_unlock_with_correct_password(self, unlocked_vault):
        unlocked_vault.lock()
        result = unlocked_vault.unlock(MASTER)
        assert result is True
        assert not unlocked_vault.is_locked()

    def test_unlock_with_wrong_password(self, unlocked_vault):
        unlocked_vault.lock()
        result = unlocked_vault.unlock("wrong!")
        assert result is False
        assert unlocked_vault.is_locked()

    def test_unlock_on_new_empty_vault_returns_true(self, vault_path):
        vault = Vault(vault_path)
        result = vault.unlock(MASTER)
        assert result is True
        assert not vault.is_locked()


class TestCredentials:
    def test_register_and_retrieve(self, unlocked_vault):
        unlocked_vault.register_credential("github", "alice", "gh-token")
        cred = unlocked_vault.get_credential("github")
        assert cred == ("alice", "gh-token")

    def test_get_missing_returns_none(self, unlocked_vault):
        assert unlocked_vault.get_credential("nope") is None

    def test_list_credentials(self, unlocked_vault):
        unlocked_vault.register_credential("a", "u1", "p1")
        unlocked_vault.register_credential("b", "u2", "p2")
        assert sorted(unlocked_vault.list_credentials()) == ["a", "b"]

    def test_delete_credential(self, unlocked_vault):
        unlocked_vault.register_credential("x", "u", "p")
        unlocked_vault.delete_credential("x")
        assert unlocked_vault.get_credential("x") is None

    def test_delete_missing_does_nothing(self, unlocked_vault):
        unlocked_vault.delete_credential("nope")  # should not raise

    def test_overwrite_existing_credential(self, unlocked_vault):
        unlocked_vault.register_credential("svc", "old-user", "old-pass")
        unlocked_vault.register_credential("svc", "new-user", "new-pass")
        cred = unlocked_vault.get_credential("svc")
        assert cred == ("new-user", "new-pass")


class TestSecureNotes:
    def test_register_and_retrieve(self, unlocked_vault):
        unlocked_vault.register_secure_note("api-key", "sk-abc123")
        assert unlocked_vault.get_secure_note("api-key") == "sk-abc123"

    def test_get_missing_returns_none(self, unlocked_vault):
        assert unlocked_vault.get_secure_note("nope") is None

    def test_list_secure_notes(self, unlocked_vault):
        unlocked_vault.register_secure_note("a", "text a")
        unlocked_vault.register_secure_note("b", "text b")
        assert sorted(unlocked_vault.list_secure_notes()) == ["a", "b"]

    def test_delete_secure_note(self, unlocked_vault):
        unlocked_vault.register_secure_note("note", "content")
        unlocked_vault.delete_secure_note("note")
        assert unlocked_vault.get_secure_note("note") is None

    def test_overwrite_existing_note(self, unlocked_vault):
        unlocked_vault.register_secure_note("key", "old")
        unlocked_vault.register_secure_note("key", "new")
        assert unlocked_vault.get_secure_note("key") == "new"


class TestLockedOperations:
    def test_register_credential_raises_when_locked(self, unlocked_vault):
        unlocked_vault.lock()
        with pytest.raises(RuntimeError, match="locked"):
            unlocked_vault.register_credential("x", "u", "p")

    def test_get_credential_raises_when_locked(self, unlocked_vault):
        unlocked_vault.lock()
        with pytest.raises(RuntimeError, match="locked"):
            unlocked_vault.get_credential("x")

    def test_register_secure_note_raises_when_locked(self, unlocked_vault):
        unlocked_vault.lock()
        with pytest.raises(RuntimeError, match="locked"):
            unlocked_vault.register_secure_note("x", "text")

    def test_get_secure_note_raises_when_locked(self, unlocked_vault):
        unlocked_vault.lock()
        with pytest.raises(RuntimeError, match="locked"):
            unlocked_vault.get_secure_note("x")


class TestPersistence:
    def test_data_survives_reload(self, vault_path):
        v1 = Vault(vault_path)
        v1.initialize(MASTER)
        v1.register_credential("svc", "user", "pass")
        v1.register_secure_note("note", "text")

        v2 = Vault(vault_path)
        v2.unlock(MASTER)
        assert v2.get_credential("svc") == ("user", "pass")
        assert v2.get_secure_note("note") == "text"

    def test_cannot_read_with_wrong_password(self, vault_path):
        v1 = Vault(vault_path)
        v1.initialize(MASTER)
        v1.register_credential("svc", "user", "pass")

        v2 = Vault(vault_path)
        result = v2.unlock("wrong")
        assert result is False
        assert v2.is_locked()

    def test_reinitialize_with_new_password_discards_old_data(self, vault_path):
        v1 = Vault(vault_path)
        v1.initialize("old-pass")
        v1.register_credential("svc", "user", "pass")

        v2 = Vault(vault_path)
        v2.initialize("new-pass")
        assert v2.list_credentials() == []
