# Fix: Last Response Section Stays Static After Stream Ends

## Problem

When a streaming turn ends, the last response section often remains as a `Static` widget instead of being swapped to `Markdown`. This means the final assistant response is rendered as plain text without rich formatting (no code blocks, bold, lists, etc.).

## Root Cause

The swap from `Static` → `Markdown` is supposed to happen in `refresh_from_sections(finalize=True)`, which is called after the streaming loop exits. There are three code paths that can trigger the swap, and **two of them are broken for the last response section**:

### Path 1: `_maybe_swap_to_markdown()` (content unchanged + status changed)
**Works correctly.** When `prev["content"] == content` and `is_complete` transitions from `False` → `True`, `_swap_to_markdown()` is called which does a proper async DOM swap (`remove()` + `mount()`).

### Path 2: Content changed + falls through to `update_section()` (BROKEN)
When the last chunk of content arrived between the final streaming poll and the finalize refresh, `prev["content"] != content`. The code falls through to the `update_section()` path, which updates the `Static` widget's text but **never swaps to Markdown**. Then `batch_finalize_turns()` runs, which swaps `_content_widget` and `_contents_list` — but these are **internal references only**. The widgets are already composed and in the DOM from streaming, so updating `_contents_list` has no effect. The old `Static` widget remains visible.

### Path 3: `batch_finalize_turns()` (designed for initial load, BROKEN for post-stream)
`batch_finalize_turns()` swaps `Static` → `Markdown` by replacing entries in `_contents_list` and `_content_widget`. This works during **initial load** (batch rebuild) because the `Collapsible` hasn't composed yet — when it composes during `end_batch()`, it uses `_contents_list` to yield children.

But after streaming, the `Section` widgets are **already in the DOM**. The `Collapsible` has already composed. Updating `_contents_list` is pointless — the old `Static` widget is still rendered. The method needs to do an actual DOM swap (`remove()` + `mount()`) for already-composed sections.

## Fix

### Change 1: Make `batch_finalize_turns()` do DOM swaps for already-mounted sections

When a section's `Collapsible.Contents` container already exists in the DOM (meaning it's composed and mounted), `batch_finalize_turns()` should do a live DOM swap instead of just updating `_contents_list`. This mirrors what `_swap_to_markdown()` does for the async path.

**Logic:**
- For each section being finalized, check if the `Collapsible.Contents` exists in the DOM
- If yes: remove old `Static`, mount new `Markdown` into `Contents` (same as `_swap_to_markdown`)
- If no: update `_contents_list` (current behavior, for pre-composition batch)

### Change 2: Ensure content-changed sections also get the swap in `refresh_from_sections`

Even with Change 1, there's a subtlety: when content changes between the last streaming poll and the finalize refresh, the code path is:

```python
# Line 850-856 (response section, content changed)
section_id = self._refresh_section_map.get(key)
if section_id is None:
    use_markdown = is_complete and not finalize
    section_id = self.add_section("response", as_markdown=use_markdown)
    self._refresh_section_map[key] = section_id
await self.update_section(section_id, content)
```

Since `section_id` is already in `_refresh_section_map` (the section was created during streaming), `add_section` is NOT called. The `use_markdown` variable is never evaluated. The section stays as `Static`.

Then `batch_finalize_turns()` runs and (with Change 1) does the DOM swap. This should work.

But there's also the case where `section_id` IS in `_refresh_section_map` but `is_complete` is True and `finalize` is True. Currently `use_markdown = True and not True = False`, which would create as `Static` anyway. With Change 1, `batch_finalize_turns` handles the swap afterward.

### Change 3: Handle the case where `_maybe_swap_to_markdown` runs during batch mode

Currently, `_maybe_swap_to_markdown()` is called from `refresh_from_sections` during batch mode. It does an async DOM swap via `_swap_to_markdown()`. This is fine for the "content unchanged" case, but it could race with `batch_finalize_turns()` if the same section is processed twice.

