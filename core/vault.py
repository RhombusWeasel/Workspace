"""Encrypted password vault using Fernet + PBKDF2HMAC.

Stores credentials (name → username + password) and secure notes (name → text)
in a versioned, encrypted JSON file.  The vault must be unlocked with a master
password before any read/write operations are allowed.

Key derivation:  PBKDF2HMAC with SHA-256, 480 000 iterations, 32-byte salt.
Encryption:      Fernet (AES-128-CBC + HMAC-SHA256).

Security properties
-------------------
* Master password never stored on disk.
* Salt is random per vault file.
* Unlock validates by attempting to decrypt all stored entries — a single
  wrong byte will cause Fernet to reject the entire file.
* Locked operations raise ``RuntimeError`` immediately (no silent failure).
"""

import json
import os
import secrets
from base64 import urlsafe_b64encode
from typing import Any

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VAULT_VERSION: int = 1
"""Current vault file format version."""

_PBKDF2_ITERATIONS: int = 480_000
_SALT_LENGTH: int = 32
_NAME_MAX_LENGTH: int = 128
_PASSWORD_MIN_LENGTH: int = 4
_PASSWORD_MAX_LENGTH: int = 256

# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_name(name: str) -> str:
	"""Validate and normalise a vault entry name.

	Returns the stripped name on success; raises ``ValueError`` on failure.

	Rules:
	* Must not be empty or whitespace-only.
	* Must not contain ``-`` (breaks UI action routing).
	* Must not start with ``vault:`` (reserved for internal passkeys).
	* Must not contain control characters (U+0000–U+001F, U+007F).
	* Must be 128 characters or fewer (after stripping).
	"""
	name = name.strip()
	if not name:
		raise ValueError("Name must not be empty")
	if "-" in name:
		raise ValueError("Name must not contain '-' (use underscores instead)")
	if name.startswith("vault:"):
		raise ValueError("Name must not start with 'vault:'")
	if any(ord(c) <= 0x1F or ord(c) == 0x7F for c in name):
		raise ValueError("Name must not contain control characters")
	if len(name) > _NAME_MAX_LENGTH:
		raise ValueError(f"Name must be {_NAME_MAX_LENGTH} characters or fewer")
	return name


def validate_master_password(password: str) -> str:
	"""Validate a master password.

	Returns the stripped password on success; raises ``ValueError`` on failure.

	Rules:
	* Must be at least 4 characters.
	* Must not be whitespace-only.
	* Must be 256 characters or fewer (after stripping).
	"""
	password = password.strip()
	if not password:
		raise ValueError("Master password must not be empty")
	if len(password) < _PASSWORD_MIN_LENGTH:
		raise ValueError(f"Master password must be at least {_PASSWORD_MIN_LENGTH} characters")
	if len(password) > _PASSWORD_MAX_LENGTH:
		raise ValueError(f"Master password must be {_PASSWORD_MAX_LENGTH} characters or fewer")
	return password


# ---------------------------------------------------------------------------
# Crypto helpers
# ---------------------------------------------------------------------------


def _derive_key(password: str, salt: bytes) -> bytes:
    """Derive a 32-byte Fernet key from *password* and *salt*."""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=_PBKDF2_ITERATIONS,
    )
    return urlsafe_b64encode(kdf.derive(password.encode("utf-8")))


def _fernet(key: bytes) -> Fernet:
    return Fernet(key)


# ---------------------------------------------------------------------------
# Vault
# ---------------------------------------------------------------------------


