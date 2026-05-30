# Prompt Registry — Design Plan

## 1. Overview

Replace the hard-coded system prompts and unused `agents` table with a **prompt registry**: a database-backed store of `{{key}}` templates with dynamic variable resolution. Users can create, edit, and switch between agent personas. Project-specific prompts override global defaults via a scope field.

**Key decisions:**

1. **Deprecate `agents` table** — absorb its fields into `prompts`; remove the agents CRUD.
2. **DB-only storage** — defaults seeded in code; project overrides stored as rows with `scope='project'`.
3. **Config key for default prompt** — `prompt.default_id` points to a prompt in the registry.
4. **Nested `{{key}}` syntax** — `{{skills}}` renders the full catalog; `{{skills.catalog}}` renders only the catalog XML; `{{skills.names}}` renders just skill names. Supports future per-skill filtering.

---

## 2. Schema

### 2.1 New: `prompts` table

```sql
CREATE TABLE IF NOT EXISTS prompts (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    template    TEXT NOT NULL,
    model       TEXT NOT NULL DEFAULT '',
    scope       TEXT NOT NULL DEFAULT 'global',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_prompts_scope ON prompts(scope);
```

| Column | Purpose |
|---|---|
| `id` | Stable identifier used in config references and `prompt_id` lookups. e.g. `"default"`, `"inline-suggest"`, `"custom:code-review"`. User-created prompts use a `"custom:"` prefix to avoid collisions with built-in IDs. |
| `name` | Human-readable label shown in the UI. e.g. `"Default Assistant"`. |
| `description` | One-line summary of the prompt's purpose. |
| `template` | The system prompt text containing `{{key}}` placeholders. |
| `model` | Optional model override. When non-empty, the `Agent` for this prompt uses this model instead of the session default. Migrated from the `agents` table. |
| `scope` | `"global"` or `"project"`. Project-scoped prompts are only visible when `working_directory` matches. Global prompts are always available. |
| `created_at` / `updated_at` | ISO-8601 timestamps. |

### 2.2 Deprecated: `agents` table

The existing `agents` table is **not dropped** (to allow a future migration script), but all CRUD methods on `DatabaseManager` are deprecated and the table receives no new writes. The relevant columns map to `prompts` as follows:

| `agents` column | `prompts` column |
|---|---|
| `id` | `id` |
| `name` | `name` |
| `description` | `description` |
| `system_prompt` | `template` |
| `model` | `model` |

A one-time migration copies any rows from `agents` → `prompts` and then leaves the `agents` table frozen.

---

## 3. Variable Resolution

### 3.1 Nested key syntax

The existing `{{key}}` regex matches `\{\{(\w+)\}\}` — we extend it to support dot-notation:

```python
_PLACEHOLDER = re.compile(r"\{\{(\w+(?:\.\w+)*)\}\}")
```

This matches `{{skills}}`, `{{skills.catalog}}`, `{{skills.names}}`, `{{working_directory}}`, etc.

### 3.2 Dynamic variable providers

`PromptManager` maintains a registry of **providers** — callables that receive an `AppContext` and return a string. Providers are registered by the user of a **dotted key prefix**:

```python
prompt_mgr.register_dynamic("skills", _provide_skills)
prompt_mgr.register_dynamic("working_directory", _provide_wd)
prompt_mgr.register_dynamic("date", _provide_date)
prompt_mgr.register_dynamic("project_name", _provide_project_name)
prompt_mgr.register_dynamic("model", _provide_model)
```

When resolving `{{skills.catalog}}`:
1. Look up the longest matching registered prefix → finds `"skills"`
2. Call `_provide_skills(ctx)` → returns a `dict`
3. Walk the dict with the remaining path `.catalog`

When resolving `{{skills}}` (no sub-path):
1. Call `_provide_skills(ctx)` → returns a dict
2. The dict has a `__default__` key (or is converted to string)

Providers can return either a `str` or a `dict`:

```python
def _provide_skills(ctx: AppContext) -> dict:
    return {
        "__default__": skill_manager.get_catalog_xml(),
        "catalog": skill_manager.get_catalog_xml(),
        "names": ", ".join(skill_manager.list_skills()),
    }
```

So `{{skills}}` renders the full catalog XML, `{{skills.catalog}}` renders the same, and `{{skills.names}}` renders a flat comma-separated list.

### 3.3 Resolution order

For a given `{{key}}`:

