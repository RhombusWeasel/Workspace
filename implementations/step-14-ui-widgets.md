# Step 14: Shared UI Widgets

**Branch:** `step-14-ui-widgets`  
**Date:** 2026-05-02

---

## Overview

Reusable ModalScreen widgets shared across the application. Currently
includes `InputModal` for single-line text prompts and `CommandsHelp`
for displaying available slash commands.

---

## Implementation

### `ui/widgets/input_modal.py` — `InputModal`

Single-line text prompt modal. Returns the entered string on submit or
`None` on cancel.

```python
InputModal(
    prompt="Enter chat title:",
    label="Title",
    default="",
    password=False,  # mask input for passwords
)
```

**Layout:**
```
┌──────────────────────────────────────────┐
│ Enter chat title:                        │
│ ┌──────────────────────────────────────┐ │
│ │ Title                                │ │
│ └──────────────────────────────────────┘ │
│                     [ OK ] [ Cancel ]     │
└──────────────────────────────────────────┘
```

**Behaviors:**
- Input auto-focused on mount
- `Enter` in input → dismiss with value
- `OK` button → dismiss with value
- `Cancel` button → dismiss with `None`
- `password=True` → uses Textual's `Input(password=True)` for masked entry

### `ui/widgets/commands_help.py` — `CommandsHelp`

Modal overlay listing all registered slash commands from the registry.

Reads from `core.commands.get_commands()` and renders as:
```
┌──────────────────────────────────────────┐
│            Slash Commands                │
│                                          │
│  /clear  —  Clear the chat buffer        │
│  /help   —  Show help information        │
│                                          │
│           Escape to close                │
└──────────────────────────────────────────┘
```

Escape dismisses the modal.

### Existing widgets in this directory

| File | Description | Built in |
|---|---|---|
| `leader_overlay.py` | `LeaderOverlay` — `Ctrl+Space` chord navigator | Step 12/13 |
| `input_modal.py` | `InputModal` — single-line text prompt | Step 14 |
| `commands_help.py` | `CommandsHelp` — slash command listing | Step 14 |

---

## Tests

### `tests/test_widgets.py` — 6 tests in 2 classes

| Class | Tests | Coverage |
|---|---|---|
| `TestInputModal` | 4 | Submit returns value, cancel returns None, default prefilled, password mode |
| `TestCommandsHelp` | 2 | Displays registered commands, handles empty registry |

All tests use `WidgetTestApp` — a minimal Textual app with `run_test()` pilot.

---

## Design Decisions

1. **ModalScreen for dialogs.** Textual's `ModalScreen` provides free
   Escape-to-dismiss and focus trapping. Custom `on_key` handlers extend
   this for type-specific behavior (e.g., `CommandsHelp` re-handles
   Escape for clarity).

2. **InputModal returns `str | None`.** Type-parameterized
   `ModalScreen[str | None]` makes the expected return type explicit for
   callers using `push_screen_wait()`.

3. **CommandsHelp reads live registry.** Calls `get_commands()` at
   compose time, so it always reflects the current state. This is fine
   since commands don't change at runtime (they're registered at import
   time during bootstrap).

---

## Usage Pattern

```python
# Prompt for input
modal = InputModal("Enter a name:", "Name")
name = await app.push_screen_wait(modal)
if name:
    do_something(name)

# Show available commands
app.push_screen(CommandsHelp())
```
