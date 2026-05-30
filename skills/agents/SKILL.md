---
name: agents
description: Agent management — view, create, edit, and delete specialized AI agents with per-agent model, provider, tools, and skills
---

# Agents Skill

Manages agent definitions stored in the database.  Each agent is a
system prompt template with optional overrides for:

- **Model** — which LLM model to use (e.g. `deepseek-r1:14b`, `gpt-4o`)
- **Provider** — which named provider instance to route through (e.g. `ollama-local`, `openai-main`)
- **Tools** — restrict which tools the agent can use (JSON list of tool names or tags)
- **Skills** — restrict which skills' knowledge is included in the system prompt (JSON list of skill names)
- **Temperature** — override the model's sampling temperature
- **Max tool iterations** — safety limit on tool-calling loops

## When to Activate

Activate this skill when the user asks about:
- Creating or editing AI agents
- Setting up specialized agents (code reviewer, test writer, etc.)
- Changing which model or provider an agent uses
- Restricting an agent's tool access
- Switching between different agent personas
- Understanding what `{{key}}` variables are available in templates

## Available Variables

| Key | Description | Dynamic? |
|---|---|---|
| `{{working_directory}}` | Current project directory | Yes |
| `{{project_name}}` | Basename of the working directory | Yes |
| `{{date}}` | Current date (YYYY-MM-DD) | Yes |
| `{{model}}` | Configured model name | Yes |
| `{{provider}}` | Default provider instance name | Yes |
| `{{skills}}` | Full skills catalog XML | Yes |
| `{{skills.catalog}}` | Same as `{{skills}}` | Yes |
| `{{skills.names}}` | Comma-separated skill names | Yes |

## Agent IDs

- `default` — the main chat assistant agent
- `inline-suggest` — the code completion agent (used by inline suggestions)
- `custom:*` — user-created agents (auto-generated prefix)

## Configuration

| Key | Description |
|---|---|
| `agent.default_id` | Which agent ID to use for the chat (default: `"default"`) |
| `agent.inline_suggest_id` | Which agent ID to use for inline suggestions (default: `"inline-suggest"`) |
| `session.default_provider` | Which named provider instance to use by default (default: `"ollama"`) |
| `session.model` | Default model name when agent doesn't specify one |
| `providers.instances` | Named provider instance definitions |

## Provider Instances

Providers are defined in config under `providers.instances`.  Each instance
has a `type` (e.g. `ollama`, `openai`) plus optional `model` and `base_url`:

```json
{
  "providers": {
    "instances": {
      "ollama-local": {
        "type": "ollama",
        "base_url": "http://localhost:11434",
        "model": "deepseek-r1:14b"
      },
      "ollama-cloud": {
        "type": "ollama",
        "model": "deepseek-v4-pro:cloud"
      }
    }
  }
}
```

Agents reference a provider by instance name.  If an agent doesn't specify
a provider, the session default (`session.default_provider`) is used.