1. **Static override** — check `prompt_variables` table for `key`. If `source='static'` and `value` is non-empty, use it.
2. **Dynamic provider** — check registered providers. If a provider exists for the key (or its prefix), call it.
3. **Missing** — leave `{{key}}` unchanged in the rendered text.

Static overrides let users pin a specific value without editing the template. For example, a user could override `{{project_name}}` with `"My Corp API"` if the directory basename isn't meaningful.

### 3.4 No `prompt_variables` table (simplified)

After further thought, a separate `prompt_variables` table is over-engineering. Dynamic values come from providers; static values can be embedded directly in the template. If a user wants `{{project_name}}` to resolve to a specific string, they just write that string in the template instead of the placeholder.

**Exception:** The config system already handles per-project overrides. If we ever need per-project variable overrides, they belong in the layered config (`prompt.variables.project_name`), not a separate table. This keeps the schema simple.

---

## 4. Default Prompts

### 4.1 Default chat assistant

```python
DEFAULT_CHAT_PROMPT = {
    "id": "default",
    "name": "Default Assistant",
    "description": "General-purpose coding assistant",
    "template": (
        "You are a helpful AI coding assistant working in {{project_name}}.\n\n"
        "Current working directory: {{working_directory}}\n"
        "Date: {{date}}\n"
        "\n"
        "{{skills}}\n"
        "\n"
        "Use the available tools when appropriate. "
        "The user can activate specific skills for detailed instructions "
        "by using the activate_skill tool.\n"
    ),
    "model": "",
    "scope": "global",
}
```

### 4.2 Inline suggestion prompt

```python
DEFAULT_INLINE_SUGGEST_PROMPT = {
    "id": "inline-suggest",
    "name": "Inline Suggest",
    "description": "Fast code completion for inline suggestions",
    "template": (
        "You are a code completion assistant. Complete the code at the <CURSOR> "
        "marker.\n\n"
        "Output ONLY the raw completion text starting from the cursor position. "
        "This may span multiple lines if a natural completion requires it. "
        "Keep completions brief — typically 1–3 lines, maximum 10.\n\n"
        "Do not include:\n"
        "- Any text before the cursor\n"
        "- Explanations, comments, or reasoning\n"
        "- Markdown code fences or formatting\n\n"
        "If you cannot determine a meaningful completion, output nothing."
    ),
    "model": "",
    "scope": "global",
}
```

### 4.3 Seeding

At bootstrap, `PromptManager.__init__` calls `_seed_defaults()` which inserts default prompts if they don't already exist (matched by `id`). This matches the pattern used by `seed_agents` — idempotent checks via `SELECT 1 FROM prompts WHERE id = ?`.

---

## 5. PromptManager

```python
# core/prompt_registry.py

class PromptManager:
    """Database-backed prompt template registry with {{key}} variable substitution."""

    def __init__(self, db: DatabaseManager, working_directory: str = ""):
        self._db = db
        self._wd = working_directory
        self._providers: dict[str, Callable[[AppContext], str | dict]] = {}
        self._seed_defaults()

    # -- Dynamic provider registration --

    def register_dynamic(self, key: str, provider: Callable) -> None:
        """Register a dynamic variable provider for *key* (or key prefix)."""
        self._providers[key] = provider

    # -- CRUD --

    def create_prompt(self, id, name, description, template, model="", scope="global") -> str: ...
    def get_prompt(self, prompt_id: str) -> dict | None: ...
    def list_prompts(self, scope: str | None = None) -> list[dict]: ...
    def update_prompt(self, prompt_id: str, **kwargs) -> None: ...
    def delete_prompt(self, prompt_id: str) -> None: ...

    # -- Rendering --

    def render(self, prompt_id: str, ctx: AppContext, extra_vars: dict | None = None) -> str:
        """Render a prompt template, resolving all {{key}} placeholders.

        Resolution order for each placeholder:
        1. extra_vars (caller-supplied overrides)
        2. Dynamic providers (context-aware)
        3. Left as {{key}} if unresolved
        """

    # -- Internal --

    def _seed_defaults(self) -> None: ...
    def _resolve_variable(self, key: str, ctx: AppContext, extra_vars: dict) -> str: ...
```

### `render()` in detail

