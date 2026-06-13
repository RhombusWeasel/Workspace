# Skills System

**File:** `core/skills.py`
**Depends on:** `os`

---

## Purpose

Skills are the sole extension mechanism in Workspace.  A skill is a directory
containing a `SKILL.md` manifest — a format compatible with the Anthropic
skill specification (ClaudeCode, Codex).  Skills are discovered via a
3-tier directory scan (bundled → user → project) and can provide:

- **Agent knowledge** — markdown instructions the LLM reads via
  `activate_skill`
- **UI registrations** — sidebar panels, event handlers, leader chords
- **Agent tools** — Python functions the LLM can invoke
- **Slash commands** — `/command` entries the user can type
- **AppContext services** — service factories wired into the app context

A skill can be purely agent-facing (knowledge only), purely app-facing
(UI only), or both.  The skill system unifies what were formerly separate
"skills" and "plugins" — they share the same manifest format and discovery
mechanism.

---

## Architecture

```
3-tier directory scan
    │
    ├── {workspace_dir}/skills/          ← bundled (tier 1)
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

Optional frontmatter fields:

| Field | Description |
|---|---|
| `requirements` | YAML list of pip-format package specifiers (for installable skills) |

---

## Skill Profiles

There are three common skill profiles:

### Ecosystem skill (Anthropic spec)

No `__init__.py`.  Just SKILL.md + optional `scripts/`.  These skills
are compatible with any tool that follows the Anthropic skill
specification.

```
my_skill/
├── SKILL.md
└── scripts/
    └── deploy.py
