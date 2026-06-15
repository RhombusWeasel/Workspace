# Creating a Skill — Quick Reference

This guide covers the essential steps for creating a new Workspace skill.
For detailed API docs, see the dedicated documentation files linked below.

---

## Skill Anatomy

### Minimal skill (ecosystem compatible)

```
my_skill/
├── SKILL.md              # Required — manifest with name + description
└── scripts/               # Optional — run via run_skill tool
    └── deploy.py
```

### UI skill

```
my_skill/
├── SKILL.md
├── __init__.py            # Entry point — imports modules with @register_*
├── core/
│   ├── __init__.py
│   └── connections.py
├── services.py           # SKILL_SERVICES factory
└── my_skill.tcss
```

### Hybrid skill (knowledge + UI)

```
my_skill/
├── SKILL.md              # Body = agent knowledge
├── scripts/
├── components/           # Auto-imported by bootstrap
│   └── panel.py          # @register_sidebar_tab, @register_handler
├── tools/                # Auto-imported by bootstrap
│   └── my_tool.py        # @register_tool
└── my_skill.tcss
```

---

## Steps

### 1. Create the directory

```bash
mkdir -p ~/.agents/skills/my_skill
```

### 2. Write SKILL.md

```markdown
---
name: my_skill
description: Short description shown in the skill catalog
requirements:        # Optional
  - requests>=2.28
---

# My Skill

Detailed instructions the LLM should follow when this skill is activated.
```

| Field | Required | Description |
|---|---|---|
| `name` | **Yes** | Unique skill name |
| `description` | **Yes** | Short description (shown in catalog) |
| `requirements` | No | YAML list of pip-format package specifiers |

### 3. Decide on `__init__.py`

| Skill type | Need `__init__.py`? | Why |
|---|---|---|
| Knowledge only | ❌ | No Python code needs to run |
| Flat UI components | ❌ | `components/`, `tools/`, `cmd/` are auto-imported |
| Complex UI with sub-packages | ✅ | Needed for `__path__`/`__package__` resolution |
| Skills with `SKILL_SERVICES` | ✅ | Services must be declared in a module-level dict |

If you add `__init__.py`, it must import all modules with `@register_*` decorators:

```python
# skills/my_skill/__init__.py
from skills.my_skill.handlers import register_handlers  # noqa: F401
from skills.my_skill.services import SKILL_SERVICES       # noqa: F401
__all__ = ["SKILL_SERVICES"]
```

### 4. Register components

Each registration mechanism has its own dedicated documentation:

| What | Module | Decorator/Function | See |
|---|---|---|---|
| Sidebar panel | `ui.sidebar.registry` | `@register_sidebar_tab()` | [sidebar.md](sidebar.md) |
| Event handler | `core.events` | `@register_handler()` | [events.md](events.md) |
| LLM tool | `core.tools` | `@register_tool()` | [tools.md](tools.md) |
| Slash command | `core.commands` | `@register_command()` | [commands.md](commands.md) |
| Leader chord | `core.leader` | `register_action()` / `register_submenu()` | [leader.md](leader.md) |
| Config defaults | `core.config` | `register_defaults()` | [config.md](config.md) |
| Workspace tab | `ui.workspace.tabs` | `TabState` + `content_factory` | [workspace_tabs.md](workspace_tabs.md) |
| Session handler | `core.session` | `register_tab_type(TabTypeHandler(...))` | [session.md](session.md) |
| Skill services | `__init__.py` | `SKILL_SERVICES` dict | [skills.md](skills.md) |
| Terminal shortcut | `core.terminal_passthrough` | `register_terminal_passthrough()` | — |

### 5. Add CSS (optional)

Create a `.tcss` file in the skill directory. Collected automatically by `collect_tcss()`.

### 6. Restart Workspace

Skills are discovered at startup. Restart to pick up new skills.

---

## Advanced Patterns

### Auto-Discovery Provider Pattern

For skills with multiple backends (e.g. database providers):

