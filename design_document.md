# Workspace Rewrite — Design Document

## 1. Overview

Workspace is a Textual-based TUI application providing an AI coding assistant. It supports
Ollama (local) and OpenAI as LLM backends, features a skill architecture
for extensibility, and includes an encrypted password vault, multi-connection database management, git
checkpointing, and a keyboard-driven leader menu system.

This document captures the architecture of the codebase, design decisions made along
the way, and remaining work items.

---

## 2. Architecture

### 2.1 High-Level Component Map

```
main.py                 ← Entry point: WorkspaceApp, leader bindings, compose/paste/mount
bootstrap.py            ← Bootstrap: config → skills → tools → DB → leader → context
context.py             ← AppContext dataclass (config, skills, database, leader, working_directory)
conftest.py            ← Pytest fixtures
├── core/              ← Core systems (zero UI dependency)
│   ├── agent.py       ← Agent: system prompt builder, tool-calling loop, streaming, progress checkpoints
│   ├── agent_registry.py   ← AgentManager: agent definition registry, template rendering
│   ├── commands.py    ← Slash-command loader (CommandBase, 3-tier discovery)
│   ├── config.py      ← Config manager (layered JSON, dot-path, diff-save, registered defaults)
│   ├── database.py    ← Database manager (SQLite provider, CRUD)
│   ├── events.py      ← WorkspaceEvent message system (leader chords → workspace/terminal actions)
│   ├── leader.py      ← Leader registry (tree of keyboard chords for Ctrl+Space menu)
│   ├── pane_tree.py   ← Pure data model: LeafPane, SplitPane, split/close/navigate ops
│   ├── paths.py       ← 3-tier path resolution ($WORKSPACE_DIR, ~/.agents, project)
│   ├── skills.py      ← Skill discovery & catalog (SKILL.md, YAML frontmatter, 3-tier)
│   ├── terminal_passthrough.py ← Key passthrough registry (prevent terminal stealing app shortcuts)
│   ├── tools.py       ← Tool registry (@register_tool, tag-based grouping, enable/disable)
│   ├── vault.py       ← Password vault (Fernet + PBKDF2, credentials + secure notes)
│   └── providers/
│       ├── base.py    ← BaseProvider protocol, ChatResponse, StreamChunk, TokenUsage
│       ├── ollama.py  ← Ollama provider (chat + stream_chat, vault key resolution)
│       ├── registry.py ← ProviderRegistry (named instances, lazy creation)
│       └── __init__.py ← Provider types registry + config defaults
├── ui/                ← All Textual widgets
│   ├── sidebar/
│   │   ├── registry.py          ← Sidebar tab registration + discovery
│   │   ├── sidebar.py           ← Sidebar + SidebarContainer (hides/shows)
│   │   ├── panels/
│   │   │   ├── config_panel.py  ← ConfigPanel: editable config tree with actions
│   │   │   ├── file_browser.py  ← FileBrowser: lazy directory tree with actions
│   │   │   ├── vault_panel.py   ← VaultPanel: encrypted credential + note management
│   │   │   └── __init__.py
│   │   └── __init__.py
│   ├── tree/
│   │   ├── tree.py              ← Generic Tree widget (flat expandable list, CSS hide/show)
│   │   ├── tree_row.py          ← TreeRow (compose-based, hosts content + action buttons)
│   │   └── __init__.py
│   ├── widgets/
│   │   ├── commands_help.py     ← Leader chord reference overlay
│   │   ├── confirm_modal.py    ← Yes/No confirmation dialog
│   │   ├── input_modal.py      ← Text input modal
│   │   ├── leader_overlay.py    ← Leader menu overlay (chord tree navigation)
│   │   └── __init__.py
│   ├── workspace/
│   │   ├── file_edit_handler.py ← Event handler wiring file.open → workspace tab
│   │   ├── file_editor.py      ← FileEditor widget (read/write files in a tab)
│   │   ├── tabs.py             ← WorkspaceTabs (tab bar + content area, closeable tabs, state persistence)
│   │   ├── welcome_view.py    ← WelcomeView (landing page for empty panes)
│   │   ├── workspace.py       ← Recursive split-pane workspace + recomposition logic
│   │   └── __init__.py
│   └── __init__.py
├── skills/            ← Bundled skills (3-tier discoverable)
│   ├── __init__.py
│   ├── chat/          ← AI chat workspace tab
│   │   ├── SKILL.md
│   │   ├── __init__.py
│   │   ├── chat_display.py      ← ChatDisplay: Tree-based streaming message display
│   │   ├── chat_input.py        ← ChatInput: Input wrapper, posts ChatSubmitted
│   │   ├── chat_manager.py      ← ChatManager: orchestrates streaming loop + history/DB
│   │   ├── chat_tab.py          ← ChatTabState, content factory, leader chords
│   │   ├── commands.py          ← /clear, /new slash commands
│   │   ├── command_palette.py   ← CommandPalette: fuzzy-search overlay for slash commands
│   │   ├── command_suggester.py ← CommandSuggester: autocomplete for command palette
│   │   ├── file_palette.py      ← File picker overlay
│   │   ├── file_suggester.py    ← File path autocomplete
│   │   ├── stream_section.py    ← Streaming section data model
│   │   ├── tool_format.py       ← Tool call formatting utilities
│   │   └── chat.tcss
│   ├── database/
│   │   ├── SKILL.md
│   │   ├── __init__.py
│   │   ├── core/
│   │   │   ├── __init__.py
│   │   │   ├── db_connections.py  ← DBProvider ABC, ConnectionManager
│   │   │   └── providers/
│   │   │       ├── __init__.py  ← Auto-discovers .py files at import time
│   │   │       └── sqlite.py   ← @register_provider class SQLiteProvider
│   │   ├── db_panel.py
│   │   ├── connection_form.py
│   │   ├── query_editor.py
│   │   ├── services.py
│   │   └── database.tcss
│   └── terminal/      ← Embedded terminal workspace tab
│       ├── SKILL.md
│       ├── __init__.py
│       ├── terminal.py           ← TerminalView: PTY lifecycle + screen/display preservation
│       ├── terminal_handler.py   ← Leader chord handler for terminal.open
│       └── terminal.tcss
├── tools/              ← Agent-callable tools (registered at startup)
│   ├── activate_skill.py    ← Load SKILL.md content into context
│   ├── read_file.py         ← Read file tool
│   ├── run_command.py       ← Run shell command tool
│   ├── run_skill.py         ← Execute skill scripts (subprocess)
│   ├── write_file.py        ← Write file tool
│   ├── edit_file.py         ← Edit file tool (search/replace)
│   └── __init__.py
├── utils/
│   ├── dom_id.py        ← DOM ID generation utilities
│   ├── icons.py         ← Nerd Font icon constants (file types, actions, folders)
│   └── __init__.py
├── skills/             ← Bundled skills (extensible via SKILL.md)
│   ├── workspace_docs/     ← Core-systems documentation skill
│   │   ├── SKILL.md
│   │   ├── docs/       ← Markdown docs (events, config, vault, skills, etc.)
│   │   └── scripts/
│   │       └── read_doc.py      ← Read doc files via run_skill
│   └── git/           ← Git workflow skill (sidebar panel + scripts)
│       ├── SKILL.md
│       ├── components/  ← Auto-imported: sidebar panel, handlers, leader chords
│       │   └── git_panel.py
│       ├── scripts/    ← run_skill scripts (status, checkpoint, diff, log)
│       │   ├── status.py
│       │   ├── checkpoint.py
│       │   ├── diff_summary.py
│       │   ├── log.py
│       │   └── branch_info.py
│       └── git.tcss
├── cmd/                ← Core slash commands
│   ├── clear.py
│   ├── help.py
│   └── new.py
├── config/             ← Default config fragments
└── implementations/    ← OpenAI provider implementation (separate package)
```

