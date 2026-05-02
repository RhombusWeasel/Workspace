# Step 9: Skill System

**Branch:** `step-9-skill-system`  
**Date:** 2026-05-02

---

## Overview

Skill discovery, catalog, and query system. Scans tiered directory trees for
`SKILL.md` files with YAML frontmatter, producing an in-memory catalog used
to inject skill metadata into the agent system prompt and to locate skill
`cmd/` and `tools/` directories at bootstrap time.

Discovery is **explicit** — call `scan()` to rebuild the catalog. No implicit
re-discovery, no file watchers.

---

## Implementation

### `core/skills.py`

#### Data

```python
@dataclass
class Skill:
    name: str
    description: str
    location: str   # full path to SKILL.md
    base_dir: str   # directory containing SKILL.md
    body: str = ""  # markdown body after frontmatter
```

#### Private frontmatter parser: `_parse_skill_md(path) -> dict | None`

Line-by-line delimiter detection with whitespace tolerance:

1. Read file, split into lines
2. Find first line where `line.strip() == "---"` → opening delimiter
3. Find next line where `line.strip() == "---"` → closing delimiter
4. Frontmatter = lines between delimiters
5. Body = lines after closing delimiter, joined and `.strip()`ed
6. Parse frontmatter as `key: value` pairs (split on first `:` only)
7. Requires both `name` and `description` keys — returns `None` otherwise

Handles gracefully:
- No delimiters → `None`
- Only opening, no closing → `None`  
- Extra frontmatter keys → silently ignored
- Whitespace around `---` → tolerated
- Colons in values → everything after first `:` is the value
- Multiple `---` blocks → only first is parsed as frontmatter

#### `SkillManager` class

| Method | Returns | Description |
|---|---|---|
| `scan(tier_paths, enabled=None)` | — | Rebuild catalog from ordered tier paths. Later tiers override. `enabled` is `{name: bool}` dict; missing = enabled. |
| `reset()` | — | Clear all state (test isolation). |
| `list_skills()` | `list[str]` | Sorted list of enabled skill names. |
| `get_skill(name)` | `Skill \| None` | Lookup by name (works even if disabled). |
| `get_skill_body(name)` | `str \| None` | Markdown body (works even if disabled). |
| `get_skill_dirs()` | `list[tuple[str,str]]` | `(name, base_dir)` for enabled skills. |
| `get_skill_cmd_dirs()` | `list[str]` | Paths to existing `cmd/` dirs in enabled skills. |
| `get_skill_tools_dirs()` | `list[str]` | Paths to existing `tools/` dirs in enabled skills. |
| `get_catalog_xml()` | `str` | XML for agent system prompt injection. |

#### Discovery algorithm (`scan()`)

```
for each tier_dir in tier_paths (lowest → highest priority):
    if tier_dir exists and is a directory:
        for each immediate subdirectory entry:
            if entry/SKILL.md exists and is a file:
                parse it
                if valid:
                    discovered[skill.name] = skill   # later tiers replace
```

Only immediate children of each tier are checked (no recursion into nested
directories). This means skill directories are exactly one level deep:
`<tier>/<skill_name>/SKILL.md`.

#### XML catalog format

```xml
<available_skills>
  <skill>
    <name>coding</name>
    <description>A coding assistant skill</description>
    <location>/home/.../skills/coding/SKILL.md</location>
  </skill>
</available_skills>
```

All three fields are XML-escaped via `xml.sax.saxutils.escape()`.

#### Enable/disable logic

- `scan()` accepts an optional `enabled: dict[str, bool]`
- `enabled.get(name, True)` — skills absent from the dict are enabled by default
- `list_skills()`, `get_catalog_xml()`, and helper dir methods only return enabled skills
- `get_skill()` and `get_skill_body()` return data regardless of enable state

#### Singleton

```python
skill_manager = SkillManager()   # module-level instance
```

Each `SkillManager` instance is independent (no shared class-level state). The
module-level `skill_manager` is a convenience; tests create their own instances
or use `skill_manager.reset()`.

---

## Tests

### `tests/test_skills.py` — 47 tests in 11 classes

| Class | Tests | Coverage |
|---|---|---|
| `TestFrontmatterParsing` | 13 | Valid files, bodies, missing fields, no frontmatter, unclosed, whitespace, multiple blocks, colons in values |
| `TestDiscovery` | 8 | Single/multi skill, ignores non-skill dirs, missing/empty tiers, location & base_dir, no deep recursion |
| `TestTierOverride` | 3 | Later overrides earlier, three tiers, unique skills accumulate |
| `TestEnableDisable` | 6 | Exclude/include, defaults, empty dict, disabled still queryable |
| `TestCatalogXml` | 5 | Empty, single, multi, excludes disabled, XML escaping |
| `TestScanBehavior` | 3 | Rebuilds from scratch, no auto-refresh, clears disabled state |
| `TestHelpers` | 6 | get_skill_dirs, get_skill_cmd_dirs, get_skill_tools_dirs, get_skill_body (found + missing), get_skill missing |
| `TestSingleton` | 2 | Independent instances, module-level instance exists |
| `TestReset` | 1 | Clears all skills |

All tests use the `_reset_skill_manager` autouse fixture that resets the module-level
singleton. Tests that create their own `SkillManager()` instances don't need it but
it ensures no cross-test pollution.

Fixture helper `_write_skill_md(path, name, description, body, extra_frontmatter)`
builds SKILL.md files with proper YAML frontmatter formatting.

---

## Design Decisions

1. **Explicit scan, no implicit re-discovery (§ 6.4).** After `scan()`, changing
   files on disk has no effect until `scan()` is called again. No file watchers,
   no background threads.

2. **Line-by-line delimiter detection.** The original codebase split on `\n---`
   which can't handle `  ---  ` (leading/trailing whitespace). The line-by-line
   approach with `line.strip() == "---"` is more robust.

3. **No full YAML dependency.** Simple `key: value` parsing with
   `line.partition(":")` — handles colons in values correctly (e.g.,
   `description: A skill with: colons`) because `partition` splits on first `:`.

4. **Skill body is stripped.** Leading/trailing whitespace (including blank lines
   between `---` and body content) is stripped. Internal whitespace preserved.

5. **Independent instances.** No class-level shared state. Each `SkillManager()`
   instance manages its own catalog. This makes testing simpler — no need to
   worry about module-level singleton contamination when using fresh instances.

6. **One-level scan depth.** Only immediate children of each tier directory are
   checked for `SKILL.md`. Nested directories inside a skill are not scanned as
   separate skills. This matches the expected structure: `<tier>/<skill>/SKILL.md`.

---

## Usage Pattern

```python
from core.paths import resolve
from core.skills import skill_manager
from core.config import cfg

# Bootstrap — scan all tiers with enable/disable from config
tiers = resolve("skills", working_dir)
enabled = cfg.get("skills.enabled", {})
skill_manager.scan(tiers, enabled)

# Inject into agent system prompt
catalog_xml = skill_manager.get_catalog_xml()

# Load skill tools at startup
for tools_dir in skill_manager.get_skill_tools_dirs():
    # import or exec .py files from tools_dir

# Load skill commands at startup
for cmd_dir in skill_manager.get_skill_cmd_dirs():
    # discover CommandBase subclasses from cmd_dir

# Activate a skill (load its body into context)
body = skill_manager.get_skill_body("coding")
```
