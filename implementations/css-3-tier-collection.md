# CSS 3-Tier Collection + DEFAULT_CSS Extraction

## Commit
`1440642` — `feat: 3-tier CSS collection + extract inline DEFAULT_CSS to .tcss files`

## Overview

This change implements automatic 3-tier discovery of `.tcss` (Textual CSS) files for the Cody application, replacing the previous single hardcoded `CSS_PATH` and extracting all inline `DEFAULT_CSS` blocks into dedicated files.

---

## Architecture

### CSS Discovery Flow

```
Bootstrap.run()
  └─ _collect_css()  [Phase 8]
       └─ paths.collect_tcss(working_dir)
            ├─ resolve("", working_dir)   → [cody_dir, ~/.agents/, wd/.agents/]
            ├─ _find_tcss(cody_dir)       → [ui/.../*.tcss, ...]
            ├─ _find_tcss(agents_dir)     → [~/.agents/.../*.tcss, ...]
            └─ _find_tcss(wd/.agents)      → [project/.agents/.../*.tcss, ...]
  └─ AppContext(css_paths=...)

CodyApp.__init__()
  └─ self.CSS_PATH = context.css_paths     # set before super().__init__()
```

### Tier Priority

Three tiers, loaded in order by Textual:
1. **Cody bundled** (lowest priority) — `cody_dir()` walks the installation for `.tcss`
2. **User overrides** — `~/.agents/` walked for `.tcss`
3. **Project overrides** (highest priority) — `{wd}/.agents/` walked for `.tcss`

Textual loads CSS files in list order; later files' rules take precedence.

---

## Key Files

### `core/paths.py`

Two new functions:

```python
def collect_tcss(working_dir: str) -> list[str]:
    """Collect .tcss files across all three tiers in priority order."""
    roots = resolve("", working_dir)
    paths = []
    for root in roots:
        paths.extend(_find_tcss(root))
    return paths

def _find_tcss(root: str) -> list[str]:
    """Walk root for .tcss files, sorted for determinism."""
    if not os.path.isdir(root):
        return []
    result = []
    for dirpath, _, filenames in os.walk(root):
        for f in sorted(filenames):
            if f.endswith(".tcss"):
                result.append(os.path.join(dirpath, f))
    return result
```

`_find_tcss` is module-private but importable for testing.

### `context.py` — AppContext

Added field: `css_paths: list[str] = field(default_factory=list)`

### `bootstrap.py` — Bootstrap

Added `_collect_css()` method (Phase 8) that calls `paths.collect_tcss(self.wd)` and passes the result to `AppContext`.

### `main.py` — CodyApp

- Class-level `CSS_PATH = []` (empty default)
- `__init__` sets `self.CSS_PATH = context.css_paths` **before** `super().__init__()` — this is critical because Textual reads `CSS_PATH` during `App.__init__()`.

---

## CSS File Inventory

| File | Origin |
|---|---|
| `ui/workspace/workspace.tcss` | Renamed from `workspace.css` |
| `ui/tree/tree.tcss` | Renamed from `tree.css` |
| `ui/tree/tree_row.tcss` | Extracted from `TreeRow.DEFAULT_CSS` + `ActionRow.DEFAULT_CSS` |
| `ui/sidebar/sidebar.tcss` | Extracted from `Sidebar.DEFAULT_CSS` + `SidebarContainer.DEFAULT_CSS` |
| `ui/sidebar/panels/vault_panel.tcss` | Extracted from `VaultPanel.DEFAULT_CSS` |
| `ui/sidebar/panels/chat_panel.tcss` | Extracted from `ChatPanel.DEFAULT_CSS` |

**Zero `DEFAULT_CSS` remain in project Python code.**

---

## Testing

### Test file: `tests/test_paths.py`

`TestCollectTcss` class with 6 tests:
- `test_returns_list` — basic type check
- `test_empty_when_no_tcss_files` — all tiers empty → empty list
- `test_collects_from_cody_tier` — only cody has files
- `test_collects_from_all_three_tiers_in_order` — verifies cody < agents < wd ordering
- `test_skips_missing_tier_directories` — missing dirs don't error
- `test_only_finds_tcss_extension` — `.css`, `.md`, `.py` ignored

### Test file: `tests/test_bootstrap.py`

Updated `test_returns_app_context` to:
- Set up `.tcss` files in mock cody tier
- Monkeypatch `paths.cody_dir` and `paths.agents_dir`
- Assert `ctx.css_paths` is a non-empty list containing expected files

---

## For Future Agents

### Adding a new widget with CSS

1. Create `ui/path/to/widget_name.tcss` in the same directory as the widget `.py` file.
2. Use `DEFAULT_CSS` inline during development if convenient, but extract to `.tcss` before merging.
3. Do NOT set class-level `CSS_PATH` on individual widgets — the app-level `collect_tcss` handles discovery.

### Adding user-level CSS overrides

Users place `.tcss` files in `~/.agents/` (any subdirectory). They're picked up automatically.

### Adding project-level CSS overrides

Users place `.tcss` files in `{project}/.agents/`. They override both bundled and user-level CSS.

### Modifying CSS discovery

The entry point is `paths.collect_tcss(working_dir)`. To change what gets discovered, modify `_find_tcss` or add filtering there.

### Running CSS-related tests

```bash
uv run pytest tests/test_paths.py -k "CollectTcss" -v
```
