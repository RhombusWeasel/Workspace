# UI Widgets

**Files:** `ui/widgets/input_modal.py`, `ui/widgets/confirm_modal.py`
**Depends on:** Textual (`ModalScreen`, `Input`, `Button`, `Static`)

---

## Purpose

Reusable modal dialogs for user interaction.  These widgets are used by
tools, commands, and event handlers to prompt the user or confirm
destructive actions.

---

## InputModal

**File:** `ui/widgets/input_modal.py`

A single-line text prompt dialog.  Returns the entered text on submit
or `None` on cancel.

### Constructor

```python
from ui.widgets.input_modal import InputModal

modal = InputModal(
    prompt="Enter your API key:",
    label="API Key",
    default="sk-",
    password=True,
)
```

| Parameter | Type | Default | Description |
|---|---|---|---|
| `prompt` | `str` | — | Instructional text shown above the input |
| `label` | `str` | `""` | Placeholder text for the input field |
| `default` | `str` | `""` | Pre-filled value |
| `password` | `bool` | `False` | Mask the input (for secrets) |

### Usage

```python
# From an async context (tool, command, or worker)
result = await app.push_screen_wait(modal)
if result is not None:
    # User submitted — result is the entered string
    process(result)
else:
    # User cancelled
    pass
```

### Example: Vault unlock handler

```python
@register_handler("vault.needs_unlock")
def _on_vault_needs_unlock(data: dict, ctx: AppContext) -> None:
    app = ctx.app
    if app is None:
        return

    async def do_prompt() -> None:
        result = await app.push_screen_wait(
            InputModal("Enter master password:", password=True)
        )
        if result is None:
            return
        ctx.vault.unlock(result)

    app.run_worker(do_prompt())
```

Since `@register_handler` functions are synchronous, you must wrap
async operations in a worker via `app.run_worker()`.

---

## ConfirmModal

**File:** `ui/widgets/confirm_modal.py`

A confirmation dialog with a scrollable body.  Returns `True` when
confirmed, `None` when cancelled.

### Constructor

```python
from ui.widgets.confirm_modal import ConfirmModal

modal = ConfirmModal(
    title="Run this command?",
    body="rm -rf /tmp/old_builds",
    confirm_label="Run",
)
```

| Parameter | Type | Default | Description |
|---|---|---|---|
| `title` | `str` | — | Heading text |
| `body` | `str` | — | Scrollable content (command, diff, etc.) |
| `confirm_label` | `str` | `"Confirm"` | Text for the confirm button |

### Usage

```python
# From an async context
confirmed = await app.push_screen_wait(modal)
if confirmed:
    # User clicked Confirm
    execute_destructive_action()
else:
    # User clicked Cancel or dismissed
    pass
```

### Example: run_command tool

```python
@register_tool(name="run_command", ...)
async def run_command(command: str, ctx: AppContext | None = None) -> str:
    if ctx is None or ctx.app is None:
        return "Error: no application context."

    modal = ConfirmModal(
        title="Run this command?",
        body=f"Directory: {ctx.working_directory}\n\n{command}",
        confirm_label="Run",
    )
    confirmed = await ctx.app.push_screen_wait(modal)
    if not confirmed:
        return "Command cancelled by user."

    # Execute the command
    ...
```

---

## Pattern: Pushing Modals from Sync Handlers

Event handlers registered via `@register_handler` are **synchronous**
functions, but modal screens require `await`.  Use `app.run_worker()` to
bridge this gap:

```python
@register_handler("my_plugin.prompt")
def _on_prompt(data: dict, ctx: AppContext) -> None:
    app = ctx.app
    if app is None:
        return

    async def do_prompt() -> None:
        result = await app.push_screen_wait(
            InputModal("Enter value:")
        )
        if result is not None:
            # Process the result
            ctx.config.set("my_plugin.value", result)
            ctx.config.save()

    app.run_worker(do_prompt())
```

---

## Pattern: Pushing Modals from Async Tools

Tools declared as `async def` can `await` directly:

```python
@register_tool(name="confirm_action", ...)
async def confirm_action(action: str, ctx: AppContext | None = None) -> str:
    if ctx is None or ctx.app is None:
        return "Error: no app context."

    confirmed = await ctx.app.push_screen_wait(
        ConfirmModal("Confirm action?", body=action)
    )
    if confirmed:
        return f"Action '{action}' confirmed."
    return "Action cancelled."
```

---

## Pattern: Pushing Modals from Slash Commands

Slash commands receive `app` directly and are async:

```python
@register_command(name="ask_name", description="Ask the user's name")
async def ask_name(app, args: str) -> str:
    result = await app.push_screen_wait(
        InputModal("What is your name?")
    )
    if result is None:
        return "Cancelled."
    app.notify(f"Hello, {result}!")
    return f"Name set to {result}."
```