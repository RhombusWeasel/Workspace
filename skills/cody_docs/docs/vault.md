# Password Vault

**File:** `core/vault.py`
**Depends on:** `cryptography` (Fernet, PBKDF2HMAC, hashes), `json`, `os`, `secrets`

---

## Purpose

Encrypted credential and secure-note storage.  Two tiers:

1. **Master vault** (`~/.agents/vault.enc`) — encrypted with the user's
   master password.  Holds all credentials and notes that aren't
   project-specific.

2. **Local vault** (`{wd}/.agents/vault.enc`) — per-project, encrypted with
   a random key stored as a credential in the master vault.  Automatically
   unlocked when the master vault is unlocked — the user only ever enters
   one password.

---

## Crypto Stack

```
User password
      │
      ▼
PBKDF2HMAC (SHA-256, 480K iterations, 32-byte salt)
      │
      ▼
Fernet key (urlsafe base64, 32 bytes)
      │
      ▼
Fernet encryption (AES-128-CBC + HMAC-SHA256)
      │
      ▼
Encrypted vault file on disk
```

**Validation on unlock:** the system attempts to decrypt all stored entries.
If the password is wrong, Fernet's HMAC check fails and the unlock returns
`False`.  There is no plaintext comparison or stored hash.

---

## Classes

### `Vault` — Single encrypted file

```python
class Vault:
    def __init__(self, filepath: str)
```

Low-level encrypted store.  Manages one vault file.

#### Lifecycle

| Method | Description |
|---|---|
| `is_locked() -> bool` | `True` when no key is cached (or no file exists — treated as unlocked-empty) |
| `initialize(password)` | Create a brand-new vault, overwriting any existing file. Generates fresh salt + key. |
| `unlock(password) -> bool` | Attempt to decrypt. Returns `True` on success. |
| `lock()` | Clear cached key and entries. |

#### Credentials

| Method | Description |
|---|---|
| `register_credential(name, username, password)` | Store or overwrite |
| `get_credential(name) -> (str, str) \| None` | Returns `(username, password)` |
| `list_credentials() -> list[str]` | All credential names |
| `delete_credential(name)` | No-op if missing |

#### Secure Notes

| Method | Description |
|---|---|
| `register_secure_note(name, text)` | Store or overwrite |
| `get_secure_note(name) -> str \| None` | Returns note text |
| `list_secure_notes() -> list[str]` | All note names |
| `delete_secure_note(name)` | No-op if missing |

#### Locked-state behavior

All read/write methods call `_require_unlocked()` first.  If locked, they
raise `RuntimeError("Vault is locked")` — no silent failure, no data leak.

---

### `VaultManager` — Multi-tier orchestrator

```python
class VaultManager:
    def __init__(self, master_path: str, working_dir: str)
```

Manages a master vault + optional local vault.  The local vault is
auto-unlocked via a passkey stored as a credential in the master vault.

#### Lifecycle

| Method | Description |
|---|---|
| `is_locked() -> bool` | Delegates to `master.is_locked()` |
| `initialize_master(password)` | Creates master vault from scratch |
| `unlock(password) -> bool` | Unlock master → auto-unlock local via stored passkey |
| `lock()` | Lock both, clear all cached keys |

#### Local vault management

| Method | Description |
|---|---|
| `has_local_vault() -> bool` | Checks if `{wd}/.agents/vault.enc` exists |
| `create_local_vault()` | Generates random passkey, stores it as `vault:{abs_path}` credential in master, initializes local vault |
| `remove_local_vault()` | Deletes local file, removes passkey credential from master |

#### Credential & Note routing

All CRUD methods follow the same pattern: **local first, then master**.

| Method | Lookup | Write |
|---|---|---|
| `get_credential(name)` | Local → Master | — |
| `register_credential(name, u, p)` | — | Local (if exists) else Master |
| `delete_credential(name)` | Local → Master | Local (if found) else Master |
| `list_credentials()` | Master ∪ Local, excluding `vault:*` | — |
| `get_secure_note(name)` | Local → Master | — |
| `register_secure_note(name, text)` | — | Local (if exists) else Master |
| `delete_secure_note(name)` | Local → Master | Local (if found) else Master |
| `list_secure_notes()` | Master ∪ Local | — |

---

## Vault File Format

```json
{
  "version": 1,
  "salt": "<32 bytes, latin-1 encoded>",
  "data": "<Fernet-encrypted JSON, latin-1 encoded>"
}
```

The decrypted `data` is:

```json
{
  "credentials": {
    "github": {"username": "alice", "password": "s3cret"},
    "vault:/home/alice/projects/foo": {"username": "_", "password": "<random-key>"}
  },
  "notes": {
    "api-key-hint": "Check the wiki page"
  }
}
```

