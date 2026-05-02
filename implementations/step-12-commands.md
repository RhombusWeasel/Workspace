# Step 12: Slash Commands

**Branch:** `step-12-commands`  
**Date:** 2026-05-02

---

## Overview

User-typed `/command` handler registry. Commands are registered via the
`@register_command()` decorator at import time and discovered from Python
modules in tiered `cmd/` directories (core + skills).

Distinct from tools (agent-invoked) and leader chords (keyboard-driven menu)
per § 6.3.

---

## Implementation

### `core/commands.py`

#### `Command` dataclass

```python
@dataclass
class Command:
    name: str
    description: str
    handler: Callable[[Any, str], Coroutine[Any, Any, Any]]
```

Handlers are async callables that receive `(app, args: str)` where `app` is
the Textual app instance and `args` is the user-provided argument string.

#### Module-level state

```python
_commands: dict[str, Command] = {}
```

#### Public API

| Function | Returns | Description |
|---|---|---|
| `register_command(*, name, description)` | decorator | Register an async handler as a slash command |
| `get_commands()` | `dict[str, Command]` | All registered commands |
| `list_commands()` | `list[str]` | Sorted command names |
| `execute_command(name, app, args)` | `Any` | Call handler by name |
| `load_commands_from_paths(paths)` | — | Import .py files from dirs, triggering registration |
| `reset_commands()` | — | Clear all (test isolation) |

#### Directory loading (`load_commands_from_paths`)

```python
for each directory in paths:
    if directory exists:
        for each .py file (excluding __init__.py):
            import via importlib.util (spec_from_file_location → exec_module)
```

This mirrors the tool loading pattern — importing a file triggers
`@register_command()` decorators at import time. Directories that don't exist
are silently skipped.

The module is imported under the `cody.cmd.{mod_name}` namespace to avoid
naming collisions.

#### Usage pattern

```python
# In a command file (e.g., cmd/clear.py):
from core.commands import register_command

@register_command(name="clear", description="Clear the chat buffer")
async def clear(app, args: str) -> None:
    app.query_one("#chat-tab").clear()
```

```python
# In bootstrap:
from core.commands import load_commands_from_paths
from core.skills import skill_manager

# Core commands
load_commands_from_paths(["cmd/"])

# Skill commands
load_commands_from_paths(skill_manager.get_skill_cmd_dirs())
```

---

## Tests

### `tests/test_commands.py` — 10 tests in 5 classes

| Class | Tests | Coverage |
|---|---|---|
| `TestRegistration` | 3 | Single, multiple, duplicate rejection |
| `TestExecution` | 3 | With args, no args, unknown raises KeyError |
| `TestReset` | 1 | Clears all |
| `TestDirectoryLoading` | 2 | Loads from .py files in dir, skips nonexistent dirs |
| `TestListing` | 1 | Sorted names via `list_commands()` |

All tests use the `_reset_commands` autouse fixture.

---

## Design Decisions

1. **Decorator pattern matching tools.** Commands use the same module-level
   globals + `@register_command()` pattern as the tool registry. This keeps
   the extension mechanism consistent — skill authors use `@register_tool()`
   for agent tools and `@register_command()` for user commands.

2. **Async handlers.** Commands take `(app, args)` as async coroutines. This
   allows commands to interact with the Textual app (query widgets, post
   messages) without blocking the event loop.

3. **`importlib.util` for dynamic imports.** Rather than `exec()` or
   `__import__()`, uses `spec_from_file_location` + `exec_module` which is
   the standard library approach for importing arbitrary .py files.

4. **Commands, tools, leader chords are three separate registries** per § 6.3.
   No merging — each serves a fundamentally different invocation context.