```python
def render(self, prompt_id: str, ctx: AppContext, extra_vars: dict | None = None) -> str:
    row = self.get_prompt(prompt_id)
    if row is None:
        raise ValueError(f"Prompt '{prompt_id}' not found")
    template = row["template"]
    overrides = extra_vars or {}

    def _replace(match: re.Match) -> str:
        key = match.group(1)  # e.g. "skills.catalog" or "date"
        # 1. Caller-supplied overrides (highest priority)
        if key in overrides:
            return overrides[key]
        # 2. Dynamic providers
        resolved = self._resolve_variable(key, ctx)
        if resolved is not None:
            return resolved
        # 3. Leave unchanged
        return match.group(0)

    return _PLACEHOLDER.sub(_replace, template)

def _resolve_variable(self, key: str, ctx: AppContext) -> str | None:
    # Exact match first
    if key in self._providers:
        result = self._providers[key](ctx)
        return result if isinstance(result, str) else str(result)

    # Dotted key: walk providers by prefix
    # e.g. "skills.catalog" → find provider "skills", call it, walk dict
    parts = key.split(".")
    for i in range(len(parts), 0, -1):
        prefix = ".".join(parts[:i])
        if prefix in self._providers:
            result = self._providers[prefix](ctx)
            if isinstance(result, dict):
                return self._walk_dict(result, parts[i:])
            return str(result)

    return None

@staticmethod
def _walk_dict(d: dict, path: list[str]) -> str | None:
    """Walk a nested dict by path segments, falling back to __default__."""
    current = d
    for segment in path:
        if isinstance(current, dict) and segment in current:
            current = current[segment]
        elif isinstance(current, dict) and "__default__" in current:
            # If we can't walk further, use the default
            return str(current["__default__"])
        else:
            return None
    if isinstance(current, dict) and "__default__" in current:
        return str(current["__default__"])
    return str(current) if current is not None else None
```

---

## 6. Configuration

New config keys registered at import time:

```python
from core.config import register_defaults

register_defaults({
    "prompt": {
        "default_id": "default",
        "inline_suggest_id": "inline-suggest",
    },
})
```

The `ChatManager._wire_agent()` method reads `prompt.default_id` from config to decide which prompt template to use. The inline suggest module reads `prompt.inline_suggest_id`.

This means:
- Users can switch the default chat prompt by editing config: `prompt.default_id = "custom:code-review"`
- Project-level config can override: `{wd}/.agents/config.json` sets a project-specific default

---

## 7. Integration Points

### 7.1 Bootstrap (`bootstrap.py`)

Add a new phase between database init and provider init:

```python
def run(self) -> AppContext:
    ...
    database = self._init_database(config)
    prompt_mgr = self._init_prompt_registry(database)  # NEW
    vault = self._init_vault()
    ...
    # Register dynamic providers
    self._register_prompt_providers(prompt_mgr)
    ...
    return AppContext(
        ...,
        prompts=prompt_mgr,  # NEW
    )
```

```python
def _init_prompt_registry(self, db: DatabaseManager) -> PromptManager:
    return PromptManager(db, working_directory=self.wd)

def _register_prompt_providers(self, mgr: PromptManager) -> None:
    mgr.register_dynamic("skills", lambda ctx: {
        "__default__": skill_manager.get_catalog_xml(),
        "catalog": skill_manager.get_catalog_xml(),
        "names": ", ".join(skill_manager.list_skills()),
    })
    mgr.register_dynamic("working_directory", lambda ctx: ctx.working_directory)
    mgr.register_dynamic("project_name", lambda ctx: os.path.basename(ctx.working_directory))
    mgr.register_dynamic("date",
        lambda ctx: datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    mgr.register_dynamic("model", lambda ctx: ctx.config.get("session.model", ""))
```

### 7.2 AppContext (`context.py`)

```python
prompts: PromptManager | None = None
"""Prompt registry — resolves templates with dynamic variables."""
```

### 7.3 ChatManager (`skills/chat/chat_manager.py`)

Current:
```python
agent = Agent(
    provider=provider,
    template="You are a helpful AI assistant. {{extra}}",
    variables={"extra": "Use tools when appropriate."},
    ...
)
```

New:
```python
prompt_id = ctx.config.get("prompt.default_id", "default")
system_prompt = ctx.prompts.render(prompt_id, ctx)
tools = get_tools()
agent = Agent(
    provider=provider,
    template=system_prompt,  # Already rendered, no variables needed
    model=...,              # May come from prompt's model override
    tools=tools,
    ctx=ctx,
)
```

Wait — if `render()` has already resolved all `{{key}}` placeholders, the Agent doesn't need `variables` at all. The template is fully rendered. But we should still support the case where the Agent is constructed ad-hoc without the prompt registry. So the `Agent` class keeps its `template` + `variables` for backward compatibility, but the main ChatManager path uses `PromptManager.render()`.