### 2.2 Core Systems

#### A. Config Manager (`core/config.py`)

Layered JSON config with dot-path access (`cfg.get('session.provider')`), diff-save
(only changed keys are written), and registered defaults that modules declare at
import time. Singleton `Config` instance bootstrapped in `Bootstrap.run()`.

#### B. Password Vault (`core/vault.py`)

Fernet + PBKDF2HMAC encryption. Two entry types: credentials (username + password)
and secure notes. Session-based unlock with concurrent caller queuing. Providers
register lock callbacks. API key resolution: vault → config → environment variable.

#### C. Skills System (`core/skills.py`)

Discovers skills via `SKILL.md` YAML frontmatter. 3-tier search: `$WORKSPACE_DIR/skills/`
→ `~/.agents/skills/` → `{wd}/.agents/skills/`. Per-skill enable/disable. Generates
XML catalog for the agent system prompt. Manual scan — no implicit re-discovery.

Skill `components/` directories contain Python modules that are auto-imported by
the bootstrap loader, enabling skills to register sidebar panels, event handlers,
leader chords, and config defaults.
This means a skill can provide both LLM knowledge (via its SKILL.md body) and
UI extensions (via `components/`), without adding new agent tools.

#### D. Provider System (`core/providers/`)

`BaseProvider` protocol with `chat()` and `stream_chat()`. `OllamaProvider`
implementation (OpenAI possible via `implementations/`). `ChatResponse`,
`StreamChunk`, `TokenUsage`, `ToolCall` dataclasses. `StreamChunk` extended with
`thinking` field for reasoning-capable models.

#### E. Tool Registry (`core/tools.py`)

`@register_tool()` decorator with module-level globals. Tag-based grouping.
Enable/disable individual tools or whole groups. Skills drop a `.py` file and
it self-registers at import time. Distinct from slash commands and leader chords
(see §6.3).

#### F. Database Manager (`core/database.py`)

SQLite provider (Cosmos dropped per §6.2). Connection manager, tables: chats,
agents, todos, input_history. CRUD operations. Agent seeding from bundled JSON.
Provider abstraction retained for future extensibility.

#### F2. DB Connection Manager

Manages user-defined database connections backed by the layered config system.
Connection metadata lives under ``db.connections`` in config; sensitive fields
(passwords) are stored in the vault.  Provides a ``DBProvider`` abstract class
that each backend implements, a dynamic ``ConnectionFormModal`` driven by
``form_fields()``, and a lazy-loading sidebar tree that introspects tables,
views, and triggers.  Query execution with offset-based pagination is handled
by each provider's ``execute_query()``.

Providers are auto-discovered from the ``providers/`` sub-package.  Each
provider module uses ``@register_provider`` to self-register at import time.
Adding a new backend is just a matter of dropping a ``.py`` file into
``skills/database/core/providers/``.  See the skill loading documentation
(``skills/workspace_docs/docs/skill_loading.md``) for details.

#### G. Leader Registry (`core/leader.py`)

Tree of keyboard chords for the leader menu (`Ctrl+Space`). `LeaderNode` dataclass
with `register_submenu()` and `register_action()`. Core chords registered by
workspace, chat, and terminal modules at import time. Skill chords discovered
from `SKILL.md` frontmatter.

#### H. Path System (`core/paths.py`)

Simplified to three functions: `workspace_dir()`, `agents_dir()`, `resolve()`. 3-tier
template expansion for skill/CSS/theme discovery. `collect_tcss()` gathers CSS
from all tiers uniformly (including skill directories).

#### I. Skill System (`core/skills.py`, `core/skill_package_manager.py`, `bootstrap.py`)

Skills are the sole extension mechanism. A skill is a directory containing
a `SKILL.md` manifest. Skills with `__init__.py` get full `importlib`
loading with correct `__path__` and `__package__` attributes; skills without
`__init__.py` (ecosystem / Anthropic spec) are discovered and their body is
available for agent activation.

Discovery uses the 3-tier path system:
`{workspace_dir}/skills/` → `~/.agents/skills/` → `{wd}/.agents/skills/`.

The skill package manager (`core/skill_package_manager.py`) handles installing,
updating, removing, and listing skills from git repositories. Skills are
always installed from a tagged release (never a live branch) and the `.git/`
directory is stripped after cloning. Install metadata is stored in
`.skill.json` and mirrored to config (`skills.installed`, `skills.enabled`).
The `/skill` slash command provides the user-facing interface.

At bootstrap, the `skills` package namespace is set up in `sys.modules` and
each discovered skill with `__init__.py` is loaded via
`importlib.util.spec_from_file_location`. The Workspace project root is added to
`sys.path` before loading so skills can import from `core/` and `context/`.

Skills can declare `SKILL_SERVICES` — service factories wired into
`AppContext.services` at bootstrap.

See `skills/workspace_docs/docs/skills.md` and `skills/workspace_docs/docs/skill_loading.md`
for full documentation.

#### J. Event System (`core/events.py`)

`WorkspaceEvent` — a Textural `Message` subclass for inter-component communication.
Leader chords post `WorkspaceEvent` messages which widgets route via `on_workspace_event`
handlers. Used for workspace navigation, terminal opening, and file opening.

#### K. Terminal Passthrough (`core/terminal_passthrough.py`)

Registry of keyboard shortcuts that the terminal must *not* consume (e.g. `Ctrl+Q`
for quit, `Ctrl+Space` for leader, `Ctrl+H/J/K/L` for pane navigation). The
embedded terminal checks this set before forwarding key events.

---

## 3. Design Decisions (Resolved)

### 3.1 Tool Registry: Module Globals with Decorator Pattern

**Decision:** Keep `@register_tool()` with module-level globals. No class wrapping.

**Rationale:** Self-registration at import time with zero boilerplate — skill authors
drop a `.py` file and it just works. A class-based approach would require passing a
registry instance around, adding friction.

### 3.2 Database Providers: Drop Cosmos, Ship SQLite Only

**Decision:** Remove Cosmos DB provider. Ship SQLite as the only bundled provider.
Retain the `BaseDBProvider` abstraction for extensibility.

**Rationale:** `azure-cosmos` + `azure-identity` are heavy dependencies with narrow
utility. One concrete provider is easier to maintain.

### 3.3 Slash Commands, Leader Chords, and Tools: Three Separate Registries

**Decision:** Three distinct registries, no merging.

**Rationale:** Fundamentally different invocation contexts:
- **Tools** — agent-invoked via LLM tool-calling loop, need structured I/O
- **Slash commands** — user-typed in chat (`/command`), freeform control
- **Leader chords** — keyboard-driven (`Ctrl+Space → keys`), pure UI navigation