```

### UI skill

Has `__init__.py` as the Python entry point.  Registers sidebar panels,
event handlers, tools, commands, and services.  Gets full `importlib`
load treatment with `__path__`/`__package__` handling for nested
sub-packages.

```
my_skill/
├── SKILL.md
├── __init__.py
├── core/
│   ├── __init__.py
│   └── connections.py
├── services.py          # SKILL_SERVICES factory
└── my_skill.tcss
```

### Hybrid skill

Has agent knowledge (SKILL.md body) plus flat UI components.  Uses
`components/` directory for sidebar panels, handlers, etc.

```
my_skill/
├── SKILL.md              # Body = agent knowledge
├── scripts/               # Agent-runnable scripts
├── components/
│   └── panel.py           # @register_sidebar_tab, @register_handler
├── tools/
│   └── my_tool.py         # @register_tool
└── my_skill.tcss
```

---

## The `__init__.py` Gate

`__init__.py` is **optional**.  Its presence determines how the skill
is loaded at bootstrap:

| Has `__init__.py`? | Loading | Used for |
|---|---|---|
| ❌ | Discovery only — SKILL.md body available to agent, scripts runnable | Ecosystem skills, pure knowledge skills |
| ✅ | Full `importlib` load — `__path__`/`__package__` set, nested sub-imports work | UI skills with complex package structures |

Skills without `__init__.py` can still have Python code in `components/`,
`tools/`, and `cmd/` directories — those are auto-imported as flat files
by the bootstrap loader.

---

## SkillManager API

### `scan(tier_paths, enabled=None)`

Rebuild the skill catalog from the given tier paths.  Call this once at
bootstrap.

```python
skill_manager.scan(
    tier_paths=[
        "/opt/workspace/skills",
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

### `get_skill_init_dirs() → list[str]`

Return base directories of enabled skills that contain `__init__.py`.
These are loaded at bootstrap with full `importlib` treatment.

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

### `get_skill_services() → dict`

Return collected `SKILL_SERVICES` from loaded skill modules.  Services are
populated by bootstrap's `_load_skill_init_files()` phase.

### `set_skill_services(services)`

Store service factories collected during bootstrap loading.  Called by
`Bootstrap._load_skill_init_files()` after each skill's `__init__.py` is
loaded.

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

This returns **bare XML** — no code fences.  For the wrapped version
suitable for injection into LLM system prompts, use `render_selected()`.

### `render_selected(skill_names) → str`

Render the XML catalog for a subset of skills, wrapped in triple-backtick
`xml` code fences.  This is the preferred method for injecting skill
catalogs into agent system prompts, as the code fences help LLMs
interpret the XML correctly.

```python
xml = skill_manager.render_selected(["chat", "git", "terminal"])
# Returns:
# ```xml
# <available_skills>
#   <skill>...
# </available_skills>
# ```
```

If `skill_names` is empty or `None`, renders all enabled skills.

### `reset()`

Clear all skills, enabled state, and services.  Use between tests.

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

### 3. (Optional) Add `__init__.py` for UI skills

If your skill registers sidebar panels, event handlers, or other Python
components that need to import each other, add `__init__.py`:

```python
# ~/.agents/skills/my_skill/__init__.py
"""My Skill — UI extension for Workspace."""

from skills.my_skill.handlers import register_handlers  # noqa: F401
from skills.my_skill.services import SKILL_SERVICES       # noqa: F401

__all__ = ["SKILL_SERVICES"]
```

### 4. (Optional) Add tools

```
my_skill/
├── SKILL.md
└── tools/
    └── my_tool.py       ← @register_tool decorators, auto-discovered
```

### 5. (Optional) Add commands

```
my_skill/
├── SKILL.md
└── cmd/
    └── mycommand.py     ← @register_command decorators, auto-discovered
```

### 6. (Optional) Add UI components

```
my_skill/
├── SKILL.md
├── components/
│   └── my_panel.py   ← @register_sidebar_tab, @register_handler, etc.
└── my_skill.tcss     ← Widget styles (auto-collected)
```

Components directories are auto-imported by the bootstrap loader, enabling
skills to register sidebar panels, event handlers, leader chords, and config
defaults — no `__init__.py` needed for flat component files.

### 7. Restart Workspace

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

## SKILL_SERVICES Convention

Skills with `__init__.py` may declare a `SKILL_SERVICES` dict mapping
service names to factory callables.  Bootstrap calls each factory with
`(config, vault)` and wires the results into `AppContext`:

```python
# skills/my_skill/__init__.py
from skills.my_skill.services import create_my_service

SKILL_SERVICES = {
    "my_service": create_my_service,
}
```

```python
# skills/my_skill/services.py
from core.config import Config
from core.vault import VaultManager

def create_my_service(config: Config, vault: VaultManager):
    return MyService(config, vault)
```

Other components access the service via `ctx.services["my_service"]` or,
for known services like `db_connections`, via `ctx.db_connections`.

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

1. **Unified skill concept** — Skills are the sole extension mechanism.
   The former "plugins" concept has been merged into skills.  A skill with
   `__init__.py` gets the same treatment plugins used to get; a skill
   without `__init__.py` works as an ecosystem-compatible knowledge bundle.

2. **`__init__.py` is optional** — This ensures compatibility with the
   Anthropic skill specification.  Ecosystem skills (ClaudeCode, Codex)
   don't have `__init__.py` — they're just SKILL.md + scripts.  UI skills
   add `__init__.py` when they need complex Python package structures.

3. **Explicit scan, no auto-reload** — `scan()` is called once at
   bootstrap.  Adding a skill requires a restart.  This avoids complexity
   from filesystem watchers and ensures the catalog is stable.

4. **XML catalog for LLM** — The catalog XML is injected into the agent's
   system prompt so the LLM knows which skills exist.  This is more
   structured than free-form text and easier for the LLM to parse.

5. **Skills can contain code** — A skill's `tools/`, `cmd/`, and
   `components/` directories are auto-imported by the bootstrap loader.
  This lets a skill provide both knowledge (markdown body) and tools
  (Python code) as well as UI components (sidebar panels, handlers, etc.).

6. **Enabled/disabled in config** — The `skills.enabled` config key maps
  skill names to booleans.  Missing entries default to `True` (enabled).