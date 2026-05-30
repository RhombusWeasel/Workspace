# Workspace

Workspace is a TUI based personal development environment built in python with Textual.
With AI tooling and customization at it's core your Workspace can truly become your own.

# Installation

1. Clone the repo `git clone https://github.com/RhombusWeasel/Workspace.git`
2. Sync UV `uv sync`
3. Profit `uv run main.py`

# Features

## Password vault with auto redaction
    A password vault lies at the heart of Workspace, a password is requested at launch which sets the master password for the vault.
    Skills with UI components can register/access passwords to/from the vault allowing for no easily stolen environment variables to be used.
    Workspace will automatically redact any passwords in it's vault from any messages before sending to an LLM provider.
    You can also configure a regex list to auto redact any matches (Useful for Azure/AWS secrets etc.)

## LLM Integration
    Workspace integrates with various LLM providers, allowing you to leverage AI assistance directly within your development environment.
    Configure your preferred provider and model to get context-aware help while you work.

## Skills System
    Extend Workspace's functionality through a modular skills system. Each skill can register UI components, access the vault, and interact with the LLM to provide specialized tooling for your workflow.
    The Skill system provides tiered loading of skills allowing you to customize skills for specific workflows.  Skills can be defined globally in ~/.agents/skills/ which agents anywhere will be able to use or locally in a project directory allowing forspecialized skills to live only where they are needed.

# Default LLM Skills:
    **Git Integration**: Interact with Git repositories, view diffs, commit changes, and manage branches directly from the TUI or ask your agent to do so.
    **