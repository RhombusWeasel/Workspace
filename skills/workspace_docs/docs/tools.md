# Tool Registry

**File:** `core/tools.py`
**Depends on:** `inspect`, `context.py` (AppContext, for context injection)

---

## Purpose

The tool registry lets skills, skills, and core modules expose Python
functions that the LLM can invoke during a conversation.  Tools register
themselves at import time via the `@register_tool()` decorator — the same
self-registration pattern used by `@register_handler()`, `@register_command()`,
and `@register_sidebar_tab()`.

The registry produces JSON Schema definitions suitable for passing directly
to `BaseProvider.chat()` / `stream_chat()`.  The `Agent` class uses
`get_tools()` to build the tool list and `execute_tool()` to dispatch LLM
tool calls.

---

## Architecture

```
@register_tool(name="my_tool", tags=["system"], ...)
  │
  ▼
_tools[name] = (fn, tags, description, parameters)
  │
  ├── get_tools(tags=None)   →  JSON Schema list for LLM
  │   (respects enable/disable per-tool and per-tag)
  │
  └── execute_tool(name, args, ctx)  →  call the function
       (auto-injects ctx if signature declares it)
```

- Tools are **plain Python functions** (sync or async).
- Registration is **module-level and import-time** — decorators fire when
  their containing module is imported by the bootstrap loader.
- `get_tools()` respects per-tool and per-tag enable/disable state.
- `execute_tool()` inspects the function signature and auto-injects
  `ctx` (AppContext) if a `ctx` parameter is declared.

---

## API

### `@register_tool(name, description, parameters, tags=None)`

```python
from core.tools import register_tool

@register_tool(
    name="read_file",
    tags=["files"],
    description="Read the contents of a file.",
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the file to read.",
            },
        },
        "required": ["path"],
    },
)
def read_file(path: str, ctx: AppContext | None = None) -> str:
    ...
```

| Parameter | Type | Description |
|---|---|---|
| `name` | `str` | Unique tool name.  Must not already be registered. |
| `tags` | `list[str] \| None` | Optional tag list for grouping.  Defaults to `[]`. |
| `description` | `str` | Human-readable description sent to the LLM. |
| `parameters` | `dict[str, Any]` | JSON Schema `parameters` object describing the tool's input shape. |

The decorated function may be sync or `async def`.  If the function
signature includes a parameter named `ctx`, `execute_tool()` injects
the `AppContext` automatically.

### `get_tools(tags=None) → list[dict[str, Any]]`

Returns enabled tools as JSON Schema `function` definitions:

```python
# All enabled tools
tools = get_tools()

# Only tools tagged "system"
tools = get_tools(tags="system")

# Tools tagged "system" OR "files" (union)
tools = get_tools(tags=["system", "files"])
```

Each entry looks like:

```json
{
  "type": "function",
  "function": {
    "name": "read_file",
    "description": "Read the contents of a file.",
    "parameters": { ... }
  }
}
```

### `execute_tool(name, args, ctx=None) → Any`

Look up a tool by name and call it with `args`.  Handles both sync and
async functions:

```python
result = execute_tool("read_file", {"path": "/tmp/test.txt"}, ctx=app_context)
# If the tool is async, result is a coroutine — caller must await
if inspect.iscoroutine(result):
    result = await result
```

If the tool's signature has a `ctx` parameter, the supplied `ctx`
(AppContext) is injected into the call automatically.

Raises `KeyError` if the tool name is not registered.

### `disable_tool(name)` / `enable_tool(name)`

Hide or restore a tool from `get_tools()` output.  Does NOT prevent
`execute_tool()` from calling the function — only controls LLM visibility.

```python
disable_tool("run_command")    # LLM won't see it
enable_tool("run_command")     # LLM can see it again
```

### `disable_group(tag)` / `enable_group(tag)`

Hide or restore all tools with a given tag:

```python
disable_group("system")   # All tools tagged "system" hidden from LLM
enable_group("system")     # Restored
```

### `reset()`

Clears all registered tools, disabled state, and disabled groups.
Use between tests.

---

## Context Injection

Tools that need access to the app context (config, vault, working
directory, app instance) declare a `ctx` parameter in their signature:

