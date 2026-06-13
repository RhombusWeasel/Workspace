# Workspace

Workspace is a TUI based personal development environment built in python with Textual.
With AI tooling and customization at it's core your Workspace can truly become your own.

## Installation

1. Clone the repo:
    ```bash
    git clone https://github.com/RhombusWeasel/Workspace.git
    cd Workspace
    ```

2. Install [uv](https://docs.astral.sh/uv/) if you don't have it already:
    ```bash
    curl -LsSf https://astral.sh/uv/install.sh | sh
    ```

3. Sync dependencies and create the virtual environment:
    ```bash
    uv sync
    ```

4. Run Workspace:
    ```bash
    uv run main.py
    ```

### Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) package manager
- An Ollama instance running locally (or a remote LLM provider)

## Features

### Password Vault with Auto-Redaction
    A password vault lies at the heart of Workspace. A password is requested at launch which sets the master password for the vault.
    Skills with UI components can register and access passwords to and from the vault, eliminating the need for easily stolen environment variables.
    Workspace will automatically redact any passwords stored in its vault from messages before sending them to an LLM provider.
    You can also configure a regex list to auto-redact any matches — useful for Azure/AWS secrets and other credential patterns.

### LLM Integration
    Workspace integrates with LLM providers via a provider registry, allowing you to connect to multiple backends simultaneously.
    Configure your preferred provider and model in your workspace config — Ollama is the default, but any provider that subclasses `BaseProvider` can be added.
    The agent system uses a tool-calling loop with progress checkpoints, so long-running tasks with many tool calls continue naturally instead of hitting a hard stop.
    Messages are automatically redacted before being sent to any provider, ensuring secrets never leave your machine.

### Agent System
    Agents are system prompt templates with optional overrides for model, provider, tools, skills, temperature, and max tool iterations.
    Templates support dynamic variables like `{{agent_name}}`, `{{project_name}}`, `{{date}}`, and `{{skills.catalog}}` that resolve at render time.
    Switch between agents mid-conversation with the `/agent` slash command, or create custom agents for specialized workflows like code review or test writing.
    The default agent ("Cody") is a general-purpose coding assistant, and the "inline-suggest" agent handles fast code completions.

### Skills System
    Extend Workspace's functionality through a modular skills system. Each skill can register UI components, access the vault, and interact with the LLM to provide specialized tooling for your workflow.
    The skill system provides tiered loading of skills allowing you to customize skills for specific workflows. Skills can be defined globally in `~/.agents/skills/` which agents anywhere will be able to use, or locally in a project directory allowing for specialized skills to live only where they are needed.

### Workspace Tabs
    A tiling tab system lets you arrange your workspace the way you want it. Split panes horizontally or vertically, open multiple chat sessions, terminals, and query editors side by side.
    Tab state is persisted across restarts, so your layout is waiting for you when you come back.
    Leader chords (`Ctrl+Space`) provide quick keyboard access to all actions — no mouse required.

## Default Skills

### AI Chat
    Streaming conversation with an LLM agent in a workspace tab. Supports slash commands, streaming abort, tool-call rendering, and conversation persistence.
    Open with `Ctrl+Space a` (mnemonic: AI).

### Git Integration
    Interact with Git repositories, view diffs, commit changes, and manage branches directly from the TUI, or ask your agent to do so.
    Create checkpoints, roll back changes, and get status updates without leaving your workspace.

### Agent Management
    View, create, edit, and delete specialized AI agents with per-agent model, provider, tools, and skills configuration.
    Each agent is a template with dynamic variables, so you can build personas that know about your project, your tools, and your workflow.

### Terminal
    An embedded terminal emulator with scrollback, PTY lifecycle management, and workspace tab integration.
    Open with `Ctrl+Space t o` (mnemonic: Terminal → Open).

### Database
    Browse database connections in the sidebar, open query editors in workspace tabs, and execute SQL with pagination support.
    Ships with a SQLite provider; additional providers can be registered for PostgreSQL, MySQL, and more.

### Brave Search
    Web search via the Brave Search API — returns concise, structured results for research and fact-checking.
    Give your agent access to real-time web information without leaving the conversation.

### Workspace Docs
    Internal documentation for Workspace's core systems. Use these docs when extending Workspace with new features, skills, or UI components.
    Covers events, config, vault, skills, tools, commands, providers, agents, and architecture.

## Configuration

Workspace uses layered JSON config files loaded from three tiers (defaults → user → project):

```
~/.agents/config.json          # User-level defaults
.project/config.json           # Project-level overrides
```

Key config options:

```json
{
    "providers": {
        "ollama": {
            "type": "ollama",
            "model": "deepseek-v4-pro:cloud",
            "base_url": "http://localhost:11434"
        }
    },
    "session": {
        "provider": "ollama",
        "max_tool_calls": 10,
        "yolo_mode": false
    },
    "agents": {
        "name": "Cody"
    },
    "ui": {
        "theme": "haxor"
    }
}
```

All config keys support dot-path access and have sensible defaults registered at import time.

## Architecture

Workspace is built on Textual (the Python TUI framework) with a plugin-first architecture:

- **Bootstrap** wires together all core services in a deterministic sequence and returns an `AppContext` service locator
- **Event system** (`WorkspaceEvent`) enables loose coupling between components via `@register_handler`
- **Tool registry** (`@register_tool`) and **command registry** (`@register_command`) let skills extend the agent's capabilities
- **Skill discovery** scans three directories for `SKILL.md` files and loads tools, commands, sidebar panels, and services
- **Provider registry** manages named LLM provider instances with lazy creation from config
- **Agent registry** manages agent definitions in SQLite with template rendering and dynamic providers

See the `workspace_docs` skill for full internal documentation on any subsystem.

## Running Tests

```bash
uv run pytest tests/
```

## License

This project is currently private. Contact the maintainer for licensing information.