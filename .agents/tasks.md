# Workspace — Task Tracker

## In-Progress Tasks

### Fix Chat Display Long Session Disconnect
- **Plan:** `.agents/plans/fix-chat-display-long-session.md`
- **Branch:** `fix/chat-display-long-session`
- **Status:** Complete — fix applied, 9 new tests added (incl. regression test for end_batch mount bug), all 209 tests pass
- **Summary:** Fixed the chat display silently losing connection in long sessions. Root cause was the `_sync_conversation` polling loop catching all exceptions from `refresh_from_sections` at DEBUG level (effectively silent). Four fixes applied: (1) upgraded polling loop error logging from DEBUG to WARNING, (2) added per-section try/except isolation in `refresh_from_sections` so one failing section doesn't block all subsequent sections, (3) removed dict-clearing in `begin_assistant_turn` that caused earlier-turn section lookups to fail during DB-driven refresh, (4) made `_mount_into_collapsible`, `add_section`, `add_tool_call`, and `batch_finalize_turns` async with awaited mount calls to ensure widgets are fully mounted before subsequent operations. **Follow-up fix:** `end_batch` was using `compose_add_child` to mount Section widgets into AssistantTurn Collapsibles, but the Collapsibles were already composed (mounted via `self.mount()`), so `compose_add_child` only added to `_contents_list` without actually mounting into the DOM — causing empty assistant collapsibles when opening conversations from history. Fixed by using `contents.mount()` for already-composed Collapsibles, falling back to `compose_add_child` only for pre-composition.

### Markdown Preview Toggle for File Editor
- **Plan:** `.agents/plans/markdown-preview-toggle.md`
- **Branch:** `feature/markdown-preview-toggle`
- **Status:** Complete — implementation done, 8 tests added, all 151 tests pass
- **Summary:** Added `Ctrl+E` toggle in `FileEditor` to switch between edit mode (TextArea with syntax highlighting) and a read-only rendered `Markdown` preview for `.md` files. Used `Ctrl+E` instead of `Ctrl+P` because Textual's test pilot silently swallows `Ctrl+P`. Made `FileEditor` focusable so key bindings work when the TextArea is hidden in preview mode. Guards AI suggestion requests as no-ops in preview mode.

## Completed Tasks

### Fix Last Response Section Static→Markdown Swap
- **Plan:** `.agents/plans/fix-last-response-static-to-markdown.md`
- **Branch:** `fix/last-response-static-markdown` → merged to `main`
- **Status:** Complete — merged
- **Summary:** Fixed `batch_finalize_turns()` to do a live DOM swap (`widget.remove()` + `contents.mount(new_widget)`) for sections already composed in the DOM, instead of only updating `_contents_list` (which has no effect post-composition). Falls back to `_contents_list` update for pre-composition batch mode. 8 regression tests added, all 143 tests pass.

### Section Completion Flag in DB
- **Plan:** `.agents/plans/section-completion-flag.md`
- **Branch:** `feature/section-completion-flag` → merged to `main`
- **Status:** Complete — merged
- **Summary:** Added `status` column (`streaming`/`complete`) to messages table. StreamManager marks sections complete per-section on transitions and tool results. ChatDisplay uses status to render completed sections as Markdown and streaming as Static. 135 tests pass, 11 new tests for status column.

## Completed Tasks

### Fix History Chat Blank Tab
- **Plan:** `.agents/plans/fix-history-chat-blank.md`
- **Branch:** `fix-cancel-streaming`
- **Status:** Complete
- **Summary:** Opening a historic conversation showed a blank tab because `_rebuild_and_resume` worker was likely cancelled by Textual's `cancel_node` during tab creation. Changed `on_mount()` to use `call_after_refresh` so the rebuild runs after the widget is fully laid out. 417 tests pass.

### Chat Display as Pure DB Read Model
- **Plan:** `.agents/plans/chat-display-db-read-model.md`
- **Branch:** `fix-chat-db-read-model`
- **Status:** Complete
- **Summary:** Make ChatDisplay a pure DB read model — remove direct display manipulation from `_handle_submit()`, fix `refresh_from_sections()` calling `finalize_turn()` on every streaming poll cycle, and remove dead `_sections` code from history panel. DB is the single source of truth; display only reads from DB. Simplified history panel to use standard chat content factory. 417 tests pass.

### Simplify Chat Display Reconstruction
- **Plan:** `.agents/plans/simplify-chat-display.md`
- **Branch:** `simplify-chat-display`
- **Status:** Complete (superseded by chat-display-db-read-model)
- **Summary:** Replace 4 overlapping reconstruction paths with single `_sync_conversation()` method. Remove `_sections` in-memory mirror (DB is source of truth). Delete dead `stream_section.py`. ~400 line reduction.

### Fix Chat Display Reconstruction
- **Plan:** `.agents/plans/fix-chat-reconstruction.md`
- **Branch:** `fix-chat-reconstruction`
- **Status:** Complete
- **Summary:** `refresh_from_sections(f finalize=True)` now uses batch mode (`begin_batch` → `batch_finalize_turns` → `end_batch`) for the entire rebuild. This fixes the bug where earlier turns' sections were removed as "empty" because `begin_assistant_turn()` cleared per-turn tracking dicts. All 49 chat display tests pass, including 3 new multi-turn regression tests.

### Chat Display Analysis
- **Status:** Complete
- **Summary:** Full end-to-end analysis of the chat display system. No code changes.

### Vault Input Validation
- **Plan:** `.agents/plans/vault-input-validation.md`
- **Branch:** `vault-input-validation`
- **Status:** Complete
- **Summary:** Added `validate_name()` and `validate_master_password()` to `core/vault.py`, applied at all entry points, added `_register_credential_raw` for internal `vault:*` passkeys, added ValueError handling in `vault_panel.py`, 30 tests passing.