```python
@register_tool(
    name="run_command",
    tags=["system"],
    description="Run a shell command after user confirmation.",
    parameters={...},
)
async def run_command(command: str, ctx: AppContext | None = None) -> str:
    if ctx is None or ctx.app is None:
        return "Error: no application context."
    confirmed = await ctx.app.push_screen_wait(
        ConfirmModal("Run this command?", body=command)
    )
    ...
```

`execute_tool()` inspects the function signature and injects `ctx` when
the parameter is present.  Tools that don't need context simply omit
the parameter.

---

## Tool Tags

Tags group tools for filtering and bulk enable/disable.  Convention:

| Tag | Purpose | Example tools |
|---|---|---|
| `system` | System-level operations | `run_command` |
| `files` | File read/write/edit | `read_file`, `write_file`, `edit_file` |
| `skills` | Skill activation | `activate_skill`, `run_skill` |

Plugins should use their skill name as a tag:

```python
@register_tool(name="db_query", tags=["database"], ...)
```

---

## How Tools Are Discovered at Startup

The bootstrap sequence loads tools from two sources:

1. **Core tools** — every `.py` file in `{workspace_dir}/tools/` is imported.
2. **Skill tools** — every `.py` file in each enabled skill's `tools/`
   subdirectory is imported.

Importing the module triggers the `@register_tool()` decorator, which
registers the tool in the module-level `_tools` dict.

---

## Writing a Tool: Complete Example

This example shows a tool registered by a skill that queries a database:

```python
# skills/database/tools/db_query.py
from core.tools import register_tool
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from context import AppContext


@register_tool(
    name="db_query",
    tags=["database"],
    description=(
        "Execute a SQL query against the configured database connection. "
        "Returns up to 100 rows as a formatted table."
    ),
    parameters={
        "type": "object",
        "properties": {
            "sql": {
                "type": "string",
                "description": "The SQL query to execute.",
            },
            "connection": {
                "type": "string",
                "description": "Name of the database connection to use.",
            },
        },
        "required": ["sql"],
    },
)
def db_query(sql: str, connection: str = "default", ctx: AppContext | None = None) -> str:
    if ctx is None or ctx.db_connections is None:
        return "Error: no database connection available."

    try:
        result = ctx.db_connections.execute(connection, sql)
        return result.to_string()
    except Exception as exc:
        return f"Query error: {exc}"
```

**Important:** the module containing this tool must be imported (directly
or transitively) by the skill's `__init__.py`.  Put tools in a
`tools/` subdirectory within your skill or skill, and the bootstrap
loader will discover them automatically.

---

## Testing

```python
from core.tools import register_tool, execute_tool, get_tools, reset

def test_my_tool():
    reset()  # clear the registry first

    @register_tool(
        name="test_tool",
        tags=["test"],
        description="A test tool.",
        parameters={"type": "object", "properties": {"x": {"type": "integer"}}},
    )
    def test_tool(x: int) -> str:
        return str(x * 2)

    # Tool appears in get_tools()
    tools = get_tools()
    assert any(t["function"]["name"] == "test_tool" for t in tools)

    # Can execute
    result = execute_tool("test_tool", {"x": 5})
    assert result == "10"

    # Disable hides from LLM but execute still works
    disable_tool("test_tool")
    assert not any(t["function"]["name"] == "test_tool" for t in get_tools())
    assert execute_tool("test_tool", {"x": 3}) == "6"
```

---

## Design Decisions

1. **Module-level singleton registry** — Same pattern as `@register_handler()`
   and `@register_command()`.  No class wrapping needed; decorators
   self-register at import time.

2. **JSON Schema parameters** — The `parameters` dict must be a valid JSON
   Schema object.  This is the format that LLM providers expect.  No
   custom parameter format.

3. **Async support** — `execute_tool()` returns coroutines as-is for the
   caller to await.  This lets tools use `await ctx.app.push_screen_wait()`
   and other async Textual APIs.

4. **Context injection via signature inspection** — Rather than passing
   `ctx` to every tool (most don't need it), `execute_tool()` inspects
   the function signature and only injects `ctx` when the parameter
   exists.  This keeps simple tools simple.

5. **Enable/disable is LLM-only** — Disabling a tool hides it from the
   JSON Schema list sent to the LLM, but `execute_tool()` can still call
   it.  This allows internal tools that the LLM shouldn't invoke directly.

6. **Tag-based grouping** — Tags enable bulk hide/show (e.g. hide all
   "system" tools in a restricted session) and targeted queries (e.g.
   return only "database" tools for a DB-focused agent).