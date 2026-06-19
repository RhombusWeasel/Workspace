# Plan: Markdown Preview Toggle for File Editor

## Goal

When a `.md` file is opened in the `FileEditor`, the user can press a key to
toggle between **edit mode** (the existing `TextArea` with markdown syntax
highlighting) and **preview mode** (a read-only rendered `Markdown` widget).

## Motivation

Textual has no built-in "editable rendered Markdown" widget.  The `Markdown`
widget is read-only (renders headings, bold, tables, code blocks, etc.) and
`TextArea` with `language="markdown"` only provides syntax highlighting, not
rendered formatting.  A toggle gives the best of both worlds without consuming
extra screen real estate.

## Design

### New binding

Add `Binding("ctrl+e", "toggle_preview", "Preview", show=True, priority=True)` to
`FileEditor.BINDINGS`.

> **Note:** Originally planned as `Ctrl+P` but Textual's test pilot
> silently swallows `Ctrl+P` (mapped to raw `\x10`), so we use `Ctrl+E`
> instead.

### Mode state

Add `self._preview_mode: bool = False` to `FileEditor.__init__`.

### Widgets in compose

Currently `compose()` yields:
1. `TextArea` (the editor)
2. `SuggestionOverlay` (docked, for AI suggestions)

Add a third widget:
3. `Markdown(id="md-preview")` — hidden by default via `display: False`

### Toggle action

`action_toggle_preview()`:

- **Entering preview mode** (`_preview_mode` is `False`):
  1. Read current text from the `TextArea`.
  2. Update the `Markdown` widget's content (`markdown_doc.update(text)`).
  3. Hide the `TextArea` (`display = False`), show the `Markdown` widget
     (`display = True`).
  4. Clear any active AI suggestion (no suggestions in preview mode).
  5. Set `self._preview_mode = True`.

- **Leaving preview mode** (`_preview_mode` is `True`):
  1. Hide the `Markdown` widget (`display = False`), show the `TextArea`
     (`display = True`).
  2. Focus the `TextArea`.
  3. Set `self._preview_mode = False`.

### Applicability

The toggle should only work for markdown files.  For non-markdown files,
`action_toggle_preview()` is a no-op (or could show a brief notification).
We check `self._language == "markdown"`.

### CSS

Add a `FileEditor` CSS rule (in the app's stylesheet or inline `DEFAULT_CSS`)
to control layout.  The `Markdown` widget should fill the same area as the
`TextArea`:

```css
FileEditor Markdown {
    display: none;
    height: 1fr;
    overflow: auto;
    padding: 0 1;
}
```

The `display: none` default ensures the preview is hidden on mount; we toggle
it via `styles.display` at runtime.

### Session persistence

No changes needed.  `FileEditorState` only stores the filepath — preview mode
is a transient UI state, not something we need to persist across workspace
recomposition.  A restored tab always opens in edit mode.

### Suggestion overlay interaction

The `SuggestionOverlay` remains mounted in both modes.  When entering preview
mode we clear any active suggestion.  The overlay is `display: False` when no
suggestion is active so it won't interfere with the preview.

## Files to modify

1. **`ui/workspace/file_editor.py`**
   - Import `Markdown` from `textual.widgets`.
   - Add `ctrl+p` binding.
   - Add `self._preview_mode` to `__init__`.
   - Yield `Markdown` widget in `compose()`.
   - Add `action_toggle_preview()` method.
   - Add `DEFAULT_CSS` class variable for the Markdown preview layout.
   - Guard `action_request_ai_suggestion()` — no-op in preview mode.

2. **`.agents/design.md`** — update with the new feature.

3. **`.agents/tasks.md`** — add task entry.

## Tests

Create `tests/test_markdown_preview_toggle.py`:

1. **Test markdown file shows preview on toggle** — compose a `FileEditor`
   with a `.md` path, toggle, assert `Markdown` widget is visible and
   `TextArea` is hidden.

2. **Test toggle back to edit mode** — after toggling to preview, toggle
   again, assert `TextArea` is visible and `Markdown` is hidden, and
   `TextArea` has focus.

3. **Test non-markdown file is no-op** — compose with a `.py` path,
   toggle, assert nothing changes (`TextArea` still visible, `Markdown`
   still hidden).

4. **Test preview content matches editor text** — load text into editor,
   toggle to preview, assert `Markdown` widget's document contains the
   same text.

5. **Test suggestion cleared on entering preview** — set a suggestion,
   toggle to preview, assert suggestion is cleared.

6. **Test AI suggestion request is no-op in preview mode** — enter
   preview mode, call `action_request_ai_suggestion()`, assert no worker
   is started (or that it's a no-op).

7. **Test initial state is edit mode** — freshly composed `FileEditor`
   has `_preview_mode == False`, `TextArea` visible, `Markdown` hidden.

8. **Test save still works after preview round-trip** — toggle to
   preview and back, then save, assert content is correct.

## Out of scope

- Live-updating preview (updating rendered markdown on every keystroke).
  The preview is a snapshot taken at toggle time.
- Split view (editor + side-by-side preview).
- Markdown widget scroll position preservation between toggles.