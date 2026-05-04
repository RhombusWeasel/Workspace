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
              │   Config._defaults  │  ← accumulated from defaults() calls
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
```

Dot-separated path into the nested dict.  Returns `default` if any segment
is missing or the intermediate value is not a dict.

### `set(key, value)`

```python
cfg.set("session.model", "deepseek-v4-pro")
cfg.set("ui.theme.colors.primary", "#ff0000")
```

Creates intermediate dicts as needed.  Does **not** validate types or check
for conflicts — the UI layer handles validation.

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

## Usage Patterns

### Bootstrap sequence

```python
# 1. Create config (loads files immediately)
cfg = Config([global_path, project_path])

# 2. Register defaults (modules do this at import time)
cfg.defaults({...})

# 3. Apply defaults (fills gaps without touching user values)
cfg.apply_defaults()
```

### Module registering defaults

```python
# In core/providers/base.py (imported before bootstrap)
from core.config import config  # if singleton exists
config.defaults({
    "session": {"provider": "ollama", "model": "llama3.2"}
})
```

### Reading in a widget

```python
theme = self.app.context.config.get("ui.theme", "default")
```

---

## Internal Helpers

These are module-level functions, not exported as public API:

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