class Vault:
    """Encrypted credential store backed by a single JSON file."""

    def __init__(self, filepath: str) -> None:
        self._filepath: str = filepath
        self._key: bytes | None = None
        # When unlocked, self._entries holds the decrypted data:
        #   {"credentials": {name: {"username": ..., "password": ...}},
        #    "notes":       {name: "text"}}
        self._entries: dict[str, dict[str, Any]] = {
            "credentials": {},
            "notes": {},
        }

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def is_locked(self) -> bool:
        """``True`` when no valid key is cached in memory.

        A brand-new vault with no backing file is considered *unlocked*
        (there is nothing to protect, and :meth:`unlock` accepts any password).
        """
        if not os.path.isfile(self._filepath):
            return False
        return self._key is None

    def initialize(self, master_password: str) -> None:
        """Create a brand-new vault file.

        Any existing file at *filepath* is overwritten.  The vault is
        unlocked afterwards using *master_password*.
        """
        master_password = validate_master_password(master_password)
        salt = secrets.token_bytes(_SALT_LENGTH)
        key = _derive_key(master_password, salt)
        self._key = key
        self._entries = {"credentials": {}, "notes": {}}
        self._write(salt)

    def unlock(self, master_password: str) -> bool:
        """Attempt to unlock the vault with *master_password*.

        Returns ``True`` if the password is correct and the vault is now
        unlocked; ``False`` otherwise (vault remains locked).
        """
        if not os.path.isfile(self._filepath):
            # No file yet — accept any password, auto-gen key for first write.
            self._key = Fernet.generate_key()
            return True

        try:
            with open(self._filepath, "rb") as fh:
                blob = json.loads(fh.read().decode("utf-8"))
        except (json.JSONDecodeError, OSError):
            return False

        try:
            salt = blob["salt"]
            ciphertext = blob["data"]
        except (KeyError, TypeError):
            return False

        key = _derive_key(master_password, salt.encode("latin-1"))
        f = _fernet(key)

        try:
            plain = json.loads(f.decrypt(ciphertext.encode("latin-1")))
            if not isinstance(plain, dict):
                return False
            # Normalise to the expected shape (forward-compat with future fields).
            if "credentials" not in plain or not isinstance(plain["credentials"], dict):
                plain["credentials"] = {}
            if "notes" not in plain or not isinstance(plain["notes"], dict):
                plain["notes"] = {}
            self._key = key
            self._entries = plain
            return True
        except Exception:
            return False

    def lock(self) -> None:
        """Clear the cached key, rendering the vault locked."""
        self._key = None
        self._entries = {"credentials": {}, "notes": {}}

    # ------------------------------------------------------------------
    # Credentials
    # ------------------------------------------------------------------

    def register_credential(self, name: str, username: str, password: str) -> None:
        """Store (or overwrite) a named credential."""
        self._require_unlocked()
        name = validate_name(name)
        self._register_credential_raw(name, username, password)

    def _register_credential_raw(self, name: str, username: str, password: str) -> None:
        """Store a credential without name validation (internal use only)."""
        self._require_unlocked()
        self._entries["credentials"][name] = {
            "username": username,
            "password": password,
        }
        self._write()

    def get_credential(self, name: str) -> tuple[str, str] | None:
        """Return ``(username, password)`` or ``None``."""
        self._require_unlocked()
        entry = self._entries["credentials"].get(name)
        if entry is None:
            return None
        return (entry["username"], entry["password"])

    def list_credentials(self) -> list[str]:
        """Return names of all stored credentials."""
        self._require_unlocked()
        return list(self._entries["credentials"].keys())

    def delete_credential(self, name: str) -> None:
        """Remove a credential (no-op if missing)."""
        self._require_unlocked()
        self._entries["credentials"].pop(name, None)
        self._write()

    # ------------------------------------------------------------------
    # Secure notes
    # ------------------------------------------------------------------

    def register_secure_note(self, name: str, text: str) -> None:
        """Store (or overwrite) a secure note."""
        self._require_unlocked()
        name = validate_name(name)
        self._entries["notes"][name] = text
        self._write()

    def get_secure_note(self, name: str) -> str | None:
        """Return the note text or ``None``."""
        self._require_unlocked()
        return self._entries["notes"].get(name)

    def list_secure_notes(self) -> list[str]:
        """Return names of all stored notes."""
        self._require_unlocked()
        return list(self._entries["notes"].keys())

    def delete_secure_note(self, name: str) -> None:
        """Remove a note (no-op if missing)."""
        self._require_unlocked()
        self._entries["notes"].pop(name, None)
        self._write()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _require_unlocked(self) -> None:
        if self.is_locked():
            raise RuntimeError("Vault is locked")

    def _write(self, salt: bytes | None = None) -> None:
        """Encrypt and persist the current entries.

        *salt* is only provided during :meth:`initialize`; after that we
        reuse the salt stored in the existing file.
        """
        assert self._key is not None

        if salt is None:
            salt = self._read_salt()

        f = _fernet(self._key)
        plain = json.dumps(self._entries, separators=(",", ":"))
        ciphertext = f.encrypt(plain.encode("utf-8")).decode("latin-1")

        blob = {
            "version": VAULT_VERSION,
            "salt": salt.decode("latin-1"),
            "data": ciphertext,
        }

        os.makedirs(os.path.dirname(self._filepath) or ".", exist_ok=True)
        with open(self._filepath, "w") as fh:
            json.dump(blob, fh, separators=(",", ":"))

    def _read_salt(self) -> bytes:
        """Read the salt from the existing vault file.

        If no file exists yet, generate a fresh salt.
        """
        if not os.path.isfile(self._filepath):
            return secrets.token_bytes(_SALT_LENGTH)
        with open(self._filepath, "rb") as fh:
            blob = json.loads(fh.read().decode("utf-8"))
        return blob["salt"].encode("latin-1")


