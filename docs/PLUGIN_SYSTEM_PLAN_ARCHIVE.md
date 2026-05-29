# Cody Plugin System — Implementation Plan

## Overview

This document captures the plugin system design decisions, what has been
implemented, and what remains.  It is intended as an action reference for
future development sprints.

---

## What Has Been Implemented

### 1. 3-Tier Plugin Discovery (`core/paths.py`)

Plugins are discovered across three tiers in order of increasing precedence:

| Tier | Path | Scope |
|---|---|---|
| 1 — Bundled | `{cody_dir}/plugins/` | Ships with Cody |
| 2 — Global | `~/.agents/plugins/` | Per-user overrides |
| 3 — Project | `{wd}/.agents/plugins/` | Per-project overrides |

Later tiers override earlier tiers for same-named plugins.

**Status:** ✅ Complete and tested.

### 2. Plugin Loading (`bootstrap.py`)

- `sys.path` is guaranteed to include the Cody project root before any
  plugins load, so `from core.config import Config` works from any tier.
- Each plugin's `__init__.py` is loaded via `importlib.util.spec_from_file_location`
  with `__path__` and `__package__` set correctly, so sub-imports resolve
  from the plugin's own directory regardless of which tier it lives in.
- A synthetic `plugins` package is registered in `sys.modules` so that
  `from plugins.database.core import X` works.

**Status:** ✅ Complete and tested.

### 3. Provider Auto-Discovery (`plugins/database/core/providers/`)

- `SQLiteProvider` has been extracted from `db_connections.py` into its own
  file (`plugins/database/core/providers/sqlite.py`).
- `plugins/database/core/providers/__init__.py` auto-discovers all `.py`
  files in the directory and imports them, triggering `@register_provider`
  decorators.
- `db_connections.py` imports the providers sub-package at the bottom, which
  fires the auto-discovery.
- `connection_form.py` no longer imports `SQLiteProvider` directly — it uses
  `get_provider()` with a `None` guard.

**Status:** ✅ Complete and tested (49 tests pass).

### 4. Plugin Manager (`core/plugin_manager.py`)

- `PluginManager` class with install, update, remove, list operations.
- Plugins are installed from **tagged git releases** — never from a live branch.
- `.git/` is stripped after cloning (no submodule issues).
- Install metadata stored in `.plugin.json` inside each plugin directory.
- Config mirrored to `plugins.installed` and `plugins.enabled` (visible in
  ConfigPanel).
- `PluginManager` accepts `agents_dir` and `cody_dir` constructor params
  for testability.

**Status:** ✅ Complete and tested (25 tests pass).

### 5. Slash Command (`cmd/plugin.py`)

```
/plugin install <url>                  Global, latest tag
/plugin install <url> --version X      Global, specific tag
/plugin install <url> --local          Project-local, latest tag
/plugin install <url> --subdir D       Monorepo subpath
/plugin update <name>                  Update to latest tag
/plugin update <name> --version X      Update to specific tag
/plugin update --all                   Update all managed plugins
/plugin remove <name>                   Remove global plugin
/plugin remove <name> --local          Remove project-local plugin
/plugin list                            List all discovered plugins
```

**Status:** ✅ Command registered, subcommands implemented.

### 6. Documentation

- `skills/cody_docs/docs/plugins.md` — Full plugin authoring guide including
  the auto-discovery provider pattern and git installation flow.
- `core/paths.py` — Expanded module and `discover_plugins` docstrings.
- `design_document.md` — Updated §2.2.I, §6.5, §6.6, directory tree, and
  plugin providers structure.

**Status:** ✅ Complete.

---

## What Remains

### 7. Integration Testing — Plugin Install End-to-End

The unit tests verify `PluginManager` logic in isolation.  What's missing is
an end-to-end test that runs through the full bootstrap cycle with a plugin
installed via the manager, verifying that:

- The plugin is discovered by `discover_plugins()`
- Its `__init__.py` is loaded and side-effects fire
- Its `PLUGIN_SERVICES` are collected and injected into `AppContext`
- The `/plugin list` output is correct