Internal `vault:*` entries are auto-managed passkeys — they are filtered
out of `list_credentials()` output but visible to `get_credential()`.

---

## Unlock Flow

```
User opens app
      │
      ▼
VaultManager.is_locked() → True   (no key in memory)
      │
      ▼
VaultPanel.on_mount() → self._vault = ctx.vault
  → _rebuild() → sees is_locked()
  → posts CodyEvent("vault.needs_unlock")
      │
      ▼
@register_handler("vault.needs_unlock")
  → pushes InputModal for master password
  → user enters password → vault_manager.unlock(password)
      │
      ├── Master vault decrypt succeeds → key cached
      │   └── _try_unlock_local()
      │       ├── local vault file exists ✓
      │       ├── get_credential("vault:{abs_path}") → "random-key"
      │       └── local_vault.unlock("random-key") → success
      │
      └── Returns True → panel._rebuild() → shows entries
```

If the vault file doesn't exist yet:

```
VaultPanel._rebuild() → no file at master._filepath
  → posts CodyEvent("vault.needs_init")
  → @register_handler("vault.needs_init")
  → pushes InputModal("Create master password:")
  → vault_manager.initialize_master(password)
  → panel._rebuild() → empty vault ready for entries
```

---

## Security Properties

1. **Master password never stored** — only the derived key is cached in
   memory for the session.

2. **Salt is random per vault** — even the same password across different
   vault files produces different encryption keys.

3. **No plaintext comparison** — unlock validation uses Fernet's built-in
   HMAC.  A wrong password produces a `cryptography` exception, caught and
   converted to `False`.

4. **No timing side-channel** — `unlock()` returns `False` immediately on
   any decryption failure.  There's no hash comparison to time.

5. **Local vault is transparent** — the user never sees the passkey.  It's
   a random 32-byte value stored inside the already-encrypted master vault.

6. **Lock clears everything** — `lock()` calls `_key = None` and resets
   `_entries` to empty dicts.  No stale data in memory.

---

## API Key Resolution for Providers

Providers resolve API keys from the vault:

```python
# In core/providers/ollama.py
def _resolve_api_key(self) -> str | None:
    vault = self._get_vault_manager()
    if vault is None or vault.is_locked():
        return None
    try:
        cred = vault.get_credential("ollama")
    except RuntimeError:
        return None  # vault is locked
    if cred is None:
        return None
    _, key = cred
    return key
```

Keys are **not** read from config files or environment variables — the vault
is the single source of truth for secrets.

---

## Testing

### Unit tests for `Vault`

```python
def test_encrypt_decrypt_roundtrip(tmp_path):
    vault_path = tmp_path / "test.enc"
    v = Vault(str(vault_path))
    v.initialize("password123")
    v.register_credential("svc", "user", "pass")
    assert v.get_credential("svc") == ("user", "pass")

    v.lock()
    assert v.is_locked()
    assert v.unlock("password123")
    assert v.get_credential("svc") == ("user", "pass")

def test_wrong_password_rejected(tmp_path):
    v = Vault(str(tmp_path / "test.enc"))
    v.initialize("correct")
    v.lock()
    assert not v.unlock("wrong")
    assert v.is_locked()
```

### Integration tests for `VaultManager`

```python
def test_local_vault_auto_unlock(tmp_path):
    vault_path = tmp_path / "vault.enc"
    wd = tmp_path / "project"
    wd.mkdir()

    mgr = VaultManager(str(vault_path), str(wd))
    mgr.initialize_master("master")
    mgr.create_local_vault()
    mgr.lock()

    assert mgr.unlock("master")
    assert mgr.has_local_vault()
    # Local vault was auto-unlocked — read works
    assert mgr.get_credential("test") is None
```

---

## Design Decisions

1. **Master + local tiers** — One password unlocks everything.  Project
   secrets stay with the project (`.agents/vault.enc` can be committed
   to a private repo if desired).

2. **No config/env fallback for secrets** — The vault is the single
   source of truth.  Mixing sources leads to ambiguity about which
   value is actually in use.

3. **RuntimeError on locked access** — Not returning `None` or empty
   strings.  A locked vault is a bug condition, not a data condition.

4. **480K PBKDF2 iterations** — OWASP 2023 recommendation for SHA-256.
   Deliberately slow to make brute-force expensive.

5. **No password strength enforcement** — The vault encrypts whatever
   password the user provides.  Strength is the user's responsibility.
   Adding a strength meter would be a UI concern, not a core concern.
