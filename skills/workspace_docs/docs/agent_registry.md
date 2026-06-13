# Agent Registry

**File:** `core/agent_registry.py`
**Depends on:** `core.database.DatabaseManager`, `core.config` (for register_defaults)

---

## Purpose

The `AgentManager` class manages agent definitions stored in the `agents`
database table.  Each agent is a system prompt template plus optional
overrides for model, provider, tool permissions, skill activation, and
generation parameters.  Templates use `{{key}}` and `{{key.sub}}`
placeholders that are resolved at render time from dynamic providers.

The `AgentManager` also handles:
- **Legacy migration** from the old `prompts` and `agents_legacy` tables
- **Seeding** default agent definitions on first run
- **Config resolution** for model, provider, tools, skills, temperature,
  and max_tool_iterations

---

## Architecture

```
AgentManager(db, working_directory)
    │
    ├── create_agent(name, template, ...) → agent_id
    ├── get_agent(agent_id) → dict
    ├── list_agents(scope) → list[dict]
    ├── update_agent(agent_id, **kwargs)
    ├── delete_agent(agent_id)
    │
    ├── render(agent_id, ctx) → system_prompt_string
    │       └── resolve {{key}} placeholders from dynamic providers
    │
    ├── resolve_model(agent_def, ctx) → str
    ├── resolve_provider_name(agent_def, ctx) → str
    ├── resolve_tools(agent_def) → list[str] | None
    ├── resolve_skills(agent_def) → list[str] | None
    ├── resolve_temperature(agent_def) → float | None
    ├── resolve_max_tool_iterations(agent_def) → int | None
    │
    └── register_dynamic(key, provider_callable)
```

---

## Agent Definition Schema

```sql
CREATE TABLE agents (
    id                  TEXT PRIMARY KEY,
    name                TEXT NOT NULL,
    description         TEXT NOT NULL DEFAULT '',
    template            TEXT NOT NULL,
    model               TEXT NOT NULL DEFAULT '',
    provider            TEXT NOT NULL DEFAULT '',
    scope               TEXT NOT NULL DEFAULT 'global',
    tools               TEXT NOT NULL DEFAULT '',
    skills              TEXT NOT NULL DEFAULT '',
    temperature         TEXT NOT NULL DEFAULT '',
    max_tool_iterations TEXT NOT NULL DEFAULT '',
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);
```

| Field | Type | Description |
|---|---|---|
| `id` | `TEXT` | Unique agent identifier (e.g. `"default"`, `"custom:abc12345"`) |
| `name` | `TEXT` | Human-readable name |
| `description` | `TEXT` | Short description shown in agent selection UI |
| `template` | `TEXT` | System prompt template with `{{key}}` placeholders |
| `model` | `TEXT` | Model override (empty = use provider default) |
| `provider` | `TEXT` | Named provider instance from config (empty = session default) |
| `scope` | `TEXT` | `"global"` or `"local"` for project-scoped agents |
| `tools` | `TEXT` | JSON list of tool tags/names (empty = all tools) |
| `skills` | `TEXT` | JSON list of skill names to activate (empty = all skills) |
| `temperature` | `TEXT` | Temperature override (empty = provider default) |
| `max_tool_iterations` | `TEXT` | Override for progress checkpoint interval (empty = config default) |
| `created_at` | `TEXT` | ISO 8601 timestamp |
| `updated_at` | `TEXT` | ISO 8601 timestamp |

---

## API

### Constructor

```python
manager = AgentManager(db=database_manager, working_directory="/path/to/project")
```

On construction, the manager migrates legacy tables and seeds default
agents if the `agents` table is empty.

### CRUD

| Method | Signature | Description |
|---|---|---|
| `create_agent` | `(name, description="", template="", model="", provider="", scope="global", tools="", skills="", temperature="", max_tool_iterations="", agent_id=None) → str` | Create a new agent, return its ID |
| `get_agent` | `(agent_id) → dict \| None` | Get an agent by ID |
| `list_agents` | `(scope=None) → list[dict]` | All agents, optionally filtered by scope |
| `update_agent` | `(agent_id, **kwargs)` | Update agent fields |
| `delete_agent` | `(agent_id)` | Delete an agent by ID |

### Rendering

```python
system_prompt = manager.render("default", ctx)
```

`render()` resolves all `{{key}}` and `{{key.sub}}` placeholders using
registered dynamic providers and extra variables.  Resolution order:

1. **Extra variables** (caller-supplied overrides, highest priority)
2. **Dynamic providers** (context-aware, registered via `register_dynamic`)
3. **Left as `{{key}}`** if unresolved

### Dynamic Providers

```python
manager.register_dynamic("date", lambda ctx: datetime.now().strftime("%Y-%m-%d"))
manager.register_dynamic("agent_name", lambda ctx: ctx.config.get("agents.name", "Cody"))
manager.register_dynamic("skills", lambda ctx: {"catalog": xml, "names": names_str})
```

