# Workspace Event System

**File:** `core/events.py`
**Depends on:** `context.py` (AppContext), `textual.message.Message`

---

## Purpose

A single-envelope message bus that decouples components from the application.
Any widget, skill, or service can post a `WorkspaceEvent`, and any module can
handle it — without either side knowing about the other at import time.

The app needs exactly **one** handler, forever:

```python
def on_workspace_event(self, event: WorkspaceEvent) -> None:
    dispatch(event, self.context)
```

Every feature registers handlers via the `@register_handler(...)` decorator;
the app file never grows.

---

## Architecture

```
┌──────────────┐    post_message(WorkspaceEvent)    ┌──────────┐
│  Any Widget  │ ─────────────────────────────▶│ WorkspaceApp  │
│  or Service  │                               │          │
└──────────────┘                               │ dispatch │
                                               │  (event, │
                                               │  context)│
                                               └────┬─────┘
                                                    │
                      ┌─────────────────────────────┼──────────────────────────┐
                      ▼                             ▼                          ▼
              ┌──────────────┐             ┌──────────────┐           ┌──────────────┐
              │ @register_   │             │ @register_   │           │ @register_   │
              │ handler("a") │             │ handler("b") │           │ handler("b") │
              └──────────────┘             └──────────────┘           └──────────────┘
```

- Events are Textual `Message` objects (namespace `"workspace"`).  They bubble
  up the DOM naturally.
- The module-level `_handler_registry` dict maps `event_type` strings to
  lists of callables.
- Handlers self-register at import time via the decorator — identical
  pattern to `@register_tool()`.

---

## API

### `WorkspaceEvent`

```python
class WorkspaceEvent(Message):
    namespace = "workspace"

    def __init__(self, event_type: str, data: dict[str, Any] | None = None):
        self.event_type: str = event_type
        self.data: dict[str, Any] = data or {}
```

`event_type` is a dotted string (convention: `"domain.action"`, e.g.
`"vault.needs_unlock"`, `"workspace.split"`).  `data` carries arbitrary
payload.

### `dispatch(event, ctx)`

```python
def dispatch(event: WorkspaceEvent, ctx: AppContext) -> None:
    for handler in _handler_registry.get(event.event_type, []):
        handler(event.data, ctx)
```

Called once from `WorkspaceApp.on_workspace_event()`.  Iterates all handlers
registered for `event.event_type` and calls them with the event's data
and the app context.

### `@register_handler(event_type)`

```python
@register_handler("vault.needs_unlock")
def _on_vault_needs_unlock(data: dict, ctx: AppContext) -> None:
    ...
```

Decorator that appends the decorated function to the handler list for
`event_type`.  Handlers receive:

| Parameter | Type | Description |
|---|---|---|
| `data` | `dict[str, Any]` | Payload from the `WorkspaceEvent` |
| `ctx` | `AppContext` | Service locator with config, vault, database, and `ctx.app` |

Handlers are **synchronous** functions.  If you need to `await` an async
operation (e.g. `push_screen_wait`), launch it via `app.run_worker()`:

```python
async def do_prompt() -> None:
    result = await app.push_screen_wait(InputModal("..."))

app.run_worker(do_prompt())
```

### `reset_handlers()`

```python
def reset_handlers() -> None:
    _handler_registry.clear()
```

Clears all registered handlers.  Call between tests to prevent cross-test
pollution.

---

## `AppContext.app` — Accessing the TUI from handlers

Handlers often need the running `WorkspaceApp` instance (to push screens, show
notifications, query the DOM).  The app sets `context.app = self` in its
constructor:

```python
# main.py
class WorkspaceApp(App):
    def __init__(self, context: AppContext):
        context.app = self
        ...
```

Handlers access it via `ctx.app`:

```python
@register_handler("vault.needs_unlock")
def _on_vault_needs_unlock(data: dict, ctx: AppContext) -> None:
    app = ctx.app
    if app is None:
        return
    # Push a modal via an async worker — handlers are sync,
    # so async operations must be launched through run_worker().
    async def do_prompt() -> None:
        result = await app.push_screen_wait(InputModal("Enter password", password=True))
        if result is None:
            return
        ctx.vault.unlock(result)
        # ... rebuild UI after unlock

    app.run_worker(do_prompt())
```

---

## Event Naming Convention

Use dotted `"domain.action"` strings:

| Domain | Example | Meaning |
|---|---|---|
| `workspace.*` | `workspace.split` | Workspace lifecycle events (data carries details) |
| `vault.*` | `vault.needs_unlock` | Vault state events |
| `app.*` | `app.open_leader` | Application-level commands |
| `db.*` | `db.open_query` | Database skill events |
| `files.*` | `files.edit` | File browser events |
| `terminal.*` | `terminal.open` | Terminal skill events |
| Skill domains | `analysis.complete` | Skill-specific events |

Two or more dots is fine for sub-actions: `leader.workspace.toggle_left`.

---

## Registration Order & Timing

- Handlers register at **import time** when the module containing the
  `@register_handler` decorator is loaded.
- The `bootstrap.py` sequence ensures all core modules and skill tools
  are imported before the app starts.
- For skills, import their handler modules during tool loading so handlers
  are registered before any events fire.

---

## Testing

Handlers are isolated via `reset_handlers()`.  Test pattern:

```python
from core.events import WorkspaceEvent, dispatch, register_handler, reset_handlers

def test_my_handler():
    reset_handlers()
    calls = []

    @register_handler("test.event")
    def handler(data, ctx):
        calls.append(data)

    dispatch(WorkspaceEvent("test.event", {"x": 1}), AppContext())
    assert calls == [{"x": 1}]
```

For integration tests, create a real `AppContext` with a test config and
mock database.  The handler receives the full context.

---

## Design Decisions

1. **Module-level singleton registry** — same pattern as `@register_tool()`.
   No class wrapping needed; decorators self-register at import time.

2. **`AppContext` as handler parameter (not app)** — handlers get the service
   locator so they can access config, vault, database.  `ctx.app` provides
   the app when UI interaction is needed.  This keeps the dispatch signature
   stable even as the app evolves.

3. **Separate from leader chords and slash commands** — three distinct
   registries for three distinct invocation contexts (LLM tool calls,
   user-typed commands, keyboard chords).  See §6.3 of the design document.

4. **One `on_workspace_event` in the app** — the app is a hub, not a switchboard.
   No `if/elif` chains.
