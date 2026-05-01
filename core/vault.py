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
from copy import deepcopy
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
