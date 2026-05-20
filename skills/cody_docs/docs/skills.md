# Skills System

**File:** `core/skills.py`
**Depends on:** `os`

---

## Purpose

Skills are discoverable bundles of functionality described by `SKILL.md`
files with YAML frontmatter.  They are discovered via a 3-tier directory
scan (bundled → user → project) and queried at runtime to build an XML
catalog for the LLM's system prompt.

Skills and plugins share the `SKILL.md` manifest format, but they differ
in intent:

- **Skills** are knowledge bundles — markdown instructions that the LLM
  reads (via the `activate_skill` tool) to learn how to perform tasks.
- **Plugins** are code bundles — Python packages that register sidebar
  tabs, event handlers, tools, commands, and services at import time.

A skill MAY contain Python code (tools, commands, handlers).  A plugin
MAY contain documentation in its `SKILL.md` body.  The distinction is
about primary purpose.

---

## Architecture

```
3-tier directory scan
    │
    ├── {cody_dir}/skills/          ← bundled (tier 1)
    ├── ~/.agents/skills/           ← user (tier 2)
    └── {wd}/.agents/skills/        ← project (tier 3) — wins
    │
    ▼
SkillManager.scan(tier_paths, enabled_map)
    │
    ▼
_skills: {name → Skill}     ← later tiers override same-named skills
_enabled: set[str]          ← skills not explicitly disabled in config
```

---

## SKILL.md Format

```markdown
---
name: my_skill
description: Short description shown in catalog
---

# My Skill

Detailed markdown instructions that the LLM reads when the skill
is activated.  This body is returned by the `activate_skill` tool.
```

The YAML frontmatter requires `name` and `description`.  The body after
the closing `---` is the skill's documentation / instructions.

---

## SkillManager API

### `scan(tier_paths, enabled=None)`

Rebuild the skill catalog from the given tier paths.  Call this once at
bootstrap.

```python
skill_manager.scan(
    tier_paths=[
        "/opt/cody/skills",
        "/home/alice/.agents/skills",
        "/project/.agents/skills",
    ],
    enabled={"my_skill": True, "old_skill": False},
)
```

`enabled` is a `name → bool` map.  Skills missing from the map default
to enabled.

### `list_skills() → list[str]`

Return sorted list of enabled skill names.

### `get_skill(name) → Skill | None`

Return a skill by name (even if disabled), or `None`.

### `get_skill_body(name) → str | None`

Return the markdown body for a skill (even if disabled), or `None`.

### `get_skill_dirs() → list[tuple[str, str]]`

Return `(name, base_dir)` pairs for enabled skills.  Useful for finding
a skill's root directory.

### `get_skill_cmd_dirs() → list[str]`

Return paths to `cmd/` subdirectories that exist inside enabled skills.

### `get_skill_tools_dirs() → list[str]`

Return paths to `tools/` subdirectories that exist inside enabled skills.

### `get_skill_components_dirs() → list[str]`

Return paths to `components/` subdirectories that exist inside enabled skills.
Components directories contain Python modules that register UI elements
(sidebar panels, event handlers, leader chords, config defaults) via the
usual decorator pattern.  They are auto-imported by the bootstrap loader,
exactly like `tools/` and `cmd/` directories.

### `get_catalog_xml() → str`

Return an XML string listing enabled skills for the agent's system prompt:

```xml
<available_skills>
  <skill>
    <name>my_skill</name>
    <description>Short description</description>
    <location>/path/to/SKILL.md</location>
  </skill>
</available_skills>
```

### `reset()`

Clear all skills and enabled state.  Use between tests.

---

## Skill Data

```python
@dataclass
class Skill:
    name: str           # From SKILL.md frontmatter
    description: str    # From SKILL.md frontmatter
    location: str        # Absolute path to SKILL.md
    base_dir: str        # Directory containing SKILL.md
    body: str = ""       # Markdown content after frontmatter
```

---

## Skills vs Plugins

