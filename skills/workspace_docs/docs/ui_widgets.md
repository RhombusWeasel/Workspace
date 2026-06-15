# UI Widgets

**Files:** `ui/widgets/input_modal.py`, `ui/widgets/confirm_modal.py`
**Depends on:** Textual (`ModalScreen`, `Input`, `Button`, `Static`)

---

## InputModal

**File:** `ui/widgets/input_modal.py`

A single-line text prompt dialog. Returns the entered text on submit or `None` on cancel.

```python
from ui.widgets.input_modal import InputModal

modal = InputModal(
    prompt="Enter your API key:",
    label="API Key",
    default="sk-",
    password=True,       # mask input (for secrets)
)
result = await app.push_screen_wait(modal)
# result is the entered string, or None if cancelled
```

| Parameter | Type | Default | Description |
|---|---|---|---|
| `prompt` | `str` | — | Instructional text above the input |
| `label` | `str` | `""` | Placeholder text |
| `default` | `str` | `""` | Pre-filled value |
| `password` | `bool` | `False` | Mask the input |

---

## ConfirmModal

**File:** `ui/widgets/confirm_modal.py`

A confirmation dialog with scrollable body. Returns `True` when confirmed, `None` when cancelled.

```python
from ui.widgets.confirm_modal import ConfirmModal

modal = ConfirmModal(
    title="Run this command?",
    body="rm -rf /tmp/old_builds",
    confirm_label="Run",
)
confirmed = await app.push_screen_wait(modal)
# confirmed is True or None
```

| Parameter | Type | Default | Description |
|---|---|---|---|
| `title` | `str` | — | Heading text |
| `body` | `str` | — | Scrollable content |
| `confirm_label` | `str` | `"Confirm"` | Text for the confirm button |

---

## Pushing Modals from Different Contexts

| Context | Async? | Pattern |
|---|---|---|
| `@register_handler` (sync) | No | Wrap in `app.run_worker(async_fn())` |
| `@register_tool` (async) | Yes | `await app.push_screen_wait(modal)` directly |
| `@register_command` (async) | Yes | `await app.push_screen_wait(modal)` directly |

### Sync handler pattern

```python
@register_handler("my_skill.prompt")
def _on_prompt(data: dict, ctx: AppContext) -> None:
    app = ctx.app
    if app is None:
        return

    async def do_prompt() -> None:
        result = await app.push_screen_wait(InputModal("Enter value:"))
        if result is not None:
            ctx.config.set("my_skill.value", result)

    app.run_worker(do_prompt())
```