**Action:** Create `tests/test_plugin_integration.py` with a test that
installs a plugin to a temp directory, then runs bootstrap against it.

### 8. Hot-Reload After Install

Currently, installing a plugin requires restarting Cody for it to take
effect.  This is acceptable for V1 but should be improved.

**Action:** Add a mechanism to re-scan plugins without restarting:

- `PluginManager.install()` could post a `CodyEvent("plugins.changed")`
  after a successful install.
- Bootstrap could expose a `rescan()` method that re-runs `_load_plugins()`
  without re-initialising the entire `AppContext`.
- The app could listen for `"plugins.changed"` and call `rescan()`.

### 9. Private Git Repositories

Currently, `git clone` uses whatever credentials the user has configured
(SSH keys, credential helpers, etc.).  This should work for most cases but
needs:

- Clear error messages when auth fails
- Documentation on setting up SSH keys or credential helpers
- Consider `--branch main` fallback when no tags exist (with a warning)

**Action:** Test with private GitHub repos and improve error messages in
`PluginError`.

### 10. Archive-Based Download (Future Optimization)

Currently, plugins are installed via `git clone --depth 1 --branch <tag>`
followed by `.git/` removal.  An optimization would be to download the
release tarball directly from the hosting platform's API (GitHub, GitLab,
etc.), which is faster and doesn't require git on the machine.

**Action:** Implement a `DownloadStrategy` abstraction:

```python
class DownloadStrategy(ABC):
    @abstractmethod
    def download(self, url: str, version: str, dest: str) -> None: ...

class GitCloneStrategy(DownloadStrategy): ...     # current approach
class GitHubArchiveStrategy(DownloadStrategy): ... # future: tarball download
```

Auto-detect the hosting platform from the URL and use the appropriate
strategy.

### 11. Plugin Version Pinning in Config

Currently, `plugins.installed.<name>.version` records what's installed but
doesn't prevent upgrades.  A future enhancement would allow pinning:

```json
"plugins": {
    "enabled": { "postgres": true },
    "pinned": { "postgres": "v0.3.1" }
}
```

Pinned plugins skip `update --all` and warn on `update <name>`.

**Action:** Add `plugins.pinned` to config defaults and check it in
`PluginManager.update()`.

### 12. Plugin Dependency Resolution (Future)

The current system has no dependency tracking between plugins.  If a
`postgres` plugin depends on the `database` plugin's `DBProvider` ABC,
it just imports it — and if `database` isn't installed, the import fails
at load time.

**Action:** Add optional `requires` field to `SKILL.md` frontmatter:

```yaml
---
name: postgres
description: PostgreSQL provider
requires:
  - database
---
```

During bootstrap, check that all required plugins are present before
loading.  Emit clear error messages for missing dependencies.

### 13. Plugin Uninstall Safety

`PluginManager.remove()` deletes the plugin directory immediately.  If a
plugin is currently loaded (its `__init__.py` has been executed), removing
it from disk won't unload it from `sys.modules`.

**Action:** Add a `--force` flag and a confirmation prompt (via
`ConfirmModal`).  Consider warning if the plugin is currently loaded.

### 14. Update Diff/Changelog (Nice-to-Have)

When updating a plugin, show the user what changed between versions.

**Action:** Fetch release notes from the GitHub API (or just the tag
messages) and display them before confirming the update.

---

## File Inventory

### New Files

| File | Purpose |
|---|---|
| `core/plugin_manager.py` | PluginManager, PluginInfo, PluginError |
| `cmd/plugin.py` | `/plugin` slash command |
| `plugins/database/core/providers/__init__.py` | Auto-discovery of providers |
| `plugins/database/core/providers/sqlite.py` | SQLiteProvider (extracted) |
| `skills/cody_docs/docs/plugins.md` | Plugin authoring documentation |
| `tests/test_plugin_manager.py` | 25 tests for PluginManager |

### Modified Files