| Aspect | Skill | Plugin |
|---|---|---|
| Location | `skills/` directories | `plugins/` directories |
| Primary purpose | Knowledge for the LLM | Code registrations (UI, handlers, tools) |
| Manifest | `SKILL.md` with `name` + `description` | `SKILL.md` with `name` + `description` + optional `requirements` |
| Code | Optional (`tools/`, `cmd/`, `components/` subdirs) | Required (`__init__.py` entry point) |
| Loaded by | `SkillManager.scan()` + bootstrap auto-import | `Bootstrap._load_plugins()` |
| LLM access | `activate_skill` tool reads body | Indirect (via registered tools/handlers) |
| Enable/disable | Config `skills.enabled` | Config `plugins.enabled` |
| Tier override | Same 3-tier, later wins | Same 3-tier, later wins |

A single directory can serve as both a skill and a plugin — place it in
`plugins/` and give it an `__init__.py` to trigger registrations at load
time.  Its `SKILL.md` body is still available via `activate_skill` if
needed.

---

## Creating a Skill

### 1. Create the directory

```bash
mkdir -p ~/.agents/skills/my_skill
```

### 2. Write SKILL.md

```bash
cat > ~/.agents/skills/my_skill/SKILL.md << 'EOF'
---
name: my_skill
description: Instructions for doing X with the project
---

# My Skill

Detailed instructions the LLM should follow when this skill is activated.
Include examples, constraints, and step-by-step procedures.
EOF
```

### 3. (Optional) Add tools

```
my_skill/
├── SKILL.md
└── tools/
    └── my_tool.py       ← @register_tool decorators, auto-discovered
```

### 4. (Optional) Add commands

```
my_skill/
├── SKILL.md
└── cmd/
    └── mycommand.py     ← @register_command decorators, auto-discovered
```

### 5. (Optional) Add UI components

```
my_skill/
├── SKILL.md
├── components/
│   └── my_panel.py   ← @register_sidebar_tab, @register_handler, etc.
└── my_skill.tcss     ← Widget styles (auto-collected)
```

Components directories are auto-imported by the bootstrap loader, enabling
skills to register sidebar panels, event handlers, leader chords, and config
defaults using the same decorator pattern as plugins — no `__init__.py` needed.

### 6. Restart Cody

Skills are discovered at startup.  Restart to pick up new skills.

---

## The `activate_skill` Tool

The built-in `activate_skill` tool lets the LLM read a skill's full body:

```
User: "Help me deploy to staging"
LLM: *calls activate_skill(skill_name="deployment")*
LLM: *reads skill body, follows deployment instructions*
```

This means skills are pulled into context on demand — only when the LLM
determines they're relevant.  The skill catalog XML (from
`get_catalog_xml()`) is always in the system prompt, giving the LLM a
menu of available skills to choose from.

---

## Testing

```python
from core.skills import SkillManager, skill_manager

def test_skill_discovery(tmp_path):
    # Create a skill on disk
    skill_dir = tmp_path / "my_skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: my_skill\ndescription: Test skill\n---\n\n# Body\n"
    )

    mgr = SkillManager()
    mgr.scan([str(tmp_path)])

    assert "my_skill" in mgr.list_skills()
    assert mgr.get_skill_body("my_skill") == "# Body"
```

---

## Design Decisions

1. **SKILL.md as the manifest** — Reuses the same format as plugins.
  Skills and plugins are discovered by the same scanner (looking for
  `SKILL.md` files).

2. **Explicit scan, no auto-reload** — `scan()` is called once at
  bootstrap.  Adding a skill requires a restart.  This avoids complexity
  from filesystem watchers and ensures the catalog is stable.

3. **XML catalog for LLM** — The catalog XML is injected into the agent's
  system prompt so the LLM knows which skills exist.  This is more
  structured than free-form text and easier for the LLM to parse.

4. **Skills can contain code** — A skill's `tools/`, `cmd/`, and
  `components/` directories are auto-imported by the bootstrap loader.
  This lets a skill provide both knowledge (markdown body) and tools
  (Python code) as well as UI components (sidebar panels, handlers, etc.).

5. **Enabled/disabled in config** — The `skills.enabled` config key maps
  skill names to booleans.  Missing entries default to `True` (enabled).