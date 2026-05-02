# Cody Rewrite — Design Document

## 1. Overview

Cody is a Textual-based TUI application providing an AI coding assistant. It supports
Ollama (local) and OpenAI as LLM backends, features a plugin architecture via "skills",
and includes an encrypted password vault, multi-connection database management, git
checkpointing, and a keyboard-driven leader menu system.

This document captures the broad-strokes architecture of the current codebase and
proposes a simplified target architecture for the rewrite.

---

## 2. Current Architecture — What We Have

### 2.1 High-Level Component Map

```
main.py  (entry point, app definition, orchestration)
├── utils/
│   ├── cfg_man.py          ← Config manager (layered JSON, dot-path, diff-save)
│   ├── password_vault.py   ← Encrypted credential store (Fernet + PBKDF2)
│   ├── skills.py           ← Skill discovery & catalog (SKILL.md, 3-tier search)
│   ├── agent.py            ← LLM agent (system prompt, tool-calling loop, streaming)
│   ├── tool.py             ← Tool registry (register, tag, enable/disable, execute)
│   ├── db.py               ← Database manager (SQLite + Cosmos, chats/agents/todos)
│   ├── paths.py            ← 3-tier path resolution ($CODY_DIR, ~/.agents, project)
│   ├── leader_registry.py  ← Leader menu chord tree (core + skill-extensible)
│   ├── cmd_loader.py       ← Slash-command loader (CommandBase subclasses)
│   ├── fs.py               ← File utilities (CSS discovery, folder loading)
│   ├── theme_man.py        ← Theme discovery (3-tier + legacy dir)
│   ├── git.py              ← Git utilities (checkpoint, revert, status, stash)
│   ├── interface_defaults.py ← Default UI config fragment
│   ├── providers/
│   │   ├── __init__.py     ← Provider registry + config defaults
│   │   ├── base.py         ← BaseProvider protocol, ChatResponse, StreamChunk
│   │   ├── ollama.py       ← Ollama provider implementation
│   │   ├── ollama_vault.py ← Ollama API key vault integration
│   │   ├── openai.py       ← OpenAI provider implementation
│   │   └── openai_vault.py ← OpenAI API key vault integration
│   └── db_providers/
│       ├── base.py         ← Base DB provider
│       ├── sqlite_provider.py
│       └── cosmos_provider.py
├── tools/
│   ├── skills/
│   │   ├── activate_skill.py  ← Load SKILL.md content into context
│   │   └── run_skill.py       ← Execute skill scripts (subprocess)
│   └── system/
│       ├── read_file.py
│       ├── write_file.py
│       └── run_command.py
├── components/
│   ├── chat/          ← ChatTab, MsgBox, StreamingMsgBox, MessageInput, Message
│   ├── workspace/     ← Workspace (split panes), EditorTab, OpenWorkspaceTab
│   ├── sidebar/       ← Sidebar wrapper, ChatHistory, Settings, PasswordVault, ToolList
│   ├── tabs/          ← Generic tab container (header, body, title button)
│   ├── tree/          ← GenericTree, TreeRow, VaultTreeRow
│   ├── db/            ← DB sidebar tab, DB tree, Results modal
│   ├── fs/            ← File tree components
│   ├── terminal/      ← Terminal sidebar (textual-terminal integration)
│   └── utils/         ← Buttons, modals (Input, Form, CommandsHelp), LeaderGuideScreen
├── skills/            ← Bundled skills (agents, brave_search, coding, git, todo, etc.)
├── themes/            ← Bundled themes (haxor.py)
├── cmd/               ← Core slash commands (clear.py, help.py)
└── examples/          ← Example skills and components
```

### 2.2 Core Systems (Keep These)

#### A. Config Manager (`cfg_man.py`)

**What it does:**
- Loads multiple JSON config files in order (global → project), deep-merging them.
- Provides dot-path access: `cfg.get('session.provider')`, `cfg.set('a.b.c', val)`.
- Saves only the diff vs. the baseline (files below the save path), keeping files clean.
- Supports a "registered defaults" system — modules call `register_default_config({...})`
  at import time, and `cfg.apply_registered_defaults()` fills in missing keys.