### 3.4 Skill Discovery: No Hot-Reloading

**Decision:** No implicit re-discovery. Explicit "Scan Skills" button in the UI.

**Rationale:** Implicit re-discovery is confusing. File watchers add complexity.
A manual button gives users control without restarting the app.

### 3.5 Testing Strategy

**Decision:** Full test suite from the start. pytest with Textual `pilot` fixtures.

- `AppContext` makes services injectable
- Module-level singletons have reset functions for test isolation
- Provider tests: mock HTTP → verify normalization
- UI tests: Textual `pilot` for widget-level integration
- Vault tests: integration against temp encrypted file

### 3.6 Chat UI: Unified Streaming

**Decision:** One `ChatManager` class, always streams. No blocking path.

**Rationale:** The old codebase had `MsgBox` (blocking) and `StreamingMsgBox` (streaming)
with ~10 duplicated methods. Unifying eliminates duplication and simplifies
the codebase significantly.

### 3.7 Terminal Preservation: Data Transfer, Not Widget Remount

**Decision:** Transfer pyte `Screen` + `TerminalDisplay` objects across recomposition
rather than trying to remount Textual widgets.

**Rationale:** Textual widgets cannot be remounted after DOM removal. But `Screen`
and `TerminalDisplay` are plain Python objects, not widgets — they can be captured
before the rebuild and injected into a freshly-created `PtyTerminal`. This preserves
both the PTY process and the visible output. See §7 Step 16b for full details.

### 3.8 Git Integration: Skill, Not Plugin (No New Agent Tools)

**Decision:** Implement git integration as a skill rather than a core module.
The agent activates the git skill to read its SKILL.md body, then uses the existing
5 tools (`run_command`, `run_skill`, etc.) for all git operations. No new agent tools
are added.

**Rationale:** Every new tool added to the agent increases the tool-selection error rate.
With 5 tools the model reliably picks the right one; at 8-10 the confusion increases
noticeably. By making git a skill:
- The agent receives rich, contextual git expertise on demand (not just a tool name + description)
- Simple git operations use `run_command` (the agent already knows it)
- Complex multi-step operations use `run_skill` + bundled scripts
- The tool surface stays at 5, preserving model accuracy
- Skills with `components/` directories can register UI (sidebar panels, leader chords)

---

## 4. Resolved Simplifications

These items were identified as needing cleanup in the original codebase and have
been resolved during the rewrite:

| Original problem | Resolution |
|---|---|
| Duplicated `MsgBox`/`StreamingMsgBox` code (~10 methods) | Unified into single `ChatManager` (Step 15) |
| Overly long `get_agent_response()` methods | Broken into smaller methods in `ChatManager` |
| Global mutable state (cfg, skill_manager, etc.) | `AppContext` dataclass introduced (Step 13) |
| `main.py` doing too much | Extracted to `Bootstrap` class (Step 13) |
| CSS discovery scattered across `main.py` and `fs.py` | `paths.collect_tcss()` gathers all tiers (Step 13) |

---

## 5. Current Directory Structure

(After all completed steps — see §7 for step-by-step history.)

```
.
├── bootstrap.py               ← Bootstrap class: config → skills → tools → DB → leader → context
├── conftest.py                ← Pytest fixtures
├── context.py                 ← AppContext dataclass
├── main.py                    ← Entry point: WorkspaceApp, compose, leader bindings
├── workspace_data.db               ← SQLite database (runtime)
├── core/
│   ├── __init__.py
│   ├── agent.py               ← Agent: system prompt, tool-calling loop, streaming
│   ├── agent_registry.py      ← AgentManager: agent definition registry, template rendering
│   ├── commands.py            ← Slash-command loader
│   ├── config.py              ← Layered JSON config, dot-path, diff-save
│   ├── database.py            ← SQLite DB manager, CRUD, agent seeding
│   ├── events.py              ← WorkspaceEvent message system
│   ├── leader.py              ← Leader chord tree registry
│   ├── pane_tree.py           ← Pure data model: split/close/navigate
│   ├── paths.py               ← 3-tier path resolution, collect_tcss()
│   ├── skills.py              ← Skill discovery & catalog
│   ├── terminal_passthrough.py ← Key passthrough registry for terminal
│   ├── tools.py               ← Tool registry, @register_tool()
│   ├── vault.py               ← Encrypted password vault
│   └── providers/
│       ├── __init__.py         ← Provider registry + defaults
│       ├── base.py             ← BaseProvider protocol, ChatResponse, StreamChunk
│       ├── registry.py         ← ProviderRegistry (named instances, lazy creation)
│       └── ollama.py           ← Ollama provider
├── cmd/
│   ├── agent.py               ← /agent slash command
│   ├── clear.py
│   ├── help.py
│   └── new.py
├── implementations/
│   └── (OpenAI provider package)
├── skills/
│   ├── __init__.py
│   ├── agents/                ← Agent management skill
│   │   ├── SKILL.md
│   │   ├── components/
│   │   │   └── agent_panel.py
│   │   └── ...
│   ├── chat/                  ← AI chat workspace tab
│   │   ├── SKILL.md
│   │   ├── __init__.py
│   │   ├── chat_display.py
│   │   ├── chat_input.py
│   │   ├── chat_manager.py
│   │   ├── chat_tab.py
│   │   ├── commands.py
│   │   ├── command_palette.py
│   │   ├── command_suggester.py
│   │   ├── file_palette.py
│   │   ├── file_suggester.py
│   │   ├── stream_section.py
│   │   ├── tool_format.py
│   │   └── chat.tcss
│   ├── database/              ← DB query editor skill
│   │   ├── SKILL.md
│   │   ├── __init__.py
│   │   ├── core/
│   │   │   ├── __init__.py
│   │   │   ├── db_connections.py
│   │   │   └── providers/
│   │   │       ├── __init__.py
│   │   │       └── sqlite.py
│   │   ├── db_panel.py
│   │   ├── connection_form.py
│   │   ├── query_editor.py
│   │   ├── services.py
│   │   └── database.tcss
│   ├── git/                   ← Git workflow skill
│   │   ├── SKILL.md
│   │   ├── components/
│   │   │   └── git_panel.py
│   │   ├── scripts/
│   │   │   ├── status.py
│   │   │   ├── checkpoint.py
│   │   │   ├── diff_summary.py
│   │   │   ├── log.py
│   │   │   └── branch_info.py
│   │   └── git.tcss
│   ├── terminal/              ← Embedded terminal workspace tab
│   │   ├── SKILL.md
│   │   ├── __init__.py
│   │   ├── terminal.py
│   │   ├── terminal_handler.py
│   │   └── terminal.tcss
│   └── workspace_docs/       ← Core-systems documentation skill
│       ├── SKILL.md
│       ├── docs/
│       └── scripts/
│           └── read_doc.py
├── tests/
│   ├── test_agent.py
│   ├── test_agent_registry.py
│   ├── test_bootstrap.py
│   ├── test_chat_display.py
│   ├── test_chat_display_system.py
│   ├── test_chat_input.py
│   ├── test_chat_manager.py
│   ├── test_chat_panel.py
│   ├── test_command_dispatch.py
│   ├── test_command_palette.py
│   ├── test_commands.py
│   ├── test_command_suggester.py
│   ├── test_config.py
│   ├── test_config_panel.py
│   ├── test_database.py
│   ├── test_db_connections.py
│   ├── test_events.py
│   ├── test_file_browser.py
│   ├── test_file_editor.py
│   ├── test_git_skill.py
│   ├── test_icons.py
│   ├── test_leader.py
│   ├── test_pane_tree.py
│   ├── test_paths.py
│   ├── test_provider_base.py
│   ├── test_provider_ollama.py
│   ├── test_provider_registry.py
│   ├── test_sidebar.py
│   ├── test_skills.py
│   ├── test_terminal.py
│   ├── test_terminal_preservation.py
│   ├── test_theme_persistence.py
│   ├── test_tools.py
│   ├── test_tools_read_file.py
│   ├── test_tools_run_command.py
│   ├── test_tools_skill.py
│   ├── test_tools_write_file.py
│   ├── test_tools_edit_file.py
│   ├── test_tree_merged.py
│   ├── test_tree.py
│   ├── test_vault.py
│   ├── test_widgets.py
│   ├── test_workspace.py
│   └── test_workspace_tabs.py
├── tools/
│   ├── __init__.py
│   ├── activate_skill.py
│   ├── read_file.py
│   ├── run_command.py
│   ├── run_skill.py
│   └── write_file.py
│   ├── edit_file.py
├── ui/
│   ├── __init__.py
│   ├── sidebar/
│   │   ├── __init__.py
│   │   ├── registry.py
│   │   ├── sidebar.py
│   │   └── panels/
│   │       ├── __init__.py
│   │       ├── config_panel.py
│   │       ├── file_browser.py
│   │       └── vault_panel.py
│   ├── tree/
│   │   ├── __init__.py
│   │   ├── tree.py
│   │   └── tree_row.py
│   ├── widgets/
│   │   ├── __init__.py
│   │   ├── commands_help.py
│   │   ├── confirm_modal.py
│   │   ├── input_modal.py
│   │   └── leader_overlay.py
│   └── workspace/
│       ├── __init__.py
│       ├── file_edit_handler.py
│       ├── file_editor.py
│       ├── tabs.py
│       ├── welcome_view.py
│       └── workspace.py
├── utils/
│   ├── __init__.py
│   ├── dom_id.py
│   └── icons.py
├── config/                    ← Default config fragments
└── .agents/                   ← Agent/skill configuration (project-local)
```