Providers can return either:
- A `str` — used directly for `{{key}}`
- A `dict` — enables dotted key access (e.g. `{{skills.catalog}}`)

Dicts support a `__default__` key for bare `{{key}}` access.

**Built-in providers** (registered at bootstrap):

| Key | Returns | Description |
|---|---|---|
| `agent_name` | `str` | From `agents.name` config (default: "Cody") |
| `working_directory` | `str` | Current working directory |
| `project_name` | `str` | Directory name of working directory |
| `date` | `str` | Current date in YYYY-MM-DD format |
| `skills` | `dict` | `{"catalog": xml, "names": names_str, "__default__": xml}` |
| `workspace_agents` | `str` | Contents of `AGENTS.md` from workspace skills dir |
| `global_agents` | `str` | Contents of `AGENTS.md` from `~/.agents/skills/` |
| `local_agents` | `str` | Contents of `AGENTS.md` from project `.agents/skills/` |

### Config Resolution

```python
agent_def = manager.get_agent("default")
model = manager.resolve_model(agent_def, ctx)             # agent override → provider default
provider = manager.resolve_provider_name(agent_def, ctx)  # agent override → session default → "ollama"
tools = manager.resolve_tools(agent_def)                   # JSON list or None (all tools)
skills = manager.resolve_skills(agent_def)                 # JSON list or None (all skills)
temp = manager.resolve_temperature(agent_def)              # float or None
max_iters = manager.resolve_max_tool_iterations(agent_def) # int or None
```

Resolution order for each:

| Method | Priority 1 | Priority 2 | Priority 3 |
|---|---|---|---|
| `resolve_model` | Agent's `model` field | `providers.<name>.model` config | Empty string |
| `resolve_provider_name` | Agent's `provider` field | `session.provider` config | `"ollama"` |
| `resolve_tools` | Agent's `tools` JSON | `None` (all tools) | — |
| `resolve_skills` | Agent's `skills` JSON | `None` (all skills) | — |
| `resolve_temperature` | Agent's `temperature` | `None` (provider default) | — |
| `resolve_max_tool_iterations` | Agent's `max_tool_iterations` | `None` (config default) | — |

---

## Template Rendering

The `render_template()` function replaces `{{key}}` and `{{key.sub}}`
placeholders:

```python
from core.agent_registry import render_template

prompt = render_template(
    "You are {{agent_name}}. Project: {{project_name}}.",
    {"agent_name": "Cody", "project_name": "my-app"},
)
# → "You are Cody. Project: my-app."
```

Missing keys are left unchanged.  Dotted keys like `{{skills.catalog}}`
are matched as a single key name, not as nested object access.

> **Note:** Both `core.agent.render_template()` and
> `core.agent_registry.render_template()` exist.  They share the same
> regex pattern and behavior.  The agent module uses it for system prompt
> rendering; the registry module uses it for template variable resolution.

---

## Default Agents

Two agents are seeded on first run:

### Default Assistant (`id: "default`)

General-purpose coding assistant with full template including agent name,
project info, skills catalog, and agents.md content.

### Inline Suggest (`id: "inline-suggest"`)

Fast code completion agent for inline suggestions.  Outputs only raw
completion text — no explanations, no markdown.

---

## Config Defaults

```python
register_defaults({
    "agent": {
        "default_id": "default",
        "inline_suggest_id": "inline-suggest",
    },
    "agents": {
        "name": "Cody",
    },
})
```

| Key | Default | Description |
|---|---|---|
| `agent.default_id` | `"default"` | ID of the default chat agent |
| `agent.inline_suggest_id` | `"inline-suggest"` | ID of the inline suggestion agent |
| `agents.name` | `"Cody"` | Name used in `{{agent_name}}` template variable |

---

## Legacy Migration

On first run, `AgentManager` automatically migrates data from:

1. **`prompts` table** — Rows are copied into `agents` with `system_prompt`
   → `template` and default values for new columns.  The `prompts` table
   is dropped after migration.
2. **`agents_legacy` table** — If an old `agents` table exists with the
   old schema (6 columns instead of 14), it's renamed to
   `agents_legacy`, data is migrated, and the legacy table is dropped.

---

## Design Decisions

1. **Database-backed, not config-backed** — Agents are stored in SQLite
  so they can be created and modified at runtime without editing config
  files.

2. **Templates with dynamic providers** — System prompts use `{{key}}`
  placeholders resolved at render time, not stored time.  This keeps
  prompts up-to-date with current skills, date, project name, etc.

3. **Dotted key support** — `{{skills.catalog}}` enables fine-grained
  access to dict-valued providers.  The `__default__` key in dicts
  provides a fallback for bare `{{skills}}`.

4. **Scope field** — `global` and `local` scopes allow project-specific
  agents that override or supplement global ones.

5. **Config resolution cascade** — Each agent field has a clear fallback
  chain (agent override → config default → hardcoded default), making
  it easy to use the default agent with custom overrides.