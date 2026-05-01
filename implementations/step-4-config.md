# Step 4: Config Manager

**Branch:** `steps-3-4-5-paths-config-vault`  
**Date:** 2026-05-01

---

## Overview

Layered JSON configuration that loads multiple files in order (global →
project), deep-merges them, and provides dot-path access. When saving, only
keys that differ from the baseline are written — config files stay clean.

---

## Implementation

### `core/config.py`

#### Module-level helpers

| Function | Purpose |
|---|---|
| `_deep_merge(dst, src)` | Merge `src` into `dst` in-place. Recursive on nested dicts. `src` wins. |
| `_deep_merge_missing(dst, src)` | Like `_deep_merge` but only fills keys not already in `dst`. |
| `_diff(merged, baseline)` | Return a dict containing only keys where `merged` differs from `baseline`. |

All helpers use `deepcopy` to prevent shared mutable references.

#### `Config` class

```python
class Config:
    def __init__(self, paths: list[str]) -> None
    def get(self, key: str, default: Any = None) -> Any
    def set(self, key: str, value: Any) -> None
    def defaults(self, d: dict) -> None
    def apply_defaults(self) -> None
    def save(self) -> None
```

**Loading (`__init__` → `_load`):**
1. Iterate `paths` in order.
2. For each file that exists, load JSON and deep-merge into `_data`.
3. All files *except the last* are also merged into `_baseline`.
4. The last file is the writable target — edits go there.

**Dot-path access (`get` / `set`):**
- `get("a.b.c")` — splits on `.`, walks nested dicts, returns value or default.
- `set("a.b.c", val)` — creates intermediate dicts as needed, then sets.

**Defaults system (`defaults` / `apply_defaults`):**
- Modules call `config.defaults({...})` at import time. Calls accumulate.
- `apply_defaults()` fills `_data` with defaults for missing keys only —
  never overrides user-set values.
- Deep merging: `cfg.set("db.host", "prod"); cfg.defaults({"db": {...}}); cfg.apply_defaults()` — `db.host` stays `"prod"`, `db.port` gets filled.

**Diff-based saving (`save`):**
- Computes `_diff(_data, _baseline)` — only keys that changed vs the
  read-only files.
- Writes the result as JSON to the last path (`_paths[-1]`).
- The file only contains user edits; defaults and inherited values are
  transparent.

---

## Tests

### `tests/test_config.py` — 18 tests

| Class | Tests | Coverage |
|---|---|---|
| `TestInit` | 2 | empty paths → empty config, single file loaded |
| `TestMerge` | 2 | later overrides earlier, deep merge nested objects |
| `TestGetSet` | 5 | missing key → None, default fallback, nested dot-path, set creates structure, overwrite existing |
| `TestDefaults` | 5 | fill missing, don't override existing, deep merge, accumulate across calls, later overrides earlier |
| `TestSave` | 4 | writes to last path, diff vs baseline, no last path = no-op, only changed keys |
| **Total** | **18** | |

All tests use `tempfile.TemporaryDirectory` — no filesystem pollution.

---

## Design Decisions

1. **Last file is writable, rest are baseline.** Simple rule — no complex
   "which tier do I save to" logic. The last path in the list is always the
   writable project config.

2. **Deep merge, not flat overlay.** Nested objects merge recursively rather
   than being replaced wholesale. This means a project config setting
   `db.port` doesn't wipe out the global `db.host`.

3. **Accumulating defaults.** Multiple `defaults()` calls merge into a single
   default blob. This lets each subsystem register its own defaults at import
   time, independently, and one `apply_defaults()` call fills everything.

4. **Diff-based save keeps files readable.** User config files never contain
   hundreds of inherited keys — just the ones the user actually changed.