---

## 6. Key Architectural Patterns

### 6.1 `AppContext` — Service Locator

```python
@dataclass
class AppContext:
    config: Config
    skills: SkillManager
    database: DatabaseManager
    leader: LeaderRegistry
    working_directory: str
```

Created once at bootstrap. Holds references to services components need to *query*
at runtime. Tool registry and skill manager remain module-level singletons — their
`@register_tool()` / `SkillManager()` patterns are essential for self-registration-
at-import extensibility. The vault stays module-level (global session state).

`AppContext` is a service locator, not a strict DI container.

### 6.2 Unified Chat Streaming

One `ChatManager` class. Always streams via `Agent.stream_chat()`. The
`ChatDisplay` widget provides a streaming API: `add_user_message()`,
`begin_assistant_turn()`, `add_section()`, `update_section()`, `finalize_turn()`.
No more `MsgBox`/`StreamingMsgBox` duplication.

**Thinking sections use plain `Static` text** (no markdown parsing) to
reduce re-rendering overhead during streaming.  Reasoning models emit
rapid thinking tokens that previously caused lag when each chunk triggered
a full markdown re-render of the entire accumulated thinking text.  Response
and tools sections continue to use `Markdown` for rich formatting.

**Auto-scroll** — the `ChatDisplay` schedules a scroll-to-bottom after
every content addition or update (`add_user_message`, `begin_assistant_turn`,
`add_section`, `update_section`, `add_system_message`).  The scroll is
deferred by ~1 frame using `set_timer(1/60, ...)` to allow Textual's
layout pass to recalculate the virtual size before the scroll fires.

### 6.3 Bootstrap Module

```python
class Bootstrap:
    def run(self) -> tuple[AppContext, list[str]]:
        config = self._init_config()
        skills = self._discover_skills(config)
        self._load_tools(config, skills)
        database = self._init_database(config)
        leader = self._init_leader(skills)
        css = self._collect_css(skills)
        return AppContext(...), css
```

Steps 1–13 of the startup sequence live here. `main.py` just parses args,
calls `Bootstrap.run()`, and mounts the app.

### 6.4 API Key Resolution

Providers resolve keys directly from the vault (no separate `keys.py` module).
`OllamaProvider` calls `vault.get_credential()` on demand. If the vault is locked,
an async unlock flow is triggered.

#### 6.5 Skill Loading

Skills are discovered by `SkillManager.scan()` which scans the three-tier
`skills/` directories for `SKILL.md` manifests.  Skills with `__init__.py`
are loaded via `importlib.util.spec_from_file_location`, setting `__path__` and
`__package__` to ensure sub-imports work correctly regardless of which tier
the skill lives in.  Skills without `__init__.py` (ecosystem / Anthropic spec)
are discovered and their body is available for agent activation, but no Python
code runs at import time.

The Workspace project root is added to `sys.path` before skills load, guaranteeing
that `from core.config import Config` (and similar) works from any skill.

Later-tier skills override earlier-tier skills with the same directory name.
Project-level skills at `{wd}/.agents/skills/` override user-level skills at
`~/.agents/skills/`, which override bundled skills at `{workspace_dir}/skills/`.

#### 6.6 CSS Collection

`paths.collect_tcss(wd)` gathers CSS from all three tiers (core UI, user themes,
project `.agents/`) plus any skill `components/` directories. Called once at bootstrap.

---

## 7. Implementation Steps

### Step 1: Project Scaffolding ✅

 - pyproject.toml, directory skeleton, conftest.py
 - **COMPLETE**

### Step 2: Provider Base Protocol ✅

 - `core/providers/base.py` — BaseProvider protocol, dataclasses
 - Added `thinking` field for reasoning-capable models
 - **COMPLETE**

### Step 3: Path System ✅

 - `core/paths.py` — 3-tier resolution, `workspace_dir()`, `agents_dir()`, `resolve()`
 - **COMPLETE**

### Step 4: Config Manager ✅

 - `core/config.py` — layered JSON, dot-path, diff-save, registered defaults
 - **COMPLETE**

### Step 5: Password Vault ✅

 - `core/vault.py` — Fernet + PBKDF2, credentials + secure notes, concurrent unlock
 - **COMPLETE**

### Step 6: Ollama Provider ✅

 - `core/providers/ollama.py` — implements BaseProvider, vault key resolution
 - **COMPLETE**

### Step 7: Recursive Pane Tree + Workspace ✅

 - `core/pane_tree.py` — LeafPane, SplitPane, split/close/find_neighbor/get_layout
 - `ui/workspace/workspace.py` — Workspace widget, PaneContainer, vim navigation, leader chords
 - **COMPLETE**

### Step 8: Tool Registry ✅

 - `core/tools.py` — `@register_tool()`, tag grouping, enable/disable, reset
 - **COMPLETE**

### Step 9: Skill System ✅

 - `core/skills.py` — SKILL.md discovery, YAML frontmatter, 3-tier override, XML catalog
 - **COMPLETE**