# ---------------------------------------------------------------------------
# VaultManager — multi-tier vault (master + optional local)
# ---------------------------------------------------------------------------


class VaultManager:
    """Manages a master vault and an optional per-project local vault.

    The **master vault** lives at ``~/.agents/vault.enc`` and is encrypted
    with the user's master password.  An optional **local vault** can be
    created per project at ``{wd}/.agents/vault.enc`` — its password is a
    random key generated at creation time and stored as a credential in the
    master vault.

    On :meth:`unlock`, the master vault is unlocked first, then any local
    vault belonging to the current working directory is automatically
    unlocked using its stored passkey.  The user only ever enters one
    password.

    Credential lookups check the local vault first, then fall back to the
    master vault.
    """

    def __init__(self, master_path: str, working_dir: str) -> None:
        self.master_path: str = master_path
        self.working_dir: str = working_dir
        self.master: Vault = Vault(master_path)
        self._local: Vault | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def is_locked(self) -> bool:
        """``True`` when the master vault is locked."""
        return self.master.is_locked()

    def initialize_master(self, master_password: str) -> None:
        """Create a brand-new master vault, overwriting any existing file."""
        master_password = validate_master_password(master_password)
        self.master.initialize(master_password)
        self._local = None

    def unlock(self, master_password: str) -> bool:
        """Unlock the master vault, then auto-unlock any local vault.

        Returns ``True`` if the master password is correct.
        """
        if not self.master.unlock(master_password):
            return False
        self._try_unlock_local()
        return True

    def lock(self) -> None:
        """Lock both master and local vaults, clearing all cached keys."""
        self.master.lock()
        if self._local is not None:
            self._local.lock()
            self._local = None

    # ------------------------------------------------------------------
    # Local vault management
    # ------------------------------------------------------------------

    def has_local_vault(self) -> bool:
        """``True`` if a local vault file exists for the current project."""
        return os.path.isfile(self._local_path())

    def create_local_vault(self) -> None:
        """Create a local vault for the current project.

        A random passkey is generated and stored as a credential
        ``"vault:{project_abs_path}"`` in the master vault.  The local
        vault is immediately available for reads and writes.

        Raises :class:`RuntimeError` if the master vault is locked.
        """
        self._require_unlocked()

        passkey_bytes = secrets.token_bytes(32)
        passkey = urlsafe_b64encode(passkey_bytes).decode("ascii")

        local = Vault(self._local_path())
        local.initialize(passkey)
        self._local = local

        project_abs = os.path.abspath(self.working_dir)
        self.master._register_credential_raw(f"vault:{project_abs}", "_", passkey)

    def remove_local_vault(self) -> None:
        """Delete the local vault file and its passkey from the master vault."""
        self._require_unlocked()
        local_path = self._local_path()
        project_abs = os.path.abspath(self.working_dir)

        if self._local is not None:
            self._local.lock()
            self._local = None

        self.master.delete_credential(f"vault:{project_abs}")

        try:
            os.remove(local_path)
        except FileNotFoundError:
            pass

    # ------------------------------------------------------------------
    # Credentials
    # ------------------------------------------------------------------

    def register_credential(self, name: str, username: str, password: str) -> None:
        """Store a credential in the local vault if available, otherwise master."""
        self._require_unlocked()
        name = validate_name(name)
        target = self._write_target()
        target.register_credential(name, username, password)

    def get_credential(self, name: str) -> tuple[str, str] | None:
        """Look up a credential — local first, then master."""
        self._require_unlocked()
        if self._local is not None and not self._local.is_locked():
            result = self._local.get_credential(name)
            if result is not None:
                return result
        return self.master.get_credential(name)

    def list_credentials(self) -> list[str]:
        """Return all credential names from both vaults (deduplicated).

        Internal ``vault:*`` passkey entries are excluded.
        """
        self._require_unlocked()
        names: set[str] = {
            n for n in self.master.list_credentials()
            if not n.startswith("vault:")
        }
        if self._local is not None and not self._local.is_locked():
            names |= {
                n for n in self._local.list_credentials()
                if not n.startswith("vault:")
            }
        return sorted(names)

    def delete_credential(self, name: str) -> None:
        """Delete a credential — from local if present there, otherwise master."""
        self._require_unlocked()
        if self._local is not None and not self._local.is_locked():
            if self._local.get_credential(name) is not None:
                self._local.delete_credential(name)
                return
        self.master.delete_credential(name)

    # ------------------------------------------------------------------
    # Secure notes
    # ------------------------------------------------------------------

    def register_secure_note(self, name: str, text: str) -> None:
        """Store a secure note in the local vault if available, otherwise master."""
        self._require_unlocked()
        name = validate_name(name)
        target = self._write_target()
        target.register_secure_note(name, text)

    def get_secure_note(self, name: str) -> str | None:
        """Look up a secure note — local first, then master."""
        self._require_unlocked()
        if self._local is not None and not self._local.is_locked():
            result = self._local.get_secure_note(name)
            if result is not None:
                return result
        return self.master.get_secure_note(name)

    def list_secure_notes(self) -> list[str]:
        """Return all secure note names from both vaults (deduplicated)."""
        self._require_unlocked()
        names: set[str] = set(self.master.list_secure_notes())
        if self._local is not None and not self._local.is_locked():
            names |= set(self._local.list_secure_notes())
        return sorted(names)

    def delete_secure_note(self, name: str) -> None:
        """Delete a secure note — from local if present there, otherwise master."""
        self._require_unlocked()
        if self._local is not None and not self._local.is_locked():
            if self._local.get_secure_note(name) is not None:
                self._local.delete_secure_note(name)
                return
        self.master.delete_secure_note(name)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _local_path(self) -> str:
        return os.path.join(self.working_dir, ".agents", "vault.enc")

    def _require_unlocked(self) -> None:
        if self.is_locked():
            raise RuntimeError("Vault is locked")

    def _write_target(self) -> Vault:
        """Return the vault to write to (local if available, else master)."""
        if self._local is not None and not self._local.is_locked():
            return self._local
        return self.master

    def _try_unlock_local(self) -> None:
        """Attempt to auto-unlock the local vault using the passkey stored
        in the (now-unlocked) master vault."""
        if not self.has_local_vault():
            return
        project_abs = os.path.abspath(self.working_dir)
        cred = self.master.get_credential(f"vault:{project_abs}")
        if cred is None:
            return
        _, passkey = cred
        local = Vault(self._local_path())
        if local.unlock(passkey):
            self._local = local
