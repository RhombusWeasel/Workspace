# Event System

**Branch:** `step-event-system`  
**Date:** 2026-05-01

---

## Overview

A single-envelope message bus that lets skills and components communicate
with the app without TuiApp growing a handler per feature.

**One Message type** (`CodyEvent`) carries a string `event_type` and a `data`
dict. **One app handler** (`on_cody_event`) dispatches to registered functions.

Skills use the same self-registration decorator pattern they already know
from `@register_tool()`.

---

## Files

### `core/events.py`

| Symbol | Purpose |
|---|---|
| `CodyEvent` | Textual `Message` subclass. `namespace = "cody"`. Fields: `event_type: str`, `data: dict` |
| `register_handler(event_type)` | Decorator. Registers the function as a handler for `event_type` |
| `dispatch(event, ctx)` | Calls all handlers registered for `event.event_type`, passing `(data, ctx)` |
| `reset_handlers()` | Clears the global handler registry (test isolation) |

**Usage in TuiApp:**
```python
class TuiApp(App):
    def on_cody_event(self, msg: CodyEvent) -> None:
        dispatch(msg, self.context)
```

**Usage in a skill:**
```python
from core.events import register_handler

@register_handler("analysis.complete")
def on_analysis(data: dict, ctx: AppContext) -> None:
    ctx.database.save(...)
```

**Posting from any widget:**
```python
self.post_message(CodyEvent("chat.send", {"text": "Hello"}))
```

### `context.py`

Minimal `AppContext` dataclass — service locator placeholder. Fields all
default to `None`/`""` so it can be constructed trivially in tests.

```python
@dataclass
class AppContext:
    config: Config | None = None
    skills: SkillManager | None = None
    database: DatabaseManager | None = None
    leader: LeaderRegistry | None = None
    working_directory: str = ""
```

Will be populated with real services in Step 12 (Bootstrap).

---

## Tests

### `tests/test_events.py` — 13 tests

| Class | Tests | Covers |
|---|---|---|
| `TestCodyEvent` | 3 | defaults construction, with data, is Textual Message |
| `TestRegisterHandler` | 4 | decorator returns fn, handler called on dispatch, multiple handlers per event, context passed through |
| `TestDispatch` | 4 | no handlers = no error, wrong event not called, data passthrough, empty data |
| `TestResetHandlers` | 2 | clears all, re-register after reset |

Fixture `_clean_registry` (autouse) calls `reset_handlers()` before and after
every test — ensures zero cross-test pollution.

---

## Design Decisions

1. **Single envelope, not per-feature Messages.** Avoids ballooning TuiApp
   with `on_skill_x`, `on_skill_y` handlers. One `on_cody_event` handles
   everything.

2. **String-keyed event types, not class hierarchies.** Simpler, discoverable,
   no import chains. Skills don't need to define or import Message subclasses.

3. **Same decorator pattern as tools.** `@register_handler("name")` mirrors
   `@register_tool("name")`. One mental model for skill authors.

4. **Global registry with explicit reset.** Module-level `_handler_registry`
   dict, just like the tool registry. `reset_handlers()` for test isolation
   mirrors `reset_tools()` (coming in Step 7).

5. **AppContext is a service locator.** Handlers receive it to access config,
   database, etc. Not a DI container — tools and skills still self-register
   at module level.