### Step 10: Agent ✅

 - `core/agent.py` — system prompt builder, tool-calling loop, streaming, abort
 - **COMPLETE**

### Step 11: Database ✅

 - `core/database.py` — SQLiteProvider, connection manager, CRUD, agent seeding
 - Cosmos provider dropped per §3.2
 - **COMPLETE**

### Step 12: Leader Registry + Slash Commands ✅

 - `core/leader.py` — LeaderNode tree, register_submenu/action
 - `core/commands.py` — CommandBase, tiered discovery
 - **COMPLETE**

### Step 13: Bootstrap + AppContext ✅

 - `context.py`, `bootstrap.py` — full bootstrap flow
 - CSS collection via `paths.collect_tcss()`
 - **COMPLETE**
 - **DONE:** `core/themes.py` (3-tier theme discovery), **DEFERRED:** `core/git.py` (checkpoint utilities)

### Step 14: Shared UI Widgets ✅

 - `ui/widgets/` — InputModal, CommandsHelp, LeaderOverlay, ConfirmModal
 - **COMPLETE**
 - **DEFERRED:** FormModal (structured input with labeled fields)

### Step 15: Chat UI ✅

 - ``skills/chat/`` — ChatInput, ChatDisplay (Tree-based streaming), ChatManager, ChatPanel
 - ChatDisplay uses Tree widget with content nodes; streaming via section updates
 - Thinking sections use Static (plain text) for performance; other sections use Markdown
 - Auto-scroll to bottom: deferred ~1 frame after content changes for layout recalc
 - 46 tests across chat components
 - **COMPLETE**

### Step 15c: Tree CSS Hide/Show ✅

 - Tree mounts all rows once; expand/collapse toggles `-hidden` CSS class
 - No DOM remounts for expand/collapse; `PersistentMarkdown` removed

### Step 15d: Tree User Collapse Persistence ✅

 - Tree tracks `_user_collapsed: set[str]` — IDs of branches the user has manually collapsed
 - `collapse_node()` adds to `_user_collapsed`; `expand_node()` removes from it
 - `restore_expand_state()` expands all branch nodes except user-collapsed ones
 - `expand_all()` clears `_user_collapsed` (user intent: show everything)
 - `set_root()` clears `_user_collapsed` (fresh tree)
 - `rebuild()` preserves user collapse state — ChatDisplay uses `restore_expand_state()` instead of `expand_all()`
 - Stale IDs (nodes removed from the tree) are cleaned up during `restore_expand_state()`
 - 9 new tests for user collapse persistence and `restore_expand_state()`
 - **COMPLETE**

### Step 16: Workspace + Terminal ✅

#### 16a: Terminal View

 - `skills/terminal/terminal.py` — `TerminalView` wraps `textual_terminal.Terminal`
   with lifecycle management, working directory context, `WorkspaceEvent` integration
 - `skills/terminal/terminal_handler.py` — leader chord handler for `terminal.open`
 - `core/terminal_passthrough.py` — key passthrough registry
 - Leader chord: `Ctrl+Space t o` opens terminal in focused pane

#### 16b: Terminal Preservation Across Workspace Splits

When the workspace is reorganised (split / close), the terminal's PTY emulator
**and visible output** are preserved across the DOM rebuild so the shell session
survives and the user doesn't lose their terminal history.

The challenge: Textual widgets cannot be remounted once removed from the DOM.
When `recompose()` destroys the widget tree, the old `PtyTerminal` widget (and its
render state) goes away. The previous emulator-only transfer kept the shell process
alive, but all previous output was lost — the new terminal started with a blank screen.

The solution: the pyte `Screen` (character buffer + cursor state) and
`TerminalDisplay` (rendered Rich Text lines) held by `PtyTerminal` are **plain
Python objects**, not Textual widgets. They can be captured before the DOM rebuild
and injected into the freshly-created `PtyTerminal` after recomposition.

Three preservation mechanisms:

1. **`_preserving` flag** — prevents `on_unmount` from killing the PTY process
   during a temporary DOM removal.
2. **`TerminalSnapshot` dataclass** — bundles the live emulator, pyte screen,
   and rendered display so they travel together through
   `SavedTab → restore_state → on_mount`.
3. **`_inherited_snapshot`** — on the new `TerminalView`, `on_mount()` adopts
   the emulator **and** restores the screen/display by replacing the
   newly-created `PtyTerminal`'s defaults:
   - `_screen` ← snapshot's screen (character buffer + cursor)
   - `stream.screen` ← same screen (keeps `pyte.Stream` feeding into it)
   - `_display` ← snapshot's display (Rich Text lines for immediate render)
   - `ncol`/`nrow` ← saved screen dimensions
   - `refresh()` called to show the restored content immediately

Flow during a workspace split:

```
_save_pane_tab_states()
  └─ WorkspaceTabs.save_state()
       └─ TerminalView.detach_emulator()
            ├─ captures emulator, screen, display → TerminalSnapshot
            ├─ cancels recv task
            └─ disconnects old PtyTerminal from emulator

_mark_terminals_preserving()
  └─ sets _preserving=True on all TerminalViews

await recompose()   ← DOM rebuild destroys old widgets

_restore_pane_tab_states()
  └─ WorkspaceTabs.restore_state()
       └─ creates new TerminalView via content_factory()
       └─ sets new_tv._inherited_snapshot = saved snapshot
       └─ mounts new widget
           └─ TerminalView.on_mount()
                ├─ adopts emulator (keeps PTY process alive)
                ├─ restores screen into PtyTerminal._screen
                ├─ restores display into PtyTerminal._display
                └─ calls refresh() → user sees previous output
```

Key classes and their roles:

| Class | Role |
|---|---|
| `TerminalSnapshot` | Dataclass bundling `emulator`, `screen`, `display` |
| `TerminalView.detach_emulator()` | Captures `PtyTerminal._screen` + `_display` alongside the emulator |
| `TerminalView._inherited_snapshot` | Set by `restore_state()`; consumed in `on_mount()` |
| `SavedTab.inherited_snapshot` | Carries the snapshot through the recomposition pipeline |
| `Workspace._cleanup_orphaned_terminals()` | Calls `snapshot.stop_emulator()` for closed-pane terminals |

Orphan cleanup: if a pane containing a terminal is closed (not just split),
the preserved emulator's PTY process must be explicitly killed since `on_unmount`
was skipped (`_preserving=True`). `TerminalSnapshot.stop_emulator()` handles this.

 **COMPLETE**

### Step 17: Sidebar Components ✅

 - `ui/sidebar/` — registry, Sidebar, SidebarContainer, panels/vault_panel, chat_panel, config_panel, file_browser
 - File browser uses Tree with lazy loading (`NodeNeedsChildren`) and action buttons
 - **COMPLETE**
 - **DONE:** ``skills/database/`` — DB sidebar tab + connection form + query editor (see Step 21)

### Step 18: main.py (wires everything) ✅

 - `main.py` — `WorkspaceApp` class with leader bindings, compose, vault/chat wire-up
 - No separate `app.py` — all wiring lives in `main.py`
 - **COMPLETE** — all wiring, CSS polish, theme registration, and smoke testing verified

### Step 20: File Browser + Workspace Tabs ✅

