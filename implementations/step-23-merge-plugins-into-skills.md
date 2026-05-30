# Step 23: Merge Plugins into Skills — Implementation Notes

## What Changed

The separate `plugins/` concept has been eliminated. All extensions are now **skills** under `skills/`. This unifies the discovery, loading, and extension mechanisms into a single concept, while maintaining compatibility with the Anthropic skill specification (ClaudeCode, Codex ecosystem skills).

## Key Design Decision: Optional `__init__.py`

The central design decision: **`__init__.py` is optional**.

| Skill type | Has `__init__.py`? | Loading behavior |
|---|---|---|
| Ecosystem skill (Anthropic spec) | ❌ | SKILL.md discovered, body available to agent, scripts runnable via `run_skill`. No Python code executes at import time. |
| UI skill | ✅ | Full `importlib.util.spec_from_file_location` load with `__path__`/`__package__` set to `skills.{name}`. Nested sub-packages work. Side-effect registrations fire at import. |
| Hybrid (agent knowledge + flat components) | ❌ | Body for agent, `components/` loaded via flat file-by-file imports. No `__init__.py` needed for flat structures. |

This ensures that any skill following the Anthropic specification (just SKILL.md + optional scripts/) works without modification.

## New SkillManager Methods

- **`get_skill_init_dirs()`** — returns base directories of enabled skills that contain `__init__.py`. Used by bootstrap to determine which skills need the full package-load treatment.
- **`get_skill_services()`** — returns collected service factories from loaded skills. Populated by bootstrap after `_load_skill_init_files()` runs.
- **`set_skill_services(factories)`** — stores service factories collected during bootstrap. Called after skill `__init__.py` files are loaded and their `SKILL_SERVICES` dicts are collected.

## New AppContext Field

- **`services: dict[str, Any]`** — dynamic service instances from skill `SKILL_SERVICES` declarations. Known services like `db_connections` also get a dedicated field for convenience and type-safety, but everything lives in `services` too for generic access.

## SKILL_SERVICES Convention

Replaces the old `PLUGIN_SERVICES`. A skill with `__init__.py` may declare:

```python
SKILL_SERVICES = {
    "my_service": lambda config, vault: MyServiceInstance(config, vault),
}
```

Bootstrap calls each factory with `(config, vault)` and wires the results into `AppContext.services`. Known services (currently just `db_connections`) also get a dedicated AppContext field.

## Files Moved

| From | To |
|---|---|
| `plugins/chat/` | `skills/chat/` |
| `plugins/terminal/` | `skills/terminal/` |
| `plugins/database/` | `skills/database/` |
| `core/plugin_manager.py` | `core/skill_package_manager.py` |
| `cmd/plugin.py` | `cmd/skill.py` |
| `tests/test_plugin_manager.py` | `tests/test_skill_package_manager.py` |

## Files Removed

- `plugins/__init__.py` — no longer needed
- `core/paths.py: discover_plugins()` — replaced by existing skill discovery
- `core/paths.py: collect_plugin_tcss()` — skill CSS collected by `collect_tcss()` uniformly
- `core/paths.py: _find_tcss(skip_plugins=)` — simplified, no longer skips `plugins/` dir

## Bootstrap Changes

The `_load_plugins()` phase is gone. Replaced by two phases in the skill loading flow:

1. **`_load_skill_components(skills)`** — flat imports from `components/` directories (existing behavior for skills like git)
2. **`_load_skill_init_files(skills)`** — full package-load for skills with `__init__.py`, collecting `SKILL_SERVICES` factories

The ordering matters: components are loaded first (they're simpler), then init files (which may have complex dependencies). Service factories are collected, stored on SkillManager, and called with `(config, vault)` after vault initialization.

## Import Error Isolation

Skills whose `__init__.py` fails to import (missing dependency) are skipped with a warning printed to stderr. The `sys.modules` entry is removed so a retry after installing deps works. This matches the old plugin behavior.

## CSS Collection

Simplified. `collect_tcss()` now walks all three tiers uniformly — including `skills/` directories. No more separate `collect_plugin_tcss()`. Skill CSS (like `skills/chat/chat.tcss`) is collected alongside core UI CSS.

## Legacy Compatibility

`_read_skill_json()` in `SkillPackageManager` checks for both `.skill.json` and legacy `.plugin.json` files, so skills installed before the merge continue to work.

## Tests Added

- 4 tests in `TestInitDirs` — `__init__.py` detection, exclusion of missing/disabled
- 6 tests in `TestSkillServices` — set/get services, reset clears, disabled exclusion, tier override contract
- 2 tests in `TestCollectTcss` — skill CSS collection from flat and nested sub-packages
- 2 tests in `TestSkillLoadErrorIsolation` — broken skill graceful skip, SKILL_SERVICES wiring into context

## Known Issues / Future Work

- Documentation under `skills/workspace_docs/docs/` still references "plugins" in many places — this is a documentation-only task, not functional
- The `design_document.md` Step 23 is marked in-progress; remaining phases can be checked off
- Some pre-existing test failures (Textual MountError, ollama import, icons KeyError, file editor syntax) are unrelated to this refactor