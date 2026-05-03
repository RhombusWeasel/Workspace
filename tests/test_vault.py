"""Tests for core.vault."""

import os
import tempfile

import pytest

from core.vault import Vault, VaultManager


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


# =========================================================================
# VaultManager tests
# =========================================================================


@pytest.fixture
def tmp_dirs():
    """Two temp directories — one for master, one for project (local)."""
    with tempfile.TemporaryDirectory() as master_tmp:
        with tempfile.TemporaryDirectory() as project_tmp:
            yield master_tmp, project_tmp


@pytest.fixture
def master_path(tmp_dirs):
    master_tmp, _ = tmp_dirs
    return os.path.join(master_tmp, "vault.enc")


@pytest.fixture
def project_dir(tmp_dirs):
    _, project_tmp = tmp_dirs
    return project_tmp


@pytest.fixture
def unlocked_manager(master_path, project_dir):
    """VaultManager with initialized and unlocked master, no local."""
    mgr = VaultManager(master_path, project_dir)
    mgr.initialize_master(MASTER)
    return mgr


class TestVaultManagerInit:
    def test_creates_with_master_path_and_working_dir(self, master_path, project_dir):
        mgr = VaultManager(master_path, project_dir)
        assert mgr.master_path == master_path
        assert mgr.working_dir == project_dir

    def test_no_local_vault_initially(self, master_path, project_dir):
        mgr = VaultManager(master_path, project_dir)
        assert not mgr.has_local_vault()

    def test_is_locked_delegates_to_master(self, master_path, project_dir):
        mgr = VaultManager(master_path, project_dir)
        # No file => not locked (Vault behavior)
        assert not mgr.is_locked()


class TestVaultManagerInitialize:
    def test_initialize_master_creates_file(self, master_path, project_dir):
        mgr = VaultManager(master_path, project_dir)
        mgr.initialize_master(MASTER)
        assert os.path.isfile(master_path)

    def test_initialize_master_unlocks(self, master_path, project_dir):
        mgr = VaultManager(master_path, project_dir)
        mgr.initialize_master(MASTER)
        assert not mgr.is_locked()

    def test_initialize_master_overwrites_existing(self, master_path, project_dir):
        m1 = VaultManager(master_path, project_dir)
        m1.initialize_master(MASTER)
        m1.register_credential("a", "u", "p")

        m2 = VaultManager(master_path, project_dir)
        m2.initialize_master(ALT)
        assert m2.list_credentials() == []


class TestVaultManagerLockUnlock:
    def test_lock_clears_session(self, unlocked_manager):
        unlocked_manager.lock()
        assert unlocked_manager.is_locked()

    def test_unlock_with_correct_password(self, unlocked_manager):
        unlocked_manager.lock()
        result = unlocked_manager.unlock(MASTER)
        assert result is True
        assert not unlocked_manager.is_locked()

    def test_unlock_with_wrong_password(self, unlocked_manager):
        unlocked_manager.lock()
        result = unlocked_manager.unlock("wrong!")
        assert result is False
        assert unlocked_manager.is_locked()


class TestVaultManagerLocalVault:
    def test_has_local_vault_false_when_no_file(self, unlocked_manager):
        assert not unlocked_manager.has_local_vault()

    def test_has_local_vault_true_after_creation(self, unlocked_manager):
        unlocked_manager.create_local_vault()
        assert unlocked_manager.has_local_vault()

    def test_create_local_vault_stores_passkey_in_master(self, unlocked_manager):
        unlocked_manager.create_local_vault()
        import os as _os
        project_abs = _os.path.abspath(unlocked_manager.working_dir)
        cred = unlocked_manager.master.get_credential(f"vault:{project_abs}")
        assert cred is not None
        _, passkey = cred
        assert len(passkey) > 0

    def test_local_vault_auto_unlocks_after_master_unlock(self, master_path, project_dir):
        # Create a manager, init master, create local
        m1 = VaultManager(master_path, project_dir)
        m1.initialize_master(MASTER)
        m1.create_local_vault()
        m1.register_credential("project-key", "proj-user", "proj-secret")

        # New manager — unlock master should auto-unlock local
        m2 = VaultManager(master_path, project_dir)
        m2.unlock(MASTER)
        assert m2.has_local_vault()
        cred = m2.get_credential("project-key")
        assert cred == ("proj-user", "proj-secret")

    def test_local_vault_not_auto_unlocked_for_different_project(
        self, master_path, tmp_dirs
    ):
        _, project_tmp = tmp_dirs
        other_project = os.path.join(project_tmp, "other-project")
        os.makedirs(other_project, exist_ok=True)

        # Create manager for project A, init master, create local
        m1 = VaultManager(master_path, project_tmp)
        m1.initialize_master(MASTER)
        m1.create_local_vault()
        m1.register_credential("project-a-key", "a-user", "a-secret")

        # Manager for project B — unlock master should NOT unlock project A's local
        m2 = VaultManager(master_path, other_project)
        m2.unlock(MASTER)
        assert not m2.has_local_vault()
        cred = m2.get_credential("project-a-key")
        # Should fall through to master — credential was stored in local only
        assert cred is None

    def test_create_local_vault_raises_when_master_locked(
        self, master_path, project_dir
    ):
        mgr = VaultManager(master_path, project_dir)
        # Master not initialized => is_locked() is False (no file)
        # But we can't create a local vault without master being initialized
        # Actually, is_locked returns False for no file... let's lock explicitly
        mgr.initialize_master(MASTER)
        mgr.lock()
        with pytest.raises(RuntimeError, match="locked"):
            mgr.create_local_vault()

    def test_remove_local_vault(self, unlocked_manager):
        unlocked_manager.create_local_vault()
        assert unlocked_manager.has_local_vault()
        unlocked_manager.remove_local_vault()
        assert not unlocked_manager.has_local_vault()

    def test_remove_local_vault_clears_passkey_from_master(self, unlocked_manager):
        unlocked_manager.create_local_vault()
        import os as _os
        project_abs = _os.path.abspath(unlocked_manager.working_dir)
        assert unlocked_manager.master.get_credential(f"vault:{project_abs}") is not None
        unlocked_manager.remove_local_vault()
        assert unlocked_manager.master.get_credential(f"vault:{project_abs}") is None


