# Step 5: Password Vault

**Branch:** `steps-3-4-5-paths-config-vault`  
**Date:** 2026-05-01

---

## Overview

Encrypted credential store backed by a single versioned JSON file. Uses
Fernet symmetric encryption with PBKDF2HMAC key derivation. Stores two
entry types: credentials (name → username + password) and secure notes
(name → free text).

The vault is session-locked — a master password must be supplied to unlock
before any read or write operation.

---

## Implementation

### `core/vault.py`

#### Cryptographic choices

| Component | Value |
|---|---|
| Key derivation | PBKDF2HMAC, SHA-256, 480,000 iterations |
| Salt | 32 random bytes per vault file |
| Encryption | Fernet (AES-128-CBC + HMAC-SHA256) |
| File format version | `VAULT_VERSION = 1` |

#### `Vault` class

```python
class Vault:
    def __init__(self, filepath: str) -> None
    def is_locked(self) -> bool
    def initialize(self, master_password: str) -> None
    def unlock(self, master_password: str) -> bool
    def lock(self) -> None
    # Credentials
    def register_credential(self, name: str, username: str, password: str) -> None
    def get_credential(self, name: str) -> tuple[str, str] | None
    def list_credentials(self) -> list[str]
    def delete_credential(self, name: str) -> None
    # Secure notes
    def register_secure_note(self, name: str, text: str) -> None
    def get_secure_note(self, name: str) -> str | None
    def list_secure_notes(self) -> list[str]
    def delete_secure_note(self, name: str) -> None
```

**Lifecycle:**

1. **`initialize(password)`** — creates a new vault file. Generates fresh
   salt, derives key, writes empty entries. Existing file is overwritten.
   Vault is unlocked afterwards.

2. **`unlock(password)`** — attempts to decrypt the file. Validates by
   decrypting ALL stored entries — a single wrong byte causes Fernet to
   reject the entire file. Returns `True` on success. Returns `False` on
   wrong password or corrupted file. For a brand-new vault with no file
   yet, any password is accepted.

3. **`lock()`** — clears the in-memory key and entries. Subsequent
   read/write operations raise `RuntimeError`.

**State when locked:**

- `is_locked()` returns `True`.
- All CRUD operations raise `RuntimeError("Vault is locked")`.
- Vault can be re-unlocked with `unlock()`.

**State when no file exists:**

- `is_locked()` returns `False` (nothing to protect yet).
- `unlock()` accepts any password.
- On first `_write()`, a salt is generated and the file is created.

**Internal data shape:**
```python
{
    "credentials": {
        "ollama": {"username": "apiuser", "password": "sk-xxx"},
        ...
    },
    "notes": {
        "api-token": "some long text",
        ...
    }
}
```

**File format (on disk):**
```json
{"version":1,"salt":"abc123...","data":"gAAAAAB..."}
```

`salt` and `data` are base64-encoded (Fernet's url-safe base64 for the
ciphertext, latin-1 for salt to avoid padding issues in JSON).

**Concurrent unlock:** The design doc mentions queuing concurrent unlock
callers so only one modal is shown. This is a TUI concern — the vault's
core API is synchronous. The TUI layer (Step 16, `VaultTab`) will handle
modal queuing.

---

## Tests

### `tests/test_vault.py` — 26 tests

| Class | Tests | Coverage |
|---|---|---|
| `TestInitialize` | 3 | creates file, unlocked after init, overwrites existing |
| `TestLockUnlock` | 4 | not locked initially, lock clears session, unlock correct pw, unlock wrong pw, unlock on empty vault |
| `TestCredentials` | 5 | register + retrieve, missing → None, list, delete, delete missing, overwrite |
| `TestSecureNotes` | 4 | register + retrieve, missing → None, list, delete, overwrite |
| `TestLockedOperations` | 4 | register credential raises, get raises, register note raises, get note raises |
| `TestPersistence` | 3 | data survives reload, wrong password can't read, reinitialize discards old data |
| **Total** | **26** | |

All tests use `tempfile.TemporaryDirectory` — no filesystem pollution.

---

## Design Decisions

1. **PBKDF2 with 480K iterations.** Strong but not excessive for modern
   hardware. Configurable via `_PBKDF2_ITERATIONS` if needed.

2. **Salt per vault file, stored in the file.** Not global, not in a
   separate file. The vault file is self-contained.

3. **Unlock validates by decrypting entries.** No separate "check hash"
   — Fernet's built-in HMAC does the work. A wrong password produces a
   clear failure, not silent corruption.

4. **No async API.** The vault's crypto operations are fast (one derive,
   one decrypt/encrypt per operation). Async isn't needed. The TUI layer
   can wrap calls in a thread if desired.

5. **New file = unlocked.** Before the first `initialize()`, there's
   nothing to protect. This avoids forcing the user to set up a password
   immediately.

6. **Locked operations raise `RuntimeError`.** Clear, loud failure.
   Callers should check `is_locked()` before operations if they want
   graceful handling.