| File | Change |
|---|---|
| `core/paths.py` | Expanded docstrings for plugin discovery |
| `plugins/database/core/db_connections.py` | Removed SQLiteProvider, added provider auto-import |
| `plugins/database/core/__init__.py` | Updated docstring for providers sub-package |
| `plugins/database/connection_form.py` | Removed SQLiteProvider fallback, uses None guard |
| `plugins/database/tests/test_db_connections.py` | Updated SQLiteProvider import path |
| `bootstrap.py` | Added `_ensure_project_on_path()`, fixed `__path__`/`__package__` for plugins |
| `design_document.md` | Updated plugin system sections |

---

## Architecture Diagram

```
/plugin install https://github.com/user/cody-postgres
    │
    ├── git ls-remote --tags <url>
    │   └── Pick latest semver tag (e.g. v0.3.1)
    │
    ├── git clone --depth 1 --branch v0.3.1 <url> /tmp/cody_plugin_xxx
    │
    ├── Read SKILL.md → name: "postgres"
    │
    ├── rm -rf /tmp/cody_plugin_xxx/.git/
    │
    ├── mv /tmp/cody_plugin_xxx ~/.agents/plugins/postgres/
    │
    ├── Write ~/.agents/plugins/postgres/.plugin.json
    │   └── {"source": "...", "version": "v0.3.1", "installed_at": "..."}
    │
    └── Config: plugins.installed.postgres = {...}
              plugins.enabled.postgres = true
```

```
Bootstrap plugin loading:
    │
    ├── _ensure_project_on_path()          ← adds cody_dir to sys.path
    │
    ├── Register synthetic 'plugins'       ← sys.modules["plugins"] + __path__
    │   package in sys.modules
    │
    └── For each discovered plugin dir:
        │
        ├── spec_from_file_location()      ← loads __init__.py
        ├── Set __path__ = [plugin_dir]    ← sub-imports resolve here
        ├── Set __package__ = "plugins.name"
        │
        ├── spec.loader.exec_module()      ← triggers @register_* decorators
        │
        └── Collect PLUGIN_SERVICES        ← factories called with (config, vault)
```

---

## Config Schema

```json
{
    "plugins": {
        "enabled": {
            "database": true,
            "postgres": true
        },
        "installed": {
            "postgres": {
                "source": "https://github.com/user/cody-postgres",
                "version": "v0.3.1",
                "installed_at": "2025-05-21T10:30:00+00:00"
            }
        }
    }
}
```

- `plugins.enabled`: Mirrors `skills.enabled`.  Empty dict = all enabled.
  Set `"database": false` to disable a bundled plugin.
- `plugins.installed`: Mirrors `.plugin.json` metadata.  Written on
  install/update, removed on remove.

---

## `.plugin.json` Format

```json
{
    "source": "https://github.com/user/cody-postgres",
    "version": "v0.3.1",
    "installed_at": "2025-05-21T10:30:00+00:00"
}
```

Lives inside each installed plugin directory.  Deleted with the plugin.
Not present for bundled or manually-created plugins.

---

## SKILL.md Extended Format

Current required fields:
```yaml
---
name: my_plugin
description: What the plugin does
---
```

Future optional fields (not yet implemented):
```yaml
---
name: my_plugin
description: What the plugin does
version: 0.3.1
requires:
  - database
---
```

The `version` and `requires` fields are parsed by `_parse_skill_md()` but
not yet acted on during bootstrap.

---

## Test Inventory

| Test file | Area | Count |
|---|---|---|
| `tests/test_paths.py` | 3-tier resolution, plugin discovery | 26 |
| `tests/test_skills.py` | Skill discovery, catalog | 39 |
| `tests/test_tools.py` | Tool registry | 27 |
| `tests/test_config.py` | Config get/set/defaults | 23 |
| `tests/test_events.py` | Event dispatch | 13 |
| `tests/test_plugin_manager.py` | PluginManager, install/update/remove/list | 25 |
| `tests/test_db_connections.py` | Connection manager, providers, pagination | 49 |

**Total: ~202 tests across these areas** (plus UI and integration tests not
listed here).