class TestVaultManagerCredentials:
    def test_register_and_retrieve_from_master(self, unlocked_manager):
        unlocked_manager.register_credential("github", "alice", "gh-token")
        cred = unlocked_manager.get_credential("github")
        assert cred == ("alice", "gh-token")

    def test_get_missing_returns_none(self, unlocked_manager):
        assert unlocked_manager.get_credential("nope") is None

    def test_list_credentials_from_master(self, unlocked_manager):
        unlocked_manager.register_credential("a", "u1", "p1")
        unlocked_manager.register_credential("b", "u2", "p2")
        assert sorted(unlocked_manager.list_credentials()) == ["a", "b"]

    def test_delete_credential_from_master(self, unlocked_manager):
        unlocked_manager.register_credential("x", "u", "p")
        unlocked_manager.delete_credential("x")
        assert unlocked_manager.get_credential("x") is None

    def test_local_credential_overrides_master(self, unlocked_manager):
        unlocked_manager.register_credential("svc", "master-user", "master-pass")
        unlocked_manager.create_local_vault()
        unlocked_manager.register_credential("svc", "local-user", "local-pass")
        cred = unlocked_manager.get_credential("svc")
        assert cred == ("local-user", "local-pass")

    def test_register_stores_to_local_when_available(self, unlocked_manager):
        unlocked_manager.create_local_vault()
        unlocked_manager.register_credential("only-local", "l", "p")
        # Should be in local, not master
        assert unlocked_manager.master.get_credential("only-local") is None

    def test_list_credentials_merges_local_and_master(self, unlocked_manager):
        unlocked_manager.register_credential("master-only", "m", "p")
        unlocked_manager.create_local_vault()
        unlocked_manager.register_credential("local-only", "l", "p")
        assert sorted(unlocked_manager.list_credentials()) == ["local-only", "master-only"]

    def test_delete_from_local_when_present(self, unlocked_manager):
        unlocked_manager.create_local_vault()
        unlocked_manager.register_credential("x", "l", "p")
        unlocked_manager.delete_credential("x")
        assert unlocked_manager.get_credential("x") is None

    def test_delete_local_does_not_touch_master_same_name(self, unlocked_manager):
        unlocked_manager.register_credential("shared", "master-user", "master-pass")
        unlocked_manager.create_local_vault()
        unlocked_manager.register_credential("shared", "local-user", "local-pass")
        unlocked_manager.delete_credential("shared")
        # Local override removed, master copy still exists
        cred = unlocked_manager.get_credential("shared")
        assert cred == ("master-user", "master-pass")


class TestVaultManagerSecureNotes:
    def test_register_and_retrieve_from_master(self, unlocked_manager):
        unlocked_manager.register_secure_note("api-key", "sk-abc123")
        assert unlocked_manager.get_secure_note("api-key") == "sk-abc123"

    def test_get_missing_returns_none(self, unlocked_manager):
        assert unlocked_manager.get_secure_note("nope") is None

    def test_list_secure_notes_from_master(self, unlocked_manager):
        unlocked_manager.register_secure_note("a", "text a")
        unlocked_manager.register_secure_note("b", "text b")
        assert sorted(unlocked_manager.list_secure_notes()) == ["a", "b"]

    def test_delete_secure_note_from_master(self, unlocked_manager):
        unlocked_manager.register_secure_note("note", "content")
        unlocked_manager.delete_secure_note("note")
        assert unlocked_manager.get_secure_note("note") is None

    def test_local_note_overrides_master(self, unlocked_manager):
        unlocked_manager.register_secure_note("token", "master-token")
        unlocked_manager.create_local_vault()
        unlocked_manager.register_secure_note("token", "local-token")
        assert unlocked_manager.get_secure_note("token") == "local-token"

    def test_list_notes_merges_local_and_master(self, unlocked_manager):
        unlocked_manager.register_secure_note("master-note", "m")
        unlocked_manager.create_local_vault()
        unlocked_manager.register_secure_note("local-note", "l")
        assert sorted(unlocked_manager.list_secure_notes()) == [
            "local-note",
            "master-note",
        ]


class TestVaultManagerLockedOperations:
    def test_register_credential_raises_when_locked(self, unlocked_manager):
        unlocked_manager.lock()
        with pytest.raises(RuntimeError, match="locked"):
            unlocked_manager.register_credential("x", "u", "p")

    def test_get_credential_raises_when_locked(self, unlocked_manager):
        unlocked_manager.lock()
        with pytest.raises(RuntimeError, match="locked"):
            unlocked_manager.get_credential("x")

    def test_register_secure_note_raises_when_locked(self, unlocked_manager):
        unlocked_manager.lock()
        with pytest.raises(RuntimeError, match="locked"):
            unlocked_manager.register_secure_note("x", "text")

    def test_get_secure_note_raises_when_locked(self, unlocked_manager):
        unlocked_manager.lock()
        with pytest.raises(RuntimeError, match="locked"):
            unlocked_manager.get_secure_note("x")