Phase 1: Icon Registry ✅
 - `utils/icons.py` — Nerd Font icon constants, `get_file_icon()` extension mapping

Phase 2: TreeRow + Action Buttons + Lazy Loading ✅
 - `TreeNode` has `loaded` field for lazy children
 - `TreeRow` hosts action buttons + branch toggle
 - `NodeNeedsChildren` message for on demand loading
 - `Tree._refresh_visibility()` toggles CSS classes instead of DOM remounts

Phase 3: WorkspaceTabs ✅
 - `ui/workspace/tabs.py` — `WorkspaceTabs` with `TabInfo`, `SavedTab`, `SavedTabState`
 - `open_tab()`, `close_tab()`, `switch_tab()` with `TabSwitched`/`TabClosed` messages
 - State persistence across recomposition (content factories, terminal snapshots)

Phase 4: File Browser Panel ✅
 - `ui/sidebar/panels/file_browser.py` — lazy directory tree with action buttons
 - Registered as sidebar tab with `@register_sidebar_tab`
 - Posts `WorkspaceEvent("files.open")`, `WorkspaceEvent("files.new_file")`, etc.
 - Show-hidden toggle button (``EYE_OFF``/``EYE`` icon) controls whether dotfiles/dotdirs appear
 - Sorting uses ``name`` from node data (not the icon-prefixed ``label``) for correct alphabetical order
 - ``_IGNORED_NAMES`` always filtered regardless of hidden toggle; ``startswith(".")`` entries respect the toggle

Phase 5: File Editor + Workspace Integration ✅
 - `ui/workspace/file_editor.py` — `FileEditor` reads/writes files in a tab
 - `ui/workspace/file_edit_handler.py` — routes `files.open` events to tabs
 - `ui/workspace/welcome_view.py` — landing page for empty panes
 - `ui/workspace/workspace.py` — handles `WorkspaceEvent` for file opening

 **COMPLETE**

### Step 19: Bundled Content + E2E ✅

 - Git skill: **DONE** (see Step 22)
 - E2E tests: **DONE** — full conversation with tool calls, vault unlock flow, git checkpoint
 - Theme registration: **DONE** — dynamic theme switching via config
 - App-wide CSS: **DONE** — visual polish complete
 - Smoke test: **DONE** — full app launch and basic interaction verified
 - **REMAINING:** Bundled content skills (coding, todo, brave_search)

### Step 21: Database Query Editor ✅

Phase 1: Core — Connection Management (`core/db_connections.py`) ✅
 - `FormField` dataclass — describes fields for the connection form
 - `ConnectionInfo` dataclass — represents a saved connection
 - `QueryResult` dataclass — result of executing a SQL query
 - `DBProvider` abstract class — provider interface with `form_fields()`, `connect()`, `list_tables()`, etc.
 - `SQLiteProvider` — concrete implementation for SQLite
 - `ConnectionManager` — CRUD for connections (backed by layered config), connect/disconnect lifecycle, browse/execute
 - Connections stored in config under `db.connections`; sensitive fields in vault as `dbconn:{id}`
 - Config defaults registered: `db.connections = []`, `db.default_page_size = 200`

Phase 1b: Config integration ✅
 - `context.py` — added `db_connections: ConnectionManager` field
 - `bootstrap.py` — added `_init_db_connections()` phase
 - No changes to `core/database.py` (connections are in config, not DB tables)

Phase 2: UI — Connection Form Modal (``skills/database/connection_form.py``) ✅
 - `ConnectionFormModal` — dynamic form driven by `provider.form_fields()`
 - Provider type dropdown auto-generates form fields
 - File-type fields get a Browse button
 - Test Connection button validates parameters
 - Save creates/updates connection via ConnectionManager

Phase 3: UI — DB Sidebar Panel (`ui/sidebar/panels/db_panel.py`) ✅
 - `DBPanel` — registered as sidebar tab `db` with 󰆼 icon
 - Tree of connections, lazy-loaded (tables/views/triggers expand on demand)
 - Action buttons per connection: 🔍 open query, 🖉 edit, 🗑 delete, ⟳ refresh
 - Table rows have a 📋 button that opens a SELECT * pre-filled query
 - `+ Add Connection` button opens ConnectionFormModal
 - `db.open_query` WorkspaceEvent posted to open query editor in workspace

Phase 4: UI — Query Editor (`ui/workspace/query_editor.py`) ✅
 - `QueryEditor` — split-pane widget (query input above, results below)
 - Header shows connection name + ▶ Run button
 - `TextArea` with SQL syntax highlighting for query input
 - `DataTable` for results with column headers
 - Offset-based pagination: Prev/Next buttons, row count display
 - DML/DDL results show rows affected instead of a data table
 - Ctrl+Enter keybinding to execute query
 - Pre-filled queries from table browser auto-execute after mount

Phase 5: Integration ✅
 - ``skills/database/db_panel.py`` — event handler ``db.open_query`` opens QueryEditor in workspace tabs
 - `ui/sidebar/panels/__init__.py` — imports `db_panel` for registration
 - CSS files: `db_panel.tcss`, `connection_form.tcss`, `query_editor.tcss`
 - 46 unit tests in `tests/test_db_connections.py`

### Step 22: Git Skill ✅

Git integration implemented as a **skill** to keep the agent tool
surface at 5 tools. The agent learns git expertise by activating the skill's
SKILL.md body, then uses `run_command` and `run_skill` with the existing tools.

Phase 1: Core — Skill `components/` auto-discovery ✅
 - `core/skills.py` — added `get_skill_components_dirs()` method
 - `bootstrap.py` — `_load_sidebar_panels()` now also imports from skill `components/` directories
 - Skills can register sidebar panels, event handlers, leader chords, and config defaults
   using the same decorator pattern — no new `__init__.py` required
 - 3 new tests in `test_skills.py::TestComponentsDirs`

Phase 2: Git SKILL.md ✅
 - `skills/git/SKILL.md` — comprehensive git expertise for the agent
 - Teaches the agent to use `run_command` for simple git ops and `run_skill` for complex scripts
 - Includes checkpoint protocol, commit conventions, branch strategy, safety rules
 - Zero new agent tools — the agent reads this via `activate_skill` on demand

Phase 3: Git scripts ✅
 - `skills/git/scripts/status.py` — detailed repo status (branch, tracking, stash, file groups)
 - `skills/git/scripts/checkpoint.py` — create/list/restore WIP checkpoints (tagged `workspace-checkpoint/`)
 - `skills/git/scripts/diff_summary.py` — staged/unstaged/untracked change summary
 - `skills/git/scripts/log.py` — formatted commit history with branch info
 - `skills/git/scripts/branch_info.py` — current branch, tracking, remotes, tags
 - All scripts handle non-git-repo gracefully

Phase 4: Git sidebar panel ✅
 - `skills/git/components/git_panel.py` — GitPanel registered as sidebar tab
 - Tree display: branch + tracking info, staged/unstaged/untracked files, recent commits, stashes
 - Clicking a file node opens it for editing (same `files.edit` event pattern)
 - Refresh button to rescan the repo
 - Config defaults: `git.log_count`, `git.auto_refresh`
 - `skills/git/git.tcss` — panel styling