1. Define an ABC and `@register_provider` decorator in your core module
2. Create a `providers/` sub-package that auto-imports all `.py` files
3. Each provider self-registers via the decorator at import time

See [skills.md](skills.md) for the full pattern.

### Lazy Imports for Optional Dependencies

```python
@register_tool(name="my_tool", tags=["my_skill"], ...)
async def my_tool(query: str) -> str:
    import heavy_dependency  # only imported when the tool is called
    return heavy_dependency.search(query)
```

### Accessing AppContext from Widgets

```python
class MyWidget(Widget):
    def on_mount(self) -> None:
        ctx = self.app.context
        theme = ctx.config.get("ui.theme", "default")
```

### Pushing Modals from Sync Handlers

Event handlers are synchronous, but modals require `await`. Use `app.run_worker()`:

```python
@register_handler("my_skill.prompt")
def _on_prompt(data: dict, ctx: AppContext) -> None:
    app = ctx.app
    if app is None:
        return

    async def do_prompt() -> None:
        from ui.widgets.input_modal import InputModal
        result = await app.push_screen_wait(InputModal("Enter value:"))
        if result is not None:
            ctx.config.set("my_skill.value", result)
            ctx.config.save()

    app.run_worker(do_prompt())
```

### Disabling a Bundled Skill

Create an empty override in a higher tier, or set `"skill_name": false` in config under `skills.enabled`.

---

## Troubleshooting

| Problem | Solution |
|---|---|
| Skill not discovered | Ensure `SKILL.md` exists with valid YAML frontmatter (`name` + `description` required) |
| Import errors | Use fully-qualified imports (`from core.events import ...`). Project root is on `sys.path`. |
| Handlers not firing | Modules with `@register_handler` must be imported by `__init__.py` or live in `components/` |
| Tool not showing up | Modules with `@register_tool` must be imported by `__init__.py` or live in `tools/` |
| Missing dependency | Add to `requirements:` in SKILL.md, or use lazy imports inside functions |
| CSS not applied | Check file extension is `.tcss` (not `.css`). Must be in skill directory. |
| Leader chord conflicts | Registry detects conflicts at registration time. Choose a different key path. |

---

## Quick Reference: AppContext Fields

| Field | Type | What it provides |
|---|---|---|
| `config` | `Config` | Layered JSON config with dot-path access |
| `skills` | `SkillManager` | Skill catalog (query available skills) |
| `database` | `DatabaseManager` | Chat, message, agent, todo CRUD |
| `db_connections` | `Any` | ConnectionManager from database skill (or None) |
| `leader` | `LeaderRegistry` | Keyboard chord tree |
| `providers` | `ProviderRegistry` | Named LLM provider instances |
| `agents` | `AgentManager` | Agent definition registry |
| `vault` | `VaultManager` | Encrypted credential + note storage |
| `working_directory` | `str` | Current project directory |
| `stream_manager` | `StreamManager \| None` | Owns active LLM stream tasks |
| `session_manager` | `SessionManager \| None` | Saves/restores workspace state |
| `services` | `dict[str, Any]` | Dynamic service instances from skill `SKILL_SERVICES` |
| `app` | `WorkspaceApp` | Running Textual app instance (set after construction) |

---

## Quick Reference: File Conventions

| File | Where | Auto-discovered? | What it registers |
|---|---|---|---|
| `SKILL.md` | Skill root | Yes (discovery marker) | Skill name, description, requirements |
| `__init__.py` | Skill root | Yes (entry point for UI skills) | All `@register_*` via side-effect imports |
| `*.tcss` | Skill directory (any depth) | Yes | Widget styles |
| `components/*.py` | Skill subdirectory | Yes | `@register_sidebar_tab()`, `@register_handler()`, etc. |
| `cmd/*.py` | Skill subdirectory | Yes | `@register_command()` |
| `tools/*.py` | Skill subdirectory | Yes | `@register_tool()` |
| `scripts/*.py` | Skill subdirectory | No (run via `run_skill`) | Agent-runnable scripts |