To prevent double-swapping, `batch_finalize_turns()` should skip sections where the widget is already `Markdown` (which it already does via `isinstance(widget, Static)` check). So if `_maybe_swap_to_markdown` already swapped a section, `batch_finalize_turns` will correctly skip it.

## Implementation

### File: `skills/chat/chat_display.py`

#### 1. Fix `batch_finalize_turns()` to do DOM swaps for already-mounted sections

Replace the current `_contents_list`-only update with a dual approach:
- Try to find `Collapsible.Contents` in the DOM
- If found: remove old widget, mount new widget (async-safe for batch context)
- If not found: update `_contents_list` (pre-composition path)

Since `batch_finalize_turns()` is synchronous and called before `end_batch()`, and the widgets may or may not be in the DOM, we need to handle both cases.

**Current code** (lines ~1046-1076):
```python
for section_id in list(self._section_map):
    section = self._section_map.get(section_id)
    if section is None:
        continue
    section_type = self._section_types.get(section_id, "")
    if section_type in _KEEP_STATIC_SECTIONS:
        continue
    widget = self._section_widgets.get(section_id)
    if not isinstance(widget, Static):
        continue
    text = self._section_texts.get(section_id, "")
    if not text:
        continue
    new_widget = Markdown(text, id=f"{widget.id}-rendered")
    section._content_widget = new_widget
    try:
        idx = section._contents_list.index(widget)
        section._contents_list[idx] = new_widget
    except ValueError:
        section._contents_list.append(new_widget)
    self._section_widgets[section_id] = new_widget
```

**New code:**
```python
for section_id in list(self._section_map):
    section = self._section_map.get(section_id)
    if section is None:
        continue
    section_type = self._section_types.get(section_id, "")
    if section_type in _KEEP_STATIC_SECTIONS:
        continue
    widget = self._section_widgets.get(section_id)
    if not isinstance(widget, Static):
        continue
    text = self._section_texts.get(section_id, "")
    if not text:
        continue
    new_widget = Markdown(text, id=f"{widget.id}-rendered")

    # Try live DOM swap if section is already composed.
    swapped = False
    try:
        contents = section.query_one(Collapsible.Contents)
        # Section is in the DOM — swap the widget live.
        widget.remove()
        contents.mount(new_widget)
        swapped = True
    except Exception:
        # Section not yet composed — update _contents_list.
        pass

    if not swapped:
        try:
            idx = section._contents_list.index(widget)
            section._contents_list[idx] = new_widget
        except ValueError:
            section._contents_list.append(new_widget)
        # Also try to remove the old widget if it's somehow in the DOM.
        try:
            widget.remove()
        except Exception:
            pass

    section._content_widget = new_widget
    self._section_widgets[section_id] = new_widget
```

## Tests

Add tests to `tests/test_final_response_display.py`:

1. **Test that a response section with changed content gets swapped to Markdown during finalize** — Simulate streaming (add section as Static, update content), then call `refresh_from_sections(finalize=True)` with updated content and `status='complete'`. Verify the widget is now `Markdown`.

2. **Test that `batch_finalize_turns` does a DOM swap for already-mounted sections** — Create a section, mount it into the DOM, then call `batch_finalize_turns`. Verify the old Static is removed and the new Markdown is mounted.

3. **Test that thinking sections stay Static during finalize** — Same as test 1, but for thinking sections. Verify they remain Static.

4. **Test that `_maybe_swap_to_markdown` correctly handles the streaming→complete transition** — Verify that when a section's status changes from streaming to complete and content is unchanged, the swap happens.

## Risk Assessment

- **Low risk**: The change is localized to `batch_finalize_turns()`. The pre-composition path (updating `_contents_list`) is preserved as the fallback.
- **The `contents.mount(new_widget)` call is synchronous** — Textual's `mount()` in some contexts returns a coroutine, but when called on an already-composed container inside a synchronous method, it should work. If not, we may need to defer the mount.
- **Potential issue**: `widget.remove()` might fail if the widget isn't in the DOM (e.g., during batch rebuild of initial load). The `try/except` handles this gracefully.