Phase 5: Leader chords + event handlers ✅
 - `Ctrl+Space g` — Git submenu
 - `Ctrl+Space g s` — Status (`git.status` event)
 - `Ctrl+Space g c` — Checkpoint (`git.checkpoint` event, prompts for message)
 - `Ctrl+Space g l` — Log (`git.log` event)
 - `Ctrl+Space g d` — Diff (`git.diff` event)
 - `Ctrl+Space g r` — Refresh (`git.refresh` event)

Phase 6: Tests ✅
 - 17 tests in `tests/test_git_skill.py` covering all scripts
 - Repo initialization, clean/dirty states, non-git-repo handling
 - Checkpoint create/list/lifecycle tests

**Design Decision — Skill over Plugin for Git (§3.8):** The git integration
uses a skill rather than a plugin to avoid adding new agent tools. The 5 existing
tools (`activate_skill`, `edit_file`, `read_file`, `run_command`, `run_skill`, `write_file`) are
sufficient — the agent activates the git skill to learn git expertise, then uses
`run_command` for simple operations and `run_skill` + scripts for complex ones.
This keeps the tool surface small, which is critical for LLM tool-selection accuracy.

---

### Step 24: Prompt Registry → Agents Skill + Provider Registry ✅

**Phase 1 (COMPLETE):** Replace hard-coded system prompts with a database-backed
prompt registry supporting `{{key}}` template substitution with dynamic variable
providers.  Deprecates the `agents` table (absorbed into `prompts` table).

**Phase 2 (COMPLETE):** Extend the prompt registry into an **Agents skill** with
per-agent model, provider, tools, skills, temperature, and max_tool_iterations.
Replace the single `ctx.provider` with a **Provider Registry** supporting named
provider instances.  Add `/agent` slash command for mid-conversation switching.
See §25 for the full design.

Key changes:
- `core/prompt_registry.py` → `core/agent_registry.py` (AgentManager)
- `core/providers/registry.py` — ProviderRegistry (new)
- `skills/prompts/` → `skills/agents/` (renamed, new SKILL.md + panel)
- `ctx.provider` → `ctx.providers` (ProviderRegistry, with backward-compat property)
- `ctx.prompts` → `ctx.agents` (AgentManager, with deprecated alias)
- `session.provider` → `session.default_provider`
- `prompt.default_id` → `agent.default_id`
- Agent table schema: added provider, tools, skills, temperature, max_tool_iterations
- `cmd/agent.py` — `/agent` slash command for agent switching

**Status: COMPLETE**

---

### Step 23: Merge Plugins into Skills ✅

Eliminate the separate `plugins/` concept by merging all plugins into the skills
system. Skills and plugins were functionally identical — both discovered via
SKILL.md, both used 3-tier paths, both registered UI components. The git skill
already demonstrated the merged concept (agent knowledge + UI components).

The ``skill`` name is retained for ecosystem compatibility with Anthropic's
skill specification (ClaudeCode, Codex), so users can install ecosystem skills
without modification.

Phase 1: Move plugin directories under `skills/` ✅
 - `plugins/chat/` → `skills/chat/`
 - `plugins/terminal/` → `skills/terminal/`
 - `plugins/database/` → `skills/database/`
 - Delete `plugins/` directory and `plugins/__init__.py`

Phase 2: Rewrite all `from plugins.X` imports to `from skills.X` ✅
 - Across moved skill files (~30 internal references)
 - Across all test files (~25 references)
 - `bootstrap.py` docstrings/comments

Phase 3: Upgrade `core/skills.py` — unified skill loading ✅
 - `__init__.py` is **optional** — test for it, use if present, skip if not
 - Ecosystem skills (Anthropic spec): no `__init__.py` → discovered, body available, scripts runnable
 - UI skills: have `__init__.py` → full `importlib` load with `__path__`/`__package__` handling
 - Add `get_skill_init_dirs()` — returns skill dirs containing `__init__.py`
 - Add `SKILL_SERVICES` convention (replaces `PLUGIN_SERVICES`)
 - Import error isolation for all skill Python loading

Phase 4: Rewrite `bootstrap.py` ✅
 - Remove `_load_plugins()` phase entirely
 - Expand skill loading to handle `__init__.py` entry points + `SKILL_SERVICES`
 - Register `skills` as package in `sys.modules` (replaces `plugins` package)
 - Services from `SKILL_SERVICES` wired into AppContext

Phase 5: Simplify `core/paths.py` ✅
 - Remove `discover_plugins()` and `collect_plugin_tcss()`
 - Remove `skip_plugins` parameter from `_find_tcss()` and `collect_tcss()`
 - CSS collection walks everything uniformly (skills/ already included)

Phase 6: Update tests ✅
 - All existing tests updated with new import paths
 - New tests for optional `__init__.py` loading, `SKILL_SERVICES`, import error isolation

**Design Decision — Unified Skill Concept:** Skills are the sole extension
mechanism. A skill is a directory with a `SKILL.md` manifest. It can optionally
have: agent knowledge (body), `__init__.py` (Python entry point for UI),
`components/` (flat UI modules), `scripts/` (agent-runnable), `tools/` (agent
tools), `cmd/` (slash commands), and `SKILL_SERVICES` (AppContext injection).
Ecosystem skills without `__init__.py` work out of the box — they are discovered
and their body is available for agent activation.

---

## 8. Remaining Work

| Item | Status | Notes |
|---|---|---|
| `core/themes.py` — 3-tier theme discovery | **DONE** | Subsumed by theme registration |
| `core/git.py` — git checkpoint utilities | **DONE** | Replaced by git skill (Step 22) |
| `FormModal` — structured input with labeled fields | **DONE** | `ConnectionFormModal` in Step 21 |
| ``skills/database/`` — DB sidebar tab | **DONE** | Step 21 |
| App-wide CSS polish | **DONE** | Visual refinement complete |
| Theme registration | **DONE** | Dynamic theme switching via config |
| Smoke test | **DONE** | Full app launch + basic interaction verified |
| E2E tests | **DONE** | Full conversation with tool calls, vault unlock, git checkpoint |
| Default themes | **DONE** | Theme switching functional |
| Bundled skills (coding, todo, brave_search) | **NOT STARTED** | Step 19 — git skill done in Step 22 |
| Agent registry + Provider registry | **DONE** | See §25 — replaced PromptManager with AgentManager + ProviderRegistry |

---

## 9. Test Inventory

