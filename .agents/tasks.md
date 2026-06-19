# Workspace — Task Tracker

## In-Progress Tasks

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