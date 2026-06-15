# Workspace — Design Summary

## What It Is
A Textual-based TUI application providing an AI coding assistant. Supports Ollama and OpenAI as LLM backends, features a skill architecture for extensibility, and includes an encrypted password vault, multi-connection database management, git checkpointing, and a keyboard-driven leader menu system.

## Architecture

### Core Systems (`core/`)
- **Config** (`config.py`) — Layered JSON, dot-path access, diff-save, registered defaults
- **Vault** (`vault.py`) — Fernet + PBKDF2 encryption, credentials + secure notes, session-based unlock
- **Skills** (`skills.py`) — SKILL.md discovery, 3-tier override, `components/` auto-import, XML catalog
- **Agent** (`agent.py`) — System prompt builder, tool-calling loop, streaming, progress checkpoints; on_mount rebuild uses refresh_from_sections() for both history loading and streaming
- **AgentRegistry** (`agent_registry.py`) — Agent definitions with per-agent model/provider/tools/skills/temperature
- **StreamManager** (`stream_manager.py`) — Owns LLM stream task, sequential section tracking (thinking→response transitions create separate DB rows), DB persistence via upsert_streaming_section, usage capture
- **Tools** (`tools.py`) — `@register_tool()` decorator, tag grouping, enable/disable
- **Database** (`database.py`) — SQLite CRUD, agent seeding
- **Leader** (`leader.py`) — Keyboard chord tree for Ctrl+Space menu
- **Commands** (`commands.py`) — Slash-command loader, 3-tier discovery
- **Events** (`events.py`) — `WorkspaceEvent` inter-component messaging
- **Providers** (`providers/`) — BaseProvider protocol, Ollama implementation, ProviderRegistry with named instances
- **Paths** (`paths.py`) — 3-tier resolution: `$WORKSPACE_DIR/skills/` → `~/.agents/skills/` → `{wd}/.agents/skills/`
- **PaneTree** (`pane_tree.py`) — Recursive split/close/navigate data model
- **TerminalPassthrough** (`terminal_passthrough.py`) — Key registry for terminal shortcuts
- **Session** (`session.py`) — SessionManager saves/restore workspace layout, open tabs, sidebar visibility to JSON; TabTypeHandler registry for serialising/deserialising tab state per type
- **AgentsMD** (`agents_md.py`) — Layered AGENTS.md rules (global + local)
- **ContextFiles** (`context_files.py`) — User/design/tasks markdown loaders with missing-file instructions ({{user}}, {{design}}, {{tasks}})

### UI (`ui/`)
- **Sidebar** — Tab-based panel (config, file browser, vault, agents, database, git)
- **Workspace** — Recursive split panes, WorkspaceTabs, FileEditor, WelcomeView
- **Tree** — Generic expandable list widget with CSS hide/show
- **Widgets** — InputModal, ConfirmModal, LeaderOverlay, CommandsHelp

### Skills (`skills/`)
- **chat** — AI chat tab (ChatManager, ChatDisplay, ChatInput, command palette)
- **terminal** — Embedded terminal with PTY lifecycle and screen preservation across splits
- **database** — DB sidebar panel, connection form, query editor with pagination; session handler for query_editor tabs
- **git** — Git panel, checkpoint/diff/log scripts, leader chords
- **agents** — Agent panel for CRUD and switching
- **brave_search** — Web search via Brave API (pure script skill)
- **workspace_docs** — Core-systems documentation for agent context

### Tools (`tools/`)
5 core tools: `activate_skill`, `read_file`, `write_file`, `edit_file`, `run_command`, `run_skill`

### Session (`session.py`)
- `TabTypeHandler` — dataclass with serialise/deserialise/content_factory/make_label per tab type
- `_TAB_TYPE_REGISTRY` — dict mapping tab type strings → TabTypeHandler instances
- `register_tab_type()` — registers a handler; called at module import time by each tab type
- `SessionManager` — owns `session_path` and `ctx`; `save()` captures workspace state, `restore()` rebuilds from JSON
- Session file at `{wd}/.agents/session.json`; versioned with `SESSION_VERSION`
- Tab types: chat (chat_id, agent_id), terminal (command, working_directory), file_editor (filepath), welcome (no state), query_editor (connection_id, query_text)
- Graceful degradation: missing chats/files cause tab to be skipped
- Pane tree serialisation via `pane_tree_to_dict()` / `pane_tree_from_dict()` in `pane_tree.py`

### Testing
Mission-critical tests only — core safety, tools, streaming, chat display, config, skill discovery, session persistence. No tests for internal implementation details or unimplemented features. See `tests/README.md`.

### Key Bug Fixes
- Duplicate `_rebuild_and_maybe_resume` method removed from `chat_manager.py` — Python was using the second definition, shadowing the first
- Error logging added to `_rebuild_and_maybe_resume()` and `HistoryPanel._open_chat()` — previously silent exceptions

### Key Patterns
- **AppContext** — Service locator dataclass (config, skills, database, leader, providers, agents, db_connections, working_directory, services)
- **Bootstrap** — Ordered startup: config → skills → tools → DB → leader → context
- **Skill components/** — Auto-imported Python modules that register sidebar panels, event handlers, leader chords, config defaults
- **Skill scripts/** — Python scripts run in-process via `exec()` with `context` (AppContext) and `args` globals
- **3-tier discovery** — Bundled → user-level → project-level (later overrides earlier)
- **Terminal preservation** — pyte Screen + TerminalDisplay transferred across recomposition, not widget remount