---
name: workspace_docs
description: Workspace core-systems documentation — events, config, vault, skills, tools, commands, and architecture
---

# Workspace Documentation

Internal documentation for Workspace's core systems.  Use these docs when extending
Workspace with new features, skills, or UI components.

## How to Read These Docs

This skill's SKILL.md is an index.  To read the full documentation, use
the **`run_skill`** tool to call the `read_doc.py` script bundled with
this skill:

**List available docs:**
```
run_skill(skill_name="workspace_docs", script="scripts/read_doc.py")
```

**Read a specific doc:**
```
run_skill(skill_name="workspace_docs", script="scripts/read_doc.py", args=["docs/events.md"])
```

The `args` value is the doc filename — you can use either the short form
(`events.md`) or the full form (`docs/events.md`).  If a file isn't found,
the script lists all available docs automatically.

**Read every doc at once** (large — ~166KB total):
```
run_skill(skill_name="workspace_docs", script="scripts/read_doc.py", args=["--all"])
```

## Documentation Index

| Category | File | Summary |
|---|---|---|
| **Guide** | | |
| Creating a Skill | `docs/creating_a_skill.md` | Step-by-step: anatomy, all registration types, examples, troubleshooting |
| **Core Systems** | | |
| Event system | `docs/events.md` | `WorkspaceEvent`, `@register_handler`, `dispatch`, event naming |
| Config management | `docs/config.md` | Layered JSON, dot-path access, diff-save, registered defaults |
| Password vault | `docs/vault.md` | Fernet encryption, master + local vaults, `VaultManager` |
| Skill loading | `docs/skill_loading.md` | 3-tier skill discovery, loading, `__init__.py` handling, `SKILL_SERVICES` |
| Workspace tabs | `docs/workspace_tabs.md` | `TabState`, `flush_state()`, `content_factory`, persistence patterns |
| Tool registry | `docs/tools.md` | `@register_tool`, tag grouping, enable/disable, context injection |
| Slash commands | `docs/commands.md` | `@register_command`, auto-discovery from `cmd/` directories |
| Leader chords | `docs/leader.md` | `register_action`, `register_submenu`, chord tree, terminal passthrough |
| AppContext | `docs/context.md` | Service locator dataclass, all fields, access patterns |
| Skills system | `docs/skills.md` | Skill discovery, SKILL.md format, skill profiles, `activate_skill`, `SKILL_SERVICES`, `render_selected` |
| LLM providers | `docs/providers.md` | `BaseProvider` base class with redaction, `ProviderRegistry`, creating a new provider |
| Agent | `docs/agent.md` | Tool-calling loop with progress checkpoints, template rendering, streaming, abort support |
| Agent registry | `docs/agent_registry.md` | `AgentManager`, agent CRUD, template variables, dynamic providers, config resolution, migration |
| Database | `docs/database.md` | Chat/message/agent/todo CRUD, section storage, history reconstruction |
| Sidebar registry | `docs/sidebar.md` | `@register_sidebar_tab`, tab discovery, Nerd Font icons |
| Terminal | `docs/terminal.md` | `TerminalView`, `TerminalState`, PTY lifecycle, screen/display preservation |
| UI widgets | `docs/ui_widgets.md` | `InputModal`, `ConfirmModal`, pushing modals from handlers/tools/commands |
| Bootstrap | `docs/bootstrap.md` | Startup sequence, phase ordering, provider/agent registry, error isolation |

## Quick Reference: All Registries

| What | Module | Decorator/Function | Parameters |
|---|---|---|---|
| Sidebar tab | `ui.sidebar.registry` | `@register_sidebar_tab(name, icon, side, tooltip)` | Widget subclass |
| Event handler | `core.events` | `@register_handler(event_type)` | `(data: dict, ctx: AppContext)` |
| LLM tool | `core.tools` | `@register_tool(name, description, parameters, tags)` | Sync or async function |
| Slash command | `core.commands` | `@register_command(name, description)` | `async (app, args: str)` |
| Leader chord | `core.leader` | `register_action(keys, label, event_type=)` | Side-effect registration |
| Leader submenu | `core.leader` | `register_submenu(keys, label)` | Side-effect registration |
| Config defaults | `core.config` | `register_defaults(dict)` | Nested dict |
| Terminal passthrough | `core.terminal_passthrough` | `register_terminal_passthrough(keys)` | Set of key strings |
| Provider type | `core.providers.registry` | `registry.register_type(name, cls)` | Provider class |
| Agent dynamic var | `core.agent_registry` | `manager.register_dynamic(key, callable)` | Key + context callable |

## Quick Reference: AppContext Fields

| Field | Type | What it provides |
|---|---|---|
| `config` | `Config` | Layered JSON config with dot-path access |
| `skills` | `SkillManager` | Skill catalog (query available skills) |
| `database` | `DatabaseManager` | Chat, message, agent, todo CRUD |
| `db_connections` | `Any` | ConnectionManager from database skill (or None) |
| `providers` | `ProviderRegistry` | Named LLM provider instances, lazy creation from config |
| `agents` | `AgentManager` | Agent definitions, templates, CRUD, dynamic providers |
| `services` | `dict[str, Any]` | Dynamic service instances from skill `SKILL_SERVICES` |
| `leader` | `LeaderRegistry` | Keyboard chord tree |
| `vault` | `VaultManager` | Encrypted credential + note storage |
| `working_directory` | `str` | Current project directory |
| `css_paths` | `list[str]` | Collected `.tcss` file paths for Textual CSS |
| `app` | `WorkspaceApp` | Running Textual app instance |
| `provider` | `BaseProvider \| None` | Backward-compat property → `ctx.providers.get_default()` |
| `prompts` | `AgentManager \| None` | **Deprecated** — use `ctx.agents` instead |