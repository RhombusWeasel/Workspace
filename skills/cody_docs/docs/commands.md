# Slash Commands

**File:** `core/commands.py`
**Depends on:** `importlib.util`, `os`

---

## Purpose

Slash commands are user-typed `:prefix` commands in the chat input (e.g.
`/plugin list`, `/clear`).  They are distinct from tools (LLM-invoked)
and leader chords (keyboard-driven menu).  Commands register at import
time via `@register_command()`.

---

## Architecture

```
User types "/plugin install <url>"
       │
       ▼
ChatInput.on_input_submitted() or CommandPalette
       │
       ▼
execute_command(name, app, args)
       │
       ▼
_commands[name].handler(app, args)  →  async function
```

- Commands are async functions that receive `(app, args)`.
- `app` is the running `CodyApp` instance.
- `args` is the raw text after the command name (may be empty).

---

## API

### `@register_command(name, description)`

```python
from core.commands import register_command

@register_command(name="clear", description="Clear the chat")
async def clear(app, args: str) -> None:
    ...
```

| Parameter | Type | Description |
|---|---|---|
| `name` | `str` | Unique command name (no `/` prefix). |
| `description` | `str` | Short description shown in command palette. |

The decorated function must be `async def` with signature
`(app: Any, args: str) -> Any`.

### `get_commands() → dict[str, Command]`

Return all registered commands as a `{name: Command}` dict.

### `list_commands() → list[str]`

Return sorted list of registered command names.

### `execute_command(name, app, args) → Any`

Look up a command by name and call its handler.  Raises `KeyError` if
the command is not registered.

### `load_commands_from_paths(paths)`

Import every `.py` file (except `__init__.py` and `_`-prefixed) in each
directory in `paths`, triggering `@register_command()` decorators at import
time.  Directories that don't exist are silently skipped.

### `reset_commands()`

Clear all registered commands.  Use between tests.

---

## Command Data

```python
@dataclass
class Command:
    name: str
    description: str
    handler: Callable[[Any, str], Coroutine[Any, Any, Any]]
```

---

## How Commands Are Discovered at Startup

The bootstrap sequence loads commands from two sources:

1. **Core commands** — every `.py` file in `{cody_dir}/cmd/` is imported.
2. **Skill commands** — every `.py` file in each enabled skill's `cmd/`
   subdirectory is imported.

Put your command in a `cmd/` subdirectory within your plugin or skill:

```
plugins/my_plugin/
├── SKILL.md
├── __init__.py
├── cmd/
│   └── mycommand.py     ← auto-discovered
└── ...
```

Or in a skill:

```
skills/my_skill/
├── SKILL.md
├── cmd/
│   └── mycommand.py     ← auto-discovered
└── ...
```

---

## Writing a Command: Complete Example

```python
# plugins/my_plugin/cmd/greet.py
from core.commands import register_command

@register_command(name="greet", description="Show a greeting notification")
async def greet(app, args: str) -> str:
    name = args.strip() or "stranger"
    app.notify(f"Hello, {name}!", title="Greeting")
    return f"Greeted {name}."
```

**Important:** the module containing `@register_command` must be imported
at plugin load time.  If the file lives in the skil's `cmd/` directory,
the bootstrap loader discovers and imports it automatically.  If it lives
elsewhere, import it from `__init__.py`:

```python
# plugins/my_plugin/__init__.py
from plugins.my_plugin.cmd import greet  # noqa: F401
```

---

## Accessing Config and Vault from Commands

Commands receive `app` — use `app.context` to reach all services:

```python
@register_command(name="show_config", description="Show a config value")
async def show_config(app, args: str) -> str:
    ctx = app.context
    key = args.strip()
    if not key:
        return "Usage: /show_config <key>"
    value = ctx.config.get(key)
    return f"{key} = {value!r}"
```

---

## Testing

```python
from core.commands import register_command, execute_command, reset_commands

@pytest.mark.asyncio
async def test_my_command():
    reset_commands()

    @register_command(name="test_cmd", description="Test")
    async def test_cmd(app, args: str) -> str:
        return f"got: {args}"

    result = await execute_command("test_cmd", None, "hello")
    assert result == "got: hello"
```

---

## Design Decisions

1. **Async handlers only** — Commands may push screens (`push_screen_wait`),
   show notifications, or perform async I/O.  All handlers are async.

2. **Distinct from tools and leader chords** — Three separate registries
   for three invocation contexts: tools (LLM calls), commands (user types
   `/command`), chords (keyboard menu).  This avoids confusion about
   who triggers what.

3. **Auto-discovery from `cmd/` directories** — Skills and plugins can
   contribute commands by dropping `.py` files into `cmd/`.  No manual
   wiring needed.

4. **App as first parameter** — Commands need full access to the app
   for UI operations.  Unlike tools (which receive `ctx`), commands
   receive `app` directly because they are always user-initiated and
   always have an app running.