**Key design points:**
- `deep_update(d, u)` — recursive merge, `u` wins.
- `deep_merge_missing(dst, src)` — only fills keys not already present.
- `deep_overlay_diff(merged, baseline)` — computes what to write (only changed keys).
- `Config.drill(path)` — walks dotted path through nested dicts/lists.
- Singleton `cfg` instance created at module level with global + local paths.

**Why keep:** Clean, well-isolated, no external dependencies beyond `json` and `os`.
The diff-save approach is elegant. The defaults registration pattern is simple and effective.

#### B. Password Vault (`password_vault.py`)

**What it does:**
- Encrypted JSON file at `~/.agents/cody_passwords_db.enc`.
- Fernet symmetric encryption with PBKDF2HMAC key derivation (SHA-256, 480K iterations).
- Two entry types: **credentials** (username + password) and **secure notes** (free text).
- Session-based unlock: master password → derived key cached in memory.
- TUI integration: `prompt_master_password()` pushes an `InputModal` for unlock.
- Public API: `register_credential()`, `register_secure_note()`, `get_credential()`, `get_secure_note()`.
- `get_credential()` / `get_secure_note()` are async — they await unlock if needed.
- Clear hooks: providers can register callbacks for when the vault locks.

**Key design points:**
- Vault file is versioned (`VAULT_VERSION = 1`).
- Salt stored in the file; key derived fresh each unlock.
- Validation on unlock: attempts to decrypt all ciphertexts to detect wrong password.
- Concurrent unlock callers are queued — only one modal at a time.

**Why keep:** Well-designed, cryptographically sound, clean public API. The unlock flow
with concurrent waiter queuing is thoughtful.

#### C. Skills System (`skills.py`)

**What it does:**
- Discovers skills by scanning directories for `SKILL.md` files with YAML frontmatter
  (requires `name` and `description` fields).
- 3-tier search order: `$CODY_DIR/skills/` → `~/.agents/skills/` → `{wd}/.agents/skills/`.
- Later tiers override earlier tiers for same-named skills.
- Per-skill enable/disable via `skills.enabled` config.
- Generates XML catalog for injection into the agent system prompt.
- Provides helper functions for discovering skill `cmd/` and `tools/` directories.

**Key design points:**
- `SkillManager` is a singleton that re-discovers on every `get_catalog_xml()` call
  (so config changes are hot-loaded).
- Simple YAML frontmatter parser (no full YAML dependency — just `key: value` lines).
- Skill structure: `{name, description, location, base_dir, body}`.

**Why keep:** The skill system IS the extension mechanism. The 3-tier search,
enable/disable, and catalog generation are all essential.

#### D. Provider System (`providers/`)

**What it does:**
- `BaseProvider` protocol defining `chat()` and `stream_chat()` interfaces.
- `ChatResponse`, `Message`, `StreamChunk`, `TokenUsage` dataclasses for normalization.
- `OllamaProvider` and `OpenAIProvider` implementations.
- Vault-integrated API key management (`openai_vault.py`, `ollama_vault.py`).
- Provider selection via `session.provider` config key.

**Key design points:**
- Both providers normalize to the same response types.
- Streaming uses generators yielding `StreamChunk` objects.
- API keys resolved from: vault → config → environment variable.
- `ensure_*_api_key_for_tui()` functions handle the unlock-and-prompt flow.

**Why keep:** Clean abstraction. The protocol + dataclass approach is solid.

#### E. Tool Registry (`tool.py`)

**What it does:**
- Register callables with a name and optional tags.
- Tag-based grouping (e.g., `'skills'`, `'system'`).
- Enable/disable individual tools or whole groups.
- `get_tools(tags)` returns enabled tool functions for the given tags.
- `execute_tool(name, args)` runs a tool by name.

**Key design points:**
- Module-level globals: `tools`, `groups`, `enabled_tools`.
- Tools are plain Python functions (not wrapped in objects).
- The agent passes tool functions directly to the provider.
- `@register_tool()` decorator enables self-registration at import time —
  skill authors drop a file and it just works. This pattern stays.

