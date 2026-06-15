# Context Files & Template Providers

**Files:** `core/context_files.py`, `core/project_context.py`, `core/agents_md.py`

---

## Purpose

These modules load markdown files from the user, project, and workspace directories and register them as dynamic template providers for the agent system prompt. The agent template system uses `{{variable}}` placeholders — these providers supply values for `{{user}}`, `{{design}}`, `{{tasks}}`, `{{workspace_agents}}`, `{{global_agents}}`, and `{{local_agents}}`.

---

## Context Files (`core/context_files.py`)

Loads user-facing markdown files and provides them as template variables.

### Functions

| Function | File | Description |
|---|---|---|
| `load_user_md()` | `~/.agents/user.md` | User profile and preferences |
| `load_design_md()` | `{wd}/.agents/design.md` | Project design document |
| `load_tasks_md()` | `{wd}/.agents/tasks.md` | Project task tracking |

Each function returns the file content as a string. If the file doesn't exist, it returns an instruction string telling the LLM what the file would contain and where it should be located, rather than an error or empty string. This ensures the LLM always knows about these context sources even when they're not yet created.

### Registered Providers

| Provider Key | Source | Value |
|---|---|---|
| `user` | `load_user_md()` | Content of `~/.agents/user.md` |
| `design` | `load_design_md()` | Content of `{wd}/.agents/design.md` |
| `tasks` | `load_tasks_md()` | Content of `{wd}/.agents/tasks.md` |

---

## Agents Markdown (`core/agents_md.py`)

Loads AGENTS.md rule files from three tiers and provides them as template variables for agent system prompts.

### Functions

| Function | Path | Description |
|---|---|---|
| `load_workspace_agents_md()` | `{workspace_dir}/AGENTS.md` | Workspace-bundled rules (tier 1) |
| `load_global_agents_md()` | `~/.agents/AGENTS.md` | User-global rules (tier 2) |
| `load_local_agents_md()` | `{wd}/.agents/AGENTS.md` | Project-local rules (tier 3) |

Each function returns the file content, or an empty string if the file doesn't exist.

### Registered Providers

| Provider Key | Source | Value |
|---|---|---|
| `workspace_agents` | `load_workspace_agents_md()` | Bundled AGENTS.md |
| `global_agents` | `load_global_agents_md()` | User AGENTS.md |
| `local_agents` | `load_local_agents_md()` | Project AGENTS.md |

---

## Bootstrap Integration

Context file providers are registered during bootstrap (phase 9b) after the agent registry is created:

```python
# In bootstrap.py
from core.agents_md import load_workspace_agents_md, load_global_agents_md, load_local_agents_md
from core.context_files import load_user_md, load_design_md, load_tasks_md

agents.register_provider("workspace_agents", load_workspace_agents_md)
agents.register_provider("global_agents", load_global_agents_md)
agents.register_provider("local_agents", load_local_agents_md)
agents.register_provider("user", load_user_md)
agents.register_provider("design", load_design_md)
agents.register_provider("tasks", load_tasks_md)
```

These are dynamic providers — they're called each time an agent prompt is built, so edits to the markdown files are reflected immediately without restarting the application.

---

## Design Decisions

1. **Missing-file instructions** — When a context file doesn't exist, the functions return a descriptive instruction string (e.g. "Create a file at ~/.agents/user.md with your preferences...") rather than an empty string or error. This guides the LLM to understand the intended workflow.

2. **Dynamic, not static** — Providers are called per-agent-build, not cached at startup. This means edits to user.md, design.md, tasks.md, and AGENTS.md take effect on the next agent interaction.

3. **Three-tier AGENTS.md** — Following the same tiered pattern as config and skills: bundled → global → local, with later tiers overriding earlier ones.