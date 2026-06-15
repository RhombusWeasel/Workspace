# AppContext

**File:** `context.py`
**Depends on:** `core.config.Config`, `core.database.DatabaseManager`, `core.leader.LeaderRegistry`, `core.skills.SkillManager`, `core.vault.VaultManager`, `core.providers.registry.ProviderRegistry`, `core.agent_registry.AgentManager`

---

## Purpose

`AppContext` is a service locator dataclass that holds references to every
core service.  It is created once at bootstrap and threaded through to
every component that needs to query config, read secrets, access the
database, or drive the UI.

It is **not** a dependency injection container — the tool registry and
skill manager remain module-level singletons because their decorator
self-registration patterns are essential for extensibility.

---

## Fields

```python
@dataclass
class AppContext:
    config: Config | None = None
    skills: SkillManager | None = None
    database: DatabaseManager | None = None
    db_connections: Any = None
    leader: LeaderRegistry | None = None
    providers: ProviderRegistry | None = None
    agents: AgentManager | None = None
    vault: VaultManager | None = None
    working_directory: str = ""
    css_paths: list[str] = field(default_factory=list)
    services: dict[str, Any] = field(default_factory=dict)
    app: Any = None
    prompts: Any = None  # Deprecated — use ctx.agents instead
```

| Field | Type | Set by | Description |
|---|---|---|---|
| `config` | `Config \| None` | Bootstrap | Layered JSON config with dot-path access |
| `skills` | `SkillManager \| None` | Bootstrap | Skill catalog (discovered SKILL.md files) |
| `database` | `DatabaseManager \| None` | Bootstrap | SQLite persistence (chats, messages, agents, todos) |
| `db_connections` | `Any` | Database skill | `ConnectionManager` if the database skill is loaded; `None` otherwise |
| `leader` | `LeaderRegistry \| None` | Bootstrap | Keyboard chord tree for `Ctrl+Space` menu |
| `providers` | `ProviderRegistry \| None` | Bootstrap | Named LLM provider instances, lazy creation from config |
| `agents` | `AgentManager \| None` | Bootstrap | Agent definition registry (CRUD, templates, seeding) |
| `vault` | `VaultManager \| None` | Bootstrap | Encrypted credential + secure note storage |
| `working_directory` | `str` | Bootstrap | Current working directory (project root) |
| `css_paths` | `list[str]` | Bootstrap | Collected `.tcss` file paths for Textual CSS |
| `services` | `dict[str, Any]` | Bootstrap | Dynamic service instances from skill `SKILL_SERVICES` |
| `stream_manager` | `StreamManager \| None` | WorkspaceApp | Owns active LLM stream tasks |
| `session_manager` | `SessionManager \| None` | WorkspaceApp | Saves/restores workspace state across restarts |
| `app` | `Any` | `WorkspaceApp.__init__` | The running Textual app instance |
| `prompts` | `Any` | Bootstrap | **Deprecated** — same as `ctx.agents`, for migration |

### Backward-compatible `provider` property

```python
@property
def provider(self) -> BaseProvider | None:
    """The default LLM provider (convenience shortcut)."""
    if self.providers is not None:
        try:
            return self.providers.get_default()
        except (ValueError, KeyError):
            return None
    return None
```

`ctx.provider` is a convenience property that delegates to
`ctx.providers.get_default()`.  New code should prefer
`ctx.providers.get_default()` or `ctx.providers.get(name)` to be
explicit about which named provider instance is being used.

---

## Plugin-Provided Services

The `services` dict and `db_connections` field are populated by skills
via the `SKILL_SERVICES` mechanism.  Plugins that need to provide
services to other parts of the application follow this pattern:

1. The skill declares `SKILL_SERVICES` in its `__init__.py`:
   ```python
   SKILL_SERVICES = {
       "db_connections": create_connection_manager,
   }
   ```

2. Bootstrap calls each factory with `(config, vault)` and collects
   the results into the `services` dict.

3. Known services also get dedicated fields for type-safety:
   ```python
   ctx.services["db_connections"]  # Generic access
   ctx.db_connections              # Convenience alias
   ```

To add a new service from a skill:

1. Add the factory to the skill's `SKILL_SERVICES` dict
2. (Optional) Add a dedicated field to `AppContext` for type-safety
3. Wire it in `Bootstrap.run()` if a dedicated field was added

---

## How to Access AppContext

### In event handlers

Handlers receive `ctx` as the second parameter:

```python
@register_handler("my_skill.action")
def _on_action(data: dict, ctx: AppContext) -> None:
    value = ctx.config.get("my_skill.setting", "default")
    if ctx.vault and not ctx.vault.is_locked():
        cred = ctx.vault.get_credential("service_name")
    provider = ctx.providers.get_default()  # or ctx.providers.get("ollama")
```

### In tools (via context injection)

Tools that declare a `ctx` parameter receive it automatically:

```python
@register_tool(name="my_tool", ...)
def my_tool(query: str, ctx: AppContext | None = None) -> str:
    if ctx is None:
        return "Error: no context."
    ...
```

### In slash commands

Commands receive `app`, which has a `context` attribute:

```python
@register_command(name="my_cmd", description="...")
async def my_cmd(app, args: str) -> str:
    ctx = app.context
    ...
```

### In widgets

Textual widgets can reach the app via `self.app`:

```python
class MyWidget(Widget):
    def on_mount(self) -> None:
        ctx = self.app.context
        theme = ctx.config.get("ui.theme", "default")
```

---

## Creating AppContext (Bootstrap)

`AppContext` is constructed in `Bootstrap.run()`, which wires together
all services in order:

```python
def run(self) -> AppContext:
    self._ensure_project_on_path()
    config = self._init_config()
    skills = self._discover_skills(config)
    self._load_tools(skills)
    self._load_commands(skills)
    self._load_sidebar_panels(skills)
    database = self._init_database(config)
    vault = self._init_vault()
    providers = self._init_provider_registry(config, vault)
    agents = self._init_agent_registry(database)
    self._register_agent_providers(agents, skills, providers)
    skill_services = self._load_skill_init_files(skills, config, vault)
    self._init_leader()
    css_paths = self._collect_css()

    return AppContext(
        config=config,
        skills=skills,
        database=database,
        db_connections=skill_services.get("db_connections"),
        providers=providers,
        agents=agents,
        prompts=agents,  # Deprecated alias
        vault=vault,
        leader=leader_registry,
        working_directory=self.wd,
        css_paths=css_paths,
        services=skill_services,
    )
```

The `WorkspaceApp` constructor then receives this context and sets
`context.app = self` so handlers can reach the UI.

---

## Design Decisions

1. **Dataclass, not DI container** — Simplicity over abstraction.  Fields
   are known and typed.  No dynamic resolution or lazy loading.

2. **`app` set after construction** — `AppContext` is created in bootstrap,
   before the app exists.  The app sets `context.app = self` in its
   constructor.  Handlers check `ctx.app is not None` before using it.

3. **Plugin services are opt-in** — Not every field is populated by every
   installation.  `db_connections` is `None` if the database skill is
   disabled.  Consumers check for `None`.

4. **No global singleton** — `AppContext` is passed around, not imported
   from a module.  This avoids circular imports and makes testing easier
   (construct an `AppContext` with mock services in tests).

5. **`providers` registry over single `provider`** — Multiple named
   provider instances can coexist (e.g. local Ollama + remote OpenAI).
   The `provider` property is preserved for backward compatibility only.

6. **`agents` replaces `prompts`** — The `prompts` field is a deprecated
   alias for `agents`.  New code should use `ctx.agents` exclusively.