| Test file | Area | Count |
|---|---|---|
| `test_agent.py` | Agent, streaming, tool calling | — |
| `test_agent_registry.py` | AgentManager CRUD, render, resolve helpers, migration | 58 |
| `test_bootstrap.py` | Full bootstrap flow | — |
| `test_chat_display.py` | ChatDisplay streaming, section updates, Static thinking, auto-scroll | 36 |
| `test_chat_display_system.py` | System-level chat tests | 10 |
| `test_chat_input.py` | ChatInput widget | — |
| `test_chat_manager.py` | ChatManager orchestration | — |
| `test_chat_panel.py` | ChatPanel sidebar tab | — |
| `test_command_dispatch.py` | Slash command routing | — |
| `test_command_palette.py` | CommandPalette overlay | — |
| `test_commands.py` | Command loader | — |
| `test_command_suggester.py` | Autocomplete | — |
| `test_config.py` | Config get/set/defaults | — |
| `test_config_panel.py` | ConfigPanel editing | — |
| `test_database.py` | CRUD, provider swapping | — |
| `test_db_connections.py` | Connection manager, providers, pagination | 49 |
| `test_events.py` | WorkspaceEvent dispatch | — |
| `test_file_browser.py` | File tree browser | — |
| `test_file_editor.py` | File editor tab | — |
| `test_git_skill.py` | Git skill scripts (status, checkpoint, diff, log, branch) | 17 |
| `test_icons.py` | Icon mapping | — |
| `test_leader.py` | Leader tree, action dispatch | — |
| `test_pane_tree.py` | Pure data model ops | — |
| `test_paths.py` | 3-tier path resolution | — |
| `test_provider_base.py` | BaseProvider protocol | — |
| `test_provider_ollama.py` | Ollama provider | — |
| `test_provider_registry.py` | ProviderRegistry, lazy creation, type registration | 15 |
| `test_sidebar.py` | Sidebar visibility, panels | — |
| `test_skills.py` | Skill discovery, catalog, components dirs | 50 |
| `test_terminal.py` | TerminalView, handler, passthrough | — |
| `test_terminal_preservation.py` | Screen/display preservation across splits | — |
| `test_theme_persistence.py` | Theme save/load | — |
| `test_tools.py` | Tool registry | — |
| `test_tools_read_file.py` | Read file tool | — |
| `test_tools_run_command.py` | Run command tool | — |
| `test_tools_skill.py` | Skill tools | — |
| `test_tools_edit_file.py` | Edit file tool (search/replace) | — |
| `test_tools_write_file.py` | Write file tool | — |
| `test_tree_merged.py` | Tree merged tests | — |
| `test_tree.py` | Tree widget | — |
| `test_vault.py` | Encrypt/decrypt, lock/unlock | — |
| `test_widgets.py` | InputModal, ConfirmModal | — |
| `test_workspace.py` | Workspace split/close/navigate | — |
| `test_workspace_tabs.py` | WorkspaceTabs open/close/switch | — |
| `test_text_editor_modal.py` | TextEditorModal construction, language, read-only | 4 |

**Total: ~44 test files**
---

## 25. Agents Skill + Provider Registry

### 25.1 Overview

The **Agents skill** replaces the former **Prompts skill** and `PromptManager`.
Where the prompt registry managed only system prompt templates, the agent
registry manages full agent *definitions* — each of which is a prompt
template **plus** optional overrides for model, provider, tool permissions,
skill filtering, temperature, and max tool iterations.

Concurrently, the **Provider Registry** replaces the single `ctx.provider`
field with a named-instance model.  Multiple provider instances (e.g.
`ollama-local`, `ollama-cloud`, `openai-main`) can be defined in config, and
each agent can route through a specific named instance.

### 25.2 Provider Registry

**File:** `core/providers/registry.py`

Provider instances are defined in config under `providers.instances`:

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
  },
  "session": {
    "default_provider": "ollama-cloud"
  }
}
```

Key methods:

| Method | Purpose |
|---|---|
| `register_type(name, cls)` | Register a provider class for a type name |
| `get(name)` | Get a named provider instance (lazily created) |
| `get_default()` | Get the default provider (from `session.default_provider`) |
| `list_instances()` | List configured instance names |
| `has_instance(name)` | Check if an instance is configured |

Provider types auto-register at import time (e.g. `ollama.py` exposes a
`register(registry)` function called by bootstrap).

### 25.3 Agent Registry

**File:** `core/agent_registry.py`

Replaces `core/prompt_registry.py`.  The `AgentManager` class extends the
former `PromptManager` with:

| Field | Purpose | Default if empty |
|---|---|---|
| `model` | Override the LLM model | Session default (`session.model`) |
| `provider` | Named provider instance | Session default (`session.default_provider`) |
| `tools` | JSON list of allowed tool names/tags | All tools |
| `skills` | JSON list of skill names to activate | All skills (via `{{skills}}`) |
| `temperature` | Sampling temperature override | Provider default |
| `max_tool_iterations` | Tool-loop safety limit | 10 |

Resolve helpers provide clean access:

```python
model = agents.resolve_model(agent_def, ctx)
provider_name = agents.resolve_provider_name(agent_def, ctx)
tool_filter = agents.resolve_tools(agent_def)       # None = all
skill_filter = agents.resolve_skills(agent_def)      # None = all
temp = agents.resolve_temperature(agent_def)         # None = default
mti = agents.resolve_max_tool_iterations(agent_def) # None = default
```

### 25.4 Database Schema

The `agents` table replaces both the legacy `agents` table (deprecated) and
the `prompts` table:

```sql
CREATE TABLE IF NOT EXISTS agents (
    id                  TEXT PRIMARY KEY,
    name                TEXT NOT NULL,
    description         TEXT NOT NULL DEFAULT '',
    template             TEXT NOT NULL,
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

Migration: On first run, `DatabaseManager._migrate_agents_table()` detects
the old `agents` table (by checking for `system_prompt` column) and renames
it to `agents_legacy`.  Then `AgentManager._migrate_legacy_tables()` copies
rows from both `agents_legacy` and `prompts` into the new `agents` table
and drops the legacy tables.

### 25.5 Agent Switching

The `/agent` slash command (`cmd/agent.py`) allows mid-conversation
switching of the active agent.  Usage:

- `/agent` — show current agent and list available agents
- `/agent <id>` — switch the current chat to use the named agent

The command re-wires the `ChatManager` by calling `_wire_agent(ctx)`,
which resolves the new agent's prompt, provider, model, tools, and skills.

### 25.6 Sidebar Panel

`skills/agents/components/agent_panel.py` — `AgentPanel` replaces the
former `PromptPanel`.  Each agent node in the tree shows:

- Name and scope
- Model and provider overrides (if set)
- Template preview
- Tools, skills, temperature, max_tool_iterations (if set)

The **+ New** button creates an agent via a multi-step modal flow:
name → provider → model → template.

### 25.7 Config Changes

| Old key | New key |
|---|---|
| `session.provider` | `session.default_provider` |
| `prompt.default_id` | `agent.default_id` |
| `prompt.inline_suggest_id` | `agent.inline_suggest_id` |
| *(none)* | `providers.instances` |
| *(none)* | `session.max_tool_calls` |

The `{{provider}}` template variable is now available, resolving to the
default provider instance name.

`session.max_tool_calls` (default: 10) controls the number of tool-calling
round-trips between progress checkpoints.  Every *N* rounds the agent
pauses to give the user a progress update (a forced text-only call
without tools), then continues working with a reset counter.  There is
no hard stop — the loop only ends when the LLM naturally produces a
final text response.  Individual agent definitions can override this
via their `max_tool_iterations` field.

### 25.8 Backward Compatibility

- `AppContext.provider` is preserved as a **property** that delegates to
  `ctx.providers.get_default()`.  Existing code still works.
- `AppContext.prompts` is set to the same `AgentManager` instance as
  `ctx.agents` during bootstrap.  Code referencing `ctx.prompts` still works
  (deprecated).
- Old `DatabaseManager` agent CRUD methods (`create_agent`, `get_agent`,
  `list_agents`, `delete_agent`, `seed_agents`) emit `DeprecationWarning`
  but still function, writing to the new `agents` table.