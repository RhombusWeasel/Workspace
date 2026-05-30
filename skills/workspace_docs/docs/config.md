# Config Manager

**File:** `core/config.py`
**Depends on:** `json`, `os`, `copy`

---

## Purpose

Layered JSON configuration with dot-path access and diff-based saving.
Config loads multiple JSON files in order and deep-merges them.  Later files
override earlier ones.  When saving, only keys that differ from the baseline
(merge of all files except the last) are written — keeping user config files
clean and minimal.

Modules register defaults at import time; `apply_defaults()` fills missing
keys without touching user-set values.

---

## Architecture

```
Load order (last wins):
  global.json  →  project.json  →  [user overrides]

                         │
                         ▼
              ┌─────────────────────┐
              │    Config._data     │  ← full merged config
              │  (in-memory dict)   │
              └─────────┬───────────┘
                        │
              ┌─────────▼───────────┐
              │  Config._baseline   │  ← merge of all except last file
              │   (for diff calc)   │
              └─────────┬───────────┘
                        │
              ┌─────────▼───────────┐
              │   Config._defaults  │  ← fed from module-level register_defaults()
              │ (registered at      │
              │  import time)       │
              └─────────────────────┘
```

### Save diff logic

```
_write_what = diff(merged_data, baseline)
```

Only keys that were *changed* (or added) relative to the baseline are written.
Keys that match the baseline are omitted — they were already in earlier files.

---

## API

### Constructor

```python
cfg = Config(["/path/to/global.json", "/path/to/project.json"])
```

Takes an ordered list of paths.  Files are loaded and merged in order.

### `get(key, default=None)`

```python
provider = cfg.get("session.provider")       # → "ollama"
port     = cfg.get("session.port", 11434)    # → 11434 if key missing
name    = cfg.get("db.connections[0].name")  # → list indexing supported
```

Dot-separated path into the nested dict.  Supports `[N]` notation for
list indexing — e.g. `"db.connections[0].name"` navigates into the first
list item.  Returns `default` if any segment is missing, the list index is
out of range, or the intermediate value is not a dict.

### `set(key, value)`

```python
cfg.set("session.model", "deepseek-v4-pro")
cfg.set("ui.theme.colors.primary", "#ff0000")
cfg.set("db.connections[0].name", "Renamed DB")  # list indexing supported
```

Creates intermediate dicts as needed.  Supports `[N]` notation for list
indexing — the list and all intermediate dicts must already exist; `set()`
will not create new list entries.  Does **not** validate types or check for
conflicts — the UI layer handles validation.

### `defaults(d)`

```python
cfg.defaults({
    "session": {
        "provider": "ollama",
        "model": "llama3.2",
    }
})
```

Accumulates defaults across multiple calls.  Call early (at module import
time) to register system defaults before user configs are loaded.

### `apply_defaults()`

```python
cfg.apply_defaults()
```

Fills any keys missing from `_data` with values from `_defaults`.
Existing keys (including user-set values) are **not** overwritten.
Call this after all defaults are registered and config files are loaded.

### `save()`

```python
cfg.save()
```

Writes the diff (`_data` minus `_baseline`) as JSON to the **last** config
path.  Creates parent directories if needed.  Does nothing if there are no
paths.

---

## Module-Level Defaults

In addition to the instance method `cfg.defaults()`, there is a module-level
registry for defaults that modules populate at **import time**, before a
`Config` instance even exists.  Bootstrap collects these and feeds them into
the `Config` instance.

### `register_defaults(d)`

```python
from core.config import register_defaults

register_defaults({
    "session": {"provider": "ollama", "model": "llama3.2"}
})
```

Accumulates defaults into a module-level dict.  Call this at module import
time (i.e. at the top level of your module, not inside a function).
Later calls deep-merge with earlier ones; later values win on conflict.

### `get_registered_defaults()`

```python
from core.config import get_registered_defaults

defaults = get_registered_defaults()  # → deep copy of accumulated defaults
```

Returns a deep copy of all defaults registered via `register_defaults()`.
Used by bootstrap to feed accumulated defaults into a `Config` instance.

### `reset_registered_defaults()`

```python
from core.config import reset_registered_defaults
```

Clears all accumulated module-level defaults.  Use between tests to prevent
cross-test pollution.

---

## Usage Patterns

### Bootstrap sequence

```python
from core.config import Config, get_registered_defaults

# 1. Create config (loads files immediately)
cfg = Config([global_path, project_path])

# 2. Feed in module-level defaults (registered by modules at import time)
cfg.defaults(get_registered_defaults())

# 3. Apply defaults (fills gaps without touching user values)
cfg.apply_defaults()
```

### Module registering defaults

```python
# In core/providers/ollama.py (imported before bootstrap)
from core.config import register_defaults

register_defaults({
    "session": {"provider": "ollama", "model": "llama3.2"}
})
```

Modules call `register_defaults()` at import time.  The bootstrap sequence
then collects these via `get_registered_defaults()` and feeds them into
the `Config` instance.  There is no global `config` singleton to import.

### Reading in a widget

```python
theme = self.app.context.config.get("ui.theme", "default")
```

---

## Internal Helpers

These are module-level functions used internally by `Config`.  They are
not part of the public API:

| Function | Purpose |
|---|---|
| `_deep_merge(dst, src)` | Recursive in-place merge, `src` wins |
| `_deep_merge_missing(dst, src)` | Only fills keys not in `dst` |
| `_diff(merged, baseline)` | Returns dict of keys where `merged ≠ baseline` |

---

## File Format

Each config file is standard JSON:

```json
{
  "session": {
    "provider": "ollama",
    "model": "llama3.2"
  },
  "ui": {
    "theme": "haxor"
  }
}
```

Top-level must be a JSON object.  Arrays are not supported as config roots
(config structure is always nested dicts).

---

## Testing

```python
def test_config_deep_merge():
    cfg = Config([])
    cfg.set("a.b.c", 1)
    cfg.set("a.b.d", 2)
    assert cfg.get("a.b.c") == 1

def test_diff_only_changed():
    cfg = Config([file1, file2])
    cfg.set("new.key", "value")
    cfg.save()
    # file2 now contains only {"new": {"key": "value"}}
    # Keys from file1 are NOT re-written.
```

### Test fixtures

```python
@pytest.fixture
def tmp_config(tmp_path):
    g = tmp_path / "global.json"
    g.write_text('{"base": "from-global"}')
    p = tmp_path / "project.json"
    p.write_text('{"base": "from-project"}')
    return Config([str(g), str(p)])
```

---

## Design Decisions

1. **Diff-based save** — Keeps user config files minimal.  Only changed keys
   are persisted.  Makes it easy to see what the user actually customized.

2. **No schema validation** — Config is a raw `dict`.  Validation belongs in
   the UI layer (the ConfigPanel and individual widgets validate on input).
   Adding a schema layer would couple the config to every consumer.

3. **Defaults after loading** — Defaults are registered at module import time
   but applied after config files are loaded.  This means user files always
   win over defaults, and defaults only fill gaps.

4. **No hot-reload** — Config changes require a restart (or the ConfigPanel's
   Save button explicitly triggers persistence).  The `set()` method only
   mutates the in-memory dict; it does not auto-save.
