# Step 3: Path System

**Branch:** `steps-3-4-5-paths-config-vault`  
**Date:** 2026-05-01

---

## Overview

Three-tier path resolution — the foundation Cody uses to find skills, tools,
themes, commands, and config across bundled, user, and project locations.

Later tiers override earlier tiers for same-named resources.

---

## Implementation

### `core/paths.py`

Three functions, zero dependencies beyond `os`:

```python
def cody_dir() -> str
    # /home/.../nu_cody  (two levels up from this file)

def agents_dir() -> str
    # ~/.agents

def resolve(subpath: str, working_dir: str) -> list[str]
    # Returns [cody_dir/subpath, agents_dir/subpath, working_dir/.agents/subpath]
```

| Tier | Purpose | Example (`resolve("skills", "/proj")`) |
|---|---|---|
| 1 | Bundled defaults | `/home/.../nu_cody/skills` |
| 2 | User overrides | `~/.agents/skills` |
| 3 | Project overrides | `/proj/.agents/skills` |

All paths go through `os.path.normpath()` to clean up slashes and dots.

---

## Tests

### `tests/test_paths.py` — 10 tests

| Class | Tests | What it covers |
|---|---|---|
| `TestCodyDir` | 3 | returns string, is absolute, not empty |
| `TestAgentsDir` | 3 | returns string, is absolute, ends with `.agents` |
| `TestResolve` | 4 | returns 3 paths, all absolute, subpath appended, nested subpaths, empty subpath, trailing slash on working_dir |

No mocking needed — these are pure filesystem operations that work in any
test environment.

---

## Design Decisions

1. **Simplified from original.** Original had `tiered_dir_templates()`,
   `resolve_dir_templates()`, `resolved_tiered_paths()`, and a `$CODY_DIR`
   env var lookup. Stripped down to three functions — templates added
   complexity without value. The `$CODY_DIR` env var is unused; location
   is derived from the package's own path.

2. **`cody_dir()` uses `__file__`.** Two `os.path.dirname()` calls up from
   `core/paths.py` to the repo root. This means the function *must* live
   at `core/paths.py` — moving it would require updating the offset.

3. **No trailing slash normalization beyond `normpath`.** `resolve("x", "/tmp/")`
   produces `/tmp/.agents/x` — `normpath` handles the double-slash.

4. **Static return shape.** Always returns exactly three paths. Consumers
   iterate and check `os.path.exists()` / `os.path.isdir()` to see which
   tiers are active.