**Why keep:** Simple, effective, and critically — the decorator pattern is the
key to skill extensibility. No class wrapping needed (see §6.1).

The tool registry serves a distinct purpose from slash commands (user-typed
`/command`) and leader chords (`Ctrl+Space → key`). See §6.3.

#### F. Database Manager (`db.py`)

**What it does:**
- Manages multiple database connections (SQLite files + Azure Cosmos DB).
- Project database (`cody_data.db`) with tables: `chats`, `input_history`, `agents`, `todos`.
- CRUD operations for chats and agents.
- Bundled agent seeding from `skills/agents/bundled/*.json`.
- Connection serialization to/from config.

**Why keep:** Essential for persistence. The multi-provider approach is good.

#### G. Leader Registry (`leader_registry.py`)

**What it does:**
- Tree of keyboard chords for the leader menu (Ctrl+Space).
- `LeaderNode` dataclass: `label`, `children: dict[str, LeaderNode]`, `handler`.
- `register_submenu()` and `register_action()` for building the tree.
- Core chords registered from workspace, chat, and terminal modules.
- Skill chords discovered from `components/leader_menu.py` in each skill.

**Why keep:** Clean tree structure, extensible by skills. Distinct from tools (agent-invoked)
and slash commands (user-typed in chat) — see §6.3.

#### H. Path System (`paths.py`)

**What it does:**
- `get_cody_dir()` — root of the Cody installation.
- `get_global_agents_dir()` — `~/.agents`.
- `tiered_dir_templates(subpath)` — the 3-tier template list.
- `resolve_dir_templates()` — expands `$CODY_DIR`, `~`, `{working_directory}`.
- `resolved_tiered_paths()` — convenience for the common case.

**Why keep:** The 3-tier pattern is used everywhere. Clean and simple.

---

## 3. What Needs Simplification

### 3.1 Duplicated Code

| Duplication | Locations |
|---|---|
| `_group_assistant_tool_messages()` | `chat.py` (lines 22-64), `streaming_chat.py` (lines 28-70) — **identical** |
| `_messages_to_display()` | `chat.py` (lines 67-79), `streaming_chat.py` (lines 73-85) — **identical** |
| `save_chat()` method | `MsgBox` (lines 350-378), `StreamingMsgBox` (lines 561-588) — **near-identical** |
| `_refresh_chat_history()` | `MsgBox` (lines 342-348), `StreamingMsgBox` (lines 553-559) — **identical** |
| `_update_usage_display()` | `MsgBox` (lines 119-137), `StreamingMsgBox` (lines 312-330) — **identical** |
| `_focus_message_input()` | `MsgBox` (lines 143-149), `StreamingMsgBox` (lines 336-342) — **identical** |
| `abort_agent_response()` | `MsgBox` (lines 228-230), `StreamingMsgBox` (lines 344-346) — **identical** |
| `compose()` structure | `MsgBox` (lines 96-102), `StreamingMsgBox` (lines 289-295) — **identical** |
| `on_mount()` | `MsgBox` (lines 139-141), `StreamingMsgBox` (lines 332-334) — **identical** |
| `watch_messages()` | `MsgBox` (lines 104-117), `StreamingMsgBox` (lines 297-310) — **near-identical** |

**Fix:** Extract a `BaseMsgBox` class with all shared logic. `MsgBox` and `StreamingMsgBox`
only differ in `get_agent_response()`.

### 3.2 Overly Long Methods

- `MsgBox.get_agent_response()` — ~110 lines. Mixes: API key checks, message building,
  tool-calling loop, abort handling, run_command confirmation, sync, save, refresh.
- `StreamingMsgBox.get_agent_response()` — ~165 lines. Same concerns plus thread/queue
  management for bridging sync streaming to async UI.

**Fix:** Break into smaller, testable methods:
- `_ensure_api_key()` — provider-specific key check.
- `_build_user_message()` — user msg + git checkpoint.
- `_execute_tool_call()` — single tool execution with run_command confirmation.
- `_finalize_turn()` — sync messages, save, refresh history.

### 3.3 Global Mutable State

Current singletons/globals:
- `cfg` — Config singleton (module-level in cfg_man.py)
- `skill_manager` — SkillManager singleton (module-level in skills.py)
- `db_manager` — DatabaseManager proxy (module-level in db.py)
- `tools`, `groups`, `enabled_tools` — module-level dicts/sets in tool.py
- `SESSION_KEY`, `_DATA`, `_tui_app` — module-level in password_vault.py
- `_root` — LeaderNode tree root in leader_registry.py

**Problem:** Hard to test, hard to reason about initialization order, implicit coupling.

**Fix:** A single `AppContext` dataclass or simple DI container that holds references to
the services components need to *query* at runtime (config, database, leader registry,
working directory). The tool registry and skill manager stay as module-level
singletons — their self-registration-at-import pattern (via `@register_tool()`) is
essential for the drop-in extensibility of the skill system and shouldn't be disrupted.
The vault session state also stays module-level (it's genuinely global session state).

`AppContext` is a service locator, not a strict DI container. Components import it
for things they need to read, not things that self-register.

### 3.4 `main.py` Does Too Much

`main.py` currently handles:
1. Argument parsing
2. Config loading + defaults
3. CSS discovery (walking components/ and skills/)
4. Skill discovery
5. Leader registry reset + core registration
6. Tool loading (tiered paths + skill tools)
7. Leader entry discovery
8. Git repo initialization
9. App class definition (TuiApp with all actions)
10. Theme registration
11. Async entry point

**Fix:** Extract a `Bootstrap` or `ApplicationFactory` that handles steps 1-8 and returns
a configured app. Keep `TuiApp` focused on UI concerns.

### 3.5 Chat Component Architecture

Currently there are two parallel implementations:
- `MsgBox` — blocking, uses `asyncio.to_thread(self.actor.get_response, '')`
- `StreamingMsgBox` — uses `actor.get_response_stream()` with a thread+queue bridge

**Fix:** Unify on streaming. The blocking path can be a thin wrapper that collects all
chunks from the stream into a single response. One `MsgBox` class, one code path.

### 3.6 CSS Discovery

CSS files are discovered by walking directory trees at startup. This is scattered between
`main.py` and `fs.discover_css()`. Skills also contribute CSS from their `components/` dirs.

**Fix:** A single `collect_css_paths()` function that gathers from all sources (core
components + skills) and returns a flat list. Called once at bootstrap.

---

## 4. Proposed Target Architecture

### 4.1 Directory Structure (Simplified)

```
cody/
├── main.py                  ← Entry point: parse args, bootstrap, run app
├── app.py                   ← TuiApp class (UI concerns only)
├── bootstrap.py             ← Bootstrap: config, skills, tools, CSS, themes, git
├── context.py               ← AppContext dataclass (holds refs to all services)
├── pyproject.toml
├── app.css
├── core/                    ← Core systems (the "keepers")
│   ├── config.py            ← Config manager (was cfg_man.py)
│   ├── vault.py             ← Password vault (was password_vault.py)
│   ├── skills.py            ← Skill discovery & catalog
│   ├── agent.py             ← Agent + TaskAgent
│   ├── tools.py             ← Tool registry
│   ├── database.py          ← Database manager
│   ├── paths.py             ← Path utilities
│   ├── leader.py            ← Leader registry
│   ├── commands.py          ← Slash-command loader
│   ├── git.py               ← Git utilities
│   ├── themes.py            ← Theme discovery
│   └── providers/           ← LLM providers
│       ├── base.py
│       ├── ollama.py
│       ├── openai.py
│       └── keys.py          ← Unified API key management (merge *_vault.py files)
├── tools/                   ← Agent-callable tools (registered at startup)
│   ├── activate_skill.py
│   ├── run_skill.py
│   ├── read_file.py
│   ├── write_file.py
│   └── run_command.py
├── ui/                      ← All Textual widgets
│   ├── chat/
│   │   ├── chat_tab.py      ← ChatTab (TabPane subclass)
│   │   ├── msg_box.py       ← Unified MsgBox (streaming only, blocking as wrapper)
│   │   ├── message.py       ← Message + StreamingMessage widgets
│   │   ├── input.py         ← MessageInput
│   │   └── chat.css
│   ├── workspace/
│   │   ├── workspace.py
│   │   └── workspace.css
│   ├── sidebar/
│   │   ├── wrapper.py
│   │   ├── chat_history.py
│   │   ├── settings.py
│   │   ├── vault_tab.py
│   │   ├── tool_list.py
│   │   └── sidebar.css
│   ├── terminal/
│   │   └── terminal.py
│   ├── db/
│   │   ├── db_tab.py
│   │   ├── db_tree.py
│   │   └── db.css
│   ├── tree/                ← Generic tree components
│   │   ├── tree.py
│   │   ├── tree_row.py
│   │   └── tree.css
│   └── widgets/             ← Shared widgets (buttons, modals, leader screen)
│       ├── buttons.py
│       ├── modals.py
│       ├── leader_screen.py
│       └── widgets.css
├── skills/                  ← Bundled skills (unchanged structure)
├── themes/                  ← Bundled themes
└── cmd/                     ← Core slash commands
```

### 4.2 Key Architectural Changes

#### 1. `AppContext` — Service Locator

```python
@dataclass
class AppContext:
    config: Config
    skills: SkillManager       # ref to singleton (for UI queries, not registration)
    database: DatabaseManager
    leader: LeaderRegistry
    working_directory: str
```

Created once at bootstrap. Holds references to services components need to *query*
at runtime. The tool registry and skill manager remain module-level singletons —
their `@register_tool()` / `SkillManager()` patterns are essential for
self-registration-at-import extensibility and should not be disrupted by DI.
The vault also stays module-level (session state, not app state).

`AppContext` is a service locator, not a strict DI container.

#### 2. Unified `MsgBox`

One `MsgBox` class. Always streams. The non-streaming path is just:

```python
async def get_response_blocking(self, user_text):
    chunks = []
    async for chunk in self.actor.get_response_stream(user_text):
        chunks.append(chunk)
    return chunks
```

No more duplicated `_group_assistant_tool_messages`, `save_chat`, etc.

#### 3. Bootstrap Module

```python
class Bootstrap:
    def __init__(self, working_directory: str):
        self.wd = working_directory

    def run(self) -> AppContext:
        config = self._init_config()
        skills = self._discover_skills(config)
        self._load_tools(config, skills)     # triggers import-time registration
        database = self._init_database(config)
        leader = self._init_leader(skills)
        self._init_git()
        css = self._collect_css(skills)
        return AppContext(
            config=config,
            skills=skills,
            database=database,
            leader=leader,
            working_directory=self.wd,
        ), css
```

#### 4. Unified API Key Management

Merge `openai_vault.py` and `ollama_vault.py` into a single `providers/keys.py`:

```python
async def ensure_api_key(provider_name: str, app) -> bool:
    """Ensure we have an API key for provider_name. Prompts vault unlock if needed."""

def clear_api_key_cache(provider_name: str) -> None:
    """Clear cached key for provider_name (called on vault lock)."""
```

#### 5. CSS Collection

```python
def collect_css(skills: SkillManager) -> list[str]:
    paths = ['app.css']
    paths.extend(discover_css('ui/'))
    for skill in skills.values():
        css_dir = os.path.join(skill.base_dir, 'components')
        if os.path.isdir(css_dir):
            paths.extend(discover_css(css_dir))
    return paths
```

### 4.3 What Stays the Same

| System | Changes |
|---|---|
| Config Manager | Move to `core/config.py`, otherwise identical |
| Password Vault | Move to `core/vault.py`, otherwise identical |
| Skills System | Move to `core/skills.py`, manual scan button replaces implicit re-discovery |
| Provider Protocol | Move to `core/providers/base.py`, otherwise identical |
| Tool Registry | Move to `core/tools.py`, keep module-global decorator pattern (no class wrapper — see §6.1) |
| Database Manager | Move to `core/database.py`, drop Cosmos provider, keep provider abstraction, ship SQLite only (see §6.2) |
| Leader Registry | Move to `core/leader.py`, unchanged |
| Path System | Move to `core/paths.py`, otherwise identical |
| Git Utilities | Move to `core/git.py`, otherwise identical |
| Theme Discovery | Move to `core/themes.py`, otherwise identical |
| Slash Commands | Move to `core/commands.py`, otherwise identical |

---

## 5. Migration Strategy

### Phase 1: Extract Core (no behaviour changes)

1. Create `core/` directory.
2. Move each utility file, updating import paths throughout.
3. Verify the app still runs.

### Phase 2: Eliminate Duplication

1. Extract `BaseMsgBox` from the common parts of `MsgBox` and `StreamingMsgBox`.
2. Unify on streaming — delete the blocking path.
3. Extract shared message grouping functions to a single location.

### Phase 3: Introduce AppContext

1. Create `AppContext` dataclass (service locator — does NOT wrap tools/skills).
2. Create `Bootstrap` class in `bootstrap.py`.
3. Wire AppContext through to components that query config, database, leader.
4. Tool registry and skill manager remain module-level imports — components
   import them directly for self-registration patterns.

### Phase 4: Simplify

1. Break up long methods in chat components.
2. Merge vault provider files.
3. Clean up `main.py` to just parse args + call bootstrap + run app.
4. Remove dead code (commented-out imports, unused utilities).

---

## 6. Design Decisions (Resolved)

### 6.1 Tool Registry: Keep Module Globals with Decorator Pattern

**Decision:** Keep the current `@register_tool()` decorator with module-level
globals (`tools`, `groups`, `enabled_tools`). Do NOT wrap in a class.

**Rationale:** The decorator pattern means tools self-register at import time with
a single line — no passing registries around, no proxy pattern needed. This is
critical for skill extensibility: skill authors can drop a Python file with
`@register_tool(...)` in their skill's `tools/` directory and it just works.
A class-based approach would require every tool author to access the registry
instance, adding friction to the extension mechanism.

### 6.2 Database Providers: Drop Cosmos, Keep Provider Abstraction, Ship SQLite Only

**Decision:** Remove the Cosmos DB provider entirely. Ship with SQLite as the only
bundled provider. Retain the provider abstraction (`db_providers/base.py`) so users
can write their own providers for other database types.

**Rationale:** Cosmos DB requires `azure-cosmos` and `azure-identity` — heavy
dependencies that add complexity without broad utility. The provider abstraction is
clean and worth keeping for extensibility, but we only need to ship and maintain
one concrete implementation.

### 6.3 Slash Commands, Leader Chords, and Tools: Three Separate Registries

**Decision:** Keep these as three distinct, separate registries. No merging.

**Rationale:** They serve fundamentally different invocation contexts:
- **Tools** — agent-invoked via the LLM's tool-calling loop. Need structured args
  and structured results. The LLM decides when to call them.
- **Slash commands** — user-typed in the chat input (`/command`). Freeform,
  meant for direct user control over the application.
- **Leader chords** — keyboard-driven (`Ctrl+Space → key sequence`). Pure UI
  navigation and actions with no text input.

Keeping them separate maintains clean boundaries and gives skill authors three
distinct extension surfaces to choose from depending on their needs.

### 6.4 Skill Discovery: No Hot-Reloading, Add a Manual Scan Button

**Decision:** Remove the implicit re-discovery on every catalog generation. Instead,
add an explicit "Scan Skills" button in the UI that triggers re-discovery and
refreshes the catalog.

**Rationale:** Implicit re-discovery is confusing behavior — users don't know when
it happens. File watchers add complexity (cross-platform edge cases, resource use).
A manual button is simple, explicit, and gives users control. It's still more
convenient than restarting the application.

### 6.5 Testing Strategy

**Decision:** The rewrite will include a full test suite from the start. Use pytest
with fixtures that leverage `AppContext` for dependency injection.

**Key testing design points:**
- `AppContext` makes services injectable — tests can supply test configs, mock
  databases, and fake provider responses.
- Module-level singletons (tool registry, skill manager) can be reset between
  tests via explicit reset functions added to their public APIs.
- Provider tests: mock HTTP responses, verify normalization to `ChatResponse`/
  `StreamChunk`.
- UI tests: Textual's `pilot` fixture for widget-level integration tests.
- Vault tests: integration tests against a temp encrypted file.

**Recommended pytest fixtures:**
- `test_config` — in-memory config or temp JSON files
- `test_context` — `AppContext` wired with all fakes
- `test_db` — temp SQLite file, seeded with known data
- `mock_provider` — provider that returns canned responses

---

## 7. Implementation Phases

### Step 1: Project Scaffolding ✅

 - pyproject.toml — deps: textual, ollama, cryptography, dev: pytest, pytest-asyncio
 - Directory skeleton: core/, core/providers/, ui/, tools/, skills/, tests/
 - conftest.py with base fixtures
 - Tests: Verify project imports cleanly
 - **COMPLETE** — branch `step-1-scaffolding`

### Step 2: Provider Base Protocol (zero internal deps)

 - core/providers/base.py — BaseProvider protocol, ChatResponse, Message, StreamChunk, TokenUsage, ToolCall dataclasses
 - Pure data + interfaces, no I/O
 - **COMPLETE** — branch `step-2-6-provider-base-ollama`
 - Added ``thinking`` field to ChatResponse and StreamChunk for reasoning-capable models

### Step 3: Path System (zero internal deps) ✅

 - core/paths.py — get_cody_dir(), get_global_agents_dir(), 3-tier resolution, template expansion
 - Tests: All path functions, edge cases (missing dirs, relative paths, $CODY_DIR expansion)
 - **COMPLETE** — simplified to 3 functions: cody_dir(), agents_dir(), resolve()

### Step 4: Config Manager (depends on paths) ✅

 - core/config.py — layered JSON loading, dot-path access, diff-save, registered defaults
 - Tests: Deep merge, dot-path get/set, diff computation, defaults registration, round-trip save/load
 - **COMPLETE** — Config class: get(), set(), defaults(), apply_defaults(), save()

### Step 5: Password Vault (depends on paths) ✅

 - core/vault.py — Fernet + PBKDF2, credential + secure note types, session unlock, concurrent waiter queue
 - Tests: Encrypt/decrypt round-trip, wrong password rejection, lock/unlock flow, concurrent unlock callers
 - **COMPLETE** — Vault class: initialize(), unlock(), lock(), is_locked(), credential + secure note CRUD

### Step 6: Ollama Provider (depends on base, config, vault)

 - core/providers/ollama.py — implements BaseProvider, chat() + stream_chat(), API key from vault only (no config/env fallback)
 - Removed ``core/providers/keys.py`` — unnecessary indirection; providers resolve keys directly from vault
 - **COMPLETE** — branch `step-2-6-provider-base-ollama`

### Step 7: Recursive Pane Tree + Workspace (depends on events, context stub) ✅

 - core/pane_tree.py — pure data model: LeafPane, SplitPane, operations (split, close, find_neighbor, set_content, get_leaves, get_layout)
 - ui/workspace/workspace.py — Workspace widget composing tree → Horizontal/Vertical containers, vim+click navigation, leader event posting
 - ui/workspace/workspace.css — pane borders, focus indicators, empty-state styling
 - Tests: All tree operations in isolation, Workspace widget via Textual pilot
 - No resize — splits set a ratio once at creation time
 - Leader chords: ws v/h (split), ws c (close), ws h/j/k/l (navigate)
 - **COMPLETE** — branch `step-7-pane-tree-workspace` (merged to main)

### Step 8: Tool Registry (zero internal deps) ✅

 - core/tools.py — @register_tool() decorator, tag-based grouping, enable/disable, execute_tool(), get_tools(), reset for tests
 - Tests: Registration, tag filtering, enable/disable, execution, reset isolation
 - **COMPLETE** — merged to main

### Step 9: Skill System (depends on paths, config, tools) ✅

 - core/skills.py — SKILL.md discovery with YAML frontmatter, 3-tier search with override, enable/disable, XML catalog generation, manual scan method (no implicit re-discovery)
 - Tests: Discovery from fixture directories, tier override, frontmatter parsing, catalog XML output, scan method
 - **COMPLETE** — merged to main

### Step 10: Agent (depends on providers, tools, skills) ✅

 - core/agent.py — system prompt builder with `{{key}}` template substitution, tool-calling loop, streaming response handling, abort, max_tool_iterations safety limit
 - core/providers/base.py — added ``tool_calls`` field to ``StreamChunk``
 - Tests: template rendering, message building, simple chat, tool-calling loop, streaming, abort
 - **COMPLETE** — branch `step-10-agent`

### Step 11: Database (depends on paths, config) ✅

 - core/database.py — provider abstraction (BaseDBProvider), SQLiteProvider, connection manager, tables: chats/agents/todos/input_history, CRUD, agent seeding
 - Tests: All CRUD operations, multi-connection, provider swapping, seeded agents
 - **COMPLETE** — merged to main; Cosmos provider dropped per §6.2

### Step 12: Leader Registry + Slash Commands (zero internal deps) ✅

 - core/leader.py — LeaderNode tree, register_submenu(), register_action(), skill chord discovery
 - core/commands.py — slash-command loader, CommandBase, tiered discovery from skill cmd/ dirs
 - Tests: Tree building, action dispatch, command loading, chord conflict detection
 - **COMPLETE** — merged to main; LeaderOverlay widget built early in ui/widgets/

### Step 13: Bootstrap + AppContext (depends on everything above) ✅

 - context.py — AppContext dataclass (config, skills, database, leader, working_directory)
 - bootstrap.py — Bootstrap class: init config → discover skills → load tools → init DB → build leader → return context
 - core/themes.py — theme discovery (3-tier) — **DEFERRED**
 - core/git.py — git checkpoint utilities — **DEFERRED**
 - CSS collection — **DEFERRED** to later step
 - Tests: Full bootstrap flow with temp directories, verify all services initialized
 - **COMPLETE** — merged to main; leader overlay, main.py wiring, and workspace leader chords built alongside

### Step 14: Shared UI Widgets (depends on AppContext) ✅

 - ui/widgets/ — InputModal, CommandsHelp, LeaderOverlay (built in Step 12/13)
 - Tests: Textual pilot for each widget, modal flows, keyboard navigation
 - **COMPLETE** — branch `step-14-ui-widgets`; FormModal deferred

### Step 15: Chat UI (depends on agent, AppContext, widgets)

 - ui/chat/ — Message widget, StreamingMessage widget, MessageInput, unified MsgBox (streaming-only), ChatTab
 - Tests: Message rendering, streaming append, input submission, MsgBox full turn cycle with mock agent

### Step 16: Workspace + Terminal (depends on AppContext)

 - ui/workspace/ — split panes, EditorTab, OpenWorkspaceTab
 - ui/terminal/ — terminal integration
 - Tests: Pane splitting, tab opening/closing, terminal launch

### Step 17: Sidebar Components (depends on AppContext, database, widgets) ✅

 - ui/sidebar/ — registry, Sidebar, SidebarContainer, panels/vault_panel.py
 - ui/db/ — DBTab, DBTree, results modal — DEFERRED
 - ui/tree/ — GenericTree, TreeRow ✅ (built in `step-tree`)
 - Tests: registry, sidebar visibility, vault panel rendering
 - **COMPLETE** — branch `step-sidebar`; DB tab deferred

### Step 18: app.py + main.py (wires everything)

 - app.py — TuiApp class, leader key binding, theme registration, all action methods
 - main.py — parse args → Bootstrap.run() → mount app → run
 - app.css — base styles
 - Tests: App launch, leader menu opens, theme switching, full smoke test

### Step 19: Bundled Content + E2E

 - Basic skills: coding, git, todo, brave_search
 - Default themes
 - E2E tests: full conversation with tool calls, git checkpoint, vault unlock flow

---