**Skills XML**: Currently the Agent appends `skills_xml` after the template. With the prompt registry, `{{skills}}` in the template *is* the catalog XML. The Agent should **not** also append skills separately when the template already contains `{{skills}}`. We handle this by:

1. If the rendered prompt already contains `<available_skills>`, don't append.
2. If `skills_xml` is passed to Agent and the prompt doesn't contain skills, append as before.

Or simpler: the `ChatManager._wire_agent()` path stops passing `skills_xml` to Agent entirely, since the template already includes it via `{{skills}}`.

### 7.4 Inline Suggest (`core/inline_suggest.py`)

Current:
```python
_SYSTEM_PROMPT = "You are a code completion assistant..."
```

New:
```python
async def get_inline_suggestion(ctx, ...):
    prompt_id = ctx.config.get("prompt.inline_suggest_id", "inline-suggest")
    system_prompt = ctx.prompts.render(prompt_id, ctx)
    messages = [
        Message(role="system", content=system_prompt),
        Message(role="user", content=context),
    ]
    ...
```

The hardcoded `_SYSTEM_PROMPT` constant is replaced by a PromptManager lookup. The default prompt is seeded into the DB at bootstrap.

### 7.5 Deprecation of `agents` table

- `DatabaseManager.create_agent()` → deprecated (calls still work but write to `prompts` table instead)
- `DatabaseManager.get_agent()` → reads from `prompts` table by id
- `DatabaseManager.list_agents()` → reads from `prompts` table
- `DatabaseManager.delete_agent()` → deletes from `prompts` table
- `DatabaseManager.seed_agents()` → becomes `seed_prompts()` (internal, called by PromptManager)
- `agents` table is not dropped for backward compatibility

The four original `agents` methods on `DatabaseManager` are **deprecated but still functional** — they now read/write the `prompts` table. This gives existing callers a smooth migration path.

---

## 8. Test Plan

| Area | Tests |
|---|---|
| `render_template()` | Dotted keys, missing keys, nested dict walks, `__default__` fallback |
| `PromptManager` CRUD | Create, get, list, update, delete prompts |
| `PromptManager.render()` | Full render with dynamic providers, overrides, missing variables |
| `PromptManager._seed_defaults()` | Idempotent — second call doesn't overwrite |
| Dynamic providers | `{{skills}}`, `{{skills.catalog}}`, `{{skills.names}}`, `{{working_directory}}`, `{{date}}` |
| Integration | `ChatManager._wire_agent()` uses prompt registry instead of hard-coded template |
| Integration | Inline suggest reads prompt from registry |
| Agents deprecation | Old CRUD methods redirect to `prompts` table |
| Config key | `prompt.default_id` and `prompt.inline_suggest_id` flow through bootstrap |

---

## 9. File Changes Summary

| File | Change |
|---|---|
| **`core/prompt_registry.py`** | **NEW** — `PromptManager` class, table creation, CRUD, rendering, dynamic providers |
| **`core/agent.py`** | Update `_PLACEHOLDER` regex to support dotted keys; `render_template()` handles dict returns |
| **`core/database.py`** | Add `prompts` table creation; redirect `agents` CRUD to `prompts`; deprecation warnings |
| **`context.py`** | Add `prompts: PromptManager \| None` field |
| **`bootstrap.py`** | Add `_init_prompt_registry()` phase; register providers |
| **`core/config.py`** | Register `prompt.default_id` and `prompt.inline_suggest_id` defaults |
| **`core/inline_suggest.py`** | Replace hardcoded `_SYSTEM_PROMPT` with PromptManager lookup |
| **`skills/chat/chat_manager.py`** | Replace hard-coded template with `ctx.prompts.render()` |
| **`skills/chat/chat_tab.py`** | Pass `ctx` through to ChatManager for prompt resolution |
| **`config/config.json`** | Add `prompt.default_id` and `prompt.inline_suggest_id` |
| **`conftest.py`** | Add `PromptManager` fixture |
| **`tests/test_prompt_registry.py`** | **NEW** — comprehensive test suite |
| **`tests/test_agent.py`** | Update `render_template` tests for dotted keys |

---

## 10. Future Extensions

- **Per-skill filtering**: `{{skills.git}}` renders only the git skill's body — requires each skill to register its own provider under `skills.*`
- **Prompt editor UI**: A sidebar panel for creating and editing prompt templates with live preview
- **Prompt versioning**: An `updated_at` timestamp enables diff views and undo
- **Agent profiles**: A higher-level concept that bundles a prompt + model + enabled skills into a named profile (could be a future skill with a `components/` sidebar panel)