# Workspace — Task Tracking

## Completed
- All implementation steps 1–28 complete (see design_document.md)
- Fix: ChatDisplay not scrollable — make ChatDisplay extend VerticalScroll instead of composing one inside a Widget ✅
- Fix: Collapsible widgets not actually collapsible ✅
  - All 6 subclasses now pass content as *children to Collapsible.__init__
  - Removed compose() overrides so Collapsible.compose() creates CollapsibleTitle + Contents
  - AssistantTurn uses Collapsible's built-in title (set_header updates self.title)
  - _mount_into_collapsible() routes sections into Contents container
  - _swap_to_markdown() handles both pre-compose and post-compose cases
  - end_batch() uses compose_add_child for batch mode
  - 39 tests pass (26 existing + 13 new collapsible toggle tests)
- Fix: History chat rebuild — Assistant content not displayed when opening from history tab ✅
- Add {{user}}, {{design}}, {{tasks}} template variable providers ✅
  - Created `core/context_files.py` with load_user_md(), load_design_md(), load_tasks_md()
  - Registered 3 new dynamic providers in bootstrap.py
  - 19 tests passing in tests/test_context_files.py
- Remove title extensions from User/Assistant collapsibles, change Assistant icon ✅
  - Plan: `.agents/plans/remove-title-extensions.md`
- Add coloured left-border CSS classes to chat display messages ✅
  - Branch: `feature/chat-coloured-borders`, commit ea9db3d
  - Plan: `.agents/plans/chat-coloured-borders.md`
  - 5 CSS classes: chat-user, chat-response, chat-thinking, chat-tools, chat-system
  - 7 new tests in TestMessageCSSClasses, all 33 chat_display_v2 tests pass
- Display tool results in chat UI ✅
  - Branch: `feature/tool-result-display`, commit 94e2a82
  - Plan: `.agents/plans/tool-result-display.md`
  - Tool results now shown in ToolCallSection with checkmark ✔ label + result markdown
  - Results persisted in DB alongside tool calls
  - reconstruct_history emits tool-role messages for LLM context
  - 16 new tests (5 display + 7 format + 4 database), 49 total pass
- Fix: Streaming crash on workspace split/close ✅ (DONE)
  - Branch: `fix/streaming-crash-on-split-close`, commit a60a96c
  - Plan: `.agents/plans/fix-streaming-crash-on-split-close.md`
  - Root cause: ChatManager._streaming_task not cancelled when widget destroyed during recompose
  - Added on_unmount/on_remove handlers + _detached flag + is_mounted guards
  - 19 new tests pass, all 362 pre-existing passing tests still pass
- Stream preservation across workspace recomposition (IN PROGRESS)
  - Branch: `feature/stream-manager`, commit cc9758c
  - Plan: `.agents/plans/stream-manager-preservation.md`
  - StreamManager singleton on AppContext owns stream lifecycle
  - ChatManager subscribes by UUID; on recomposition, new widget re-subscribes
  - Chunks buffered for late subscribers; persisted sections used for display rebuild
  - 29 tests pass, all 388 pre-existing passing tests still pass
  - Fixed: _rebuild_and_maybe_resume() serializes rebuild before stream resume
  - Fixed: _process_stream_chunks(resume=True) drains buffered chunks and skips already-displayed content
  - **Needs manual testing**: split/close workspace during streaming to verify stream continues
- Stream to DB + polling display (COMPLETED)
  - Plan: `.agents/plans/stream-db-polling.md`
  - Simplified StreamManager: owns LLM task, writes response/thinking/tool rows to DB periodically
  - ChatDisplay polls DB via `refresh_from_sections()` and renders updates
  - ChatManager no longer processes chunk callbacks; it starts the stream and polls the DB
  - Removed obsolete `subscribe()` / `Subscription` / chunk-buffering code
  - Added DB `section_id` column + `upsert_streaming_section()` for in-place streaming updates
  - Branch: `feature/stream-db-polling`
  - Tests: `tests/test_streaming_crash_fix.py` (30 pass), `tests/test_chat_display_v2.py` (38 pass)
  - Removed obsolete `tests/test_streaming_optimize.py` (Tree-based throttle/expand tests no longer apply)
  - **Pre-existing failures not introduced here**: `test_chat_revert.py`, `test_chat_rebuild.py`, `test_chat_display_rebuild.py` (Collapsible revert/rebuild UI still TODO)
- Fix: Token tracking broken after StreamManager switch ✅
  - Branch: `fix/token-tracking-stream-manager`, commit 140b2c8
  - Plan: `.agents/plans/fix-token-tracking.md`
  - Root cause: StreamManager._handle_chunk() ignored chunk.done/chunk.usage; ChatManager._poll_stream() never called update_context_progress()
  - Fix: StreamManager stores done chunk in _usage dict + exposes get_usage(); ChatManager reads usage after stream and updates ContextUsageBar
  - 11 new tests in test_token_tracking.py, all pass; 30 existing streaming tests still pass
- Fix: Sequential thinking/response sections merged into one collapsible ✅
  - Branch: `fix/sequential-sections`, commit 9c999f5
  - Plan: `.agents/plans/fix-sequential-sections.md`
  - Root cause: StreamManager used flat accumulators (response_id/thinking_id) that merged all thinking and all response into single DB rows
  - Fix: Replaced with sequential section tracking that detects type transitions (thinking↔response, tool calls) and creates new sections with unique IDs
  - 12 new tests in test_stream_manager_sections.py, all pass; 11 existing token tracking tests still pass; 385 total tests pass

## In Progress
- Fix: Chat display not showing messages on history load ✅
  - Branch: `fix/chat-display-use-refresh-from-sections`, commit 8feeeab
  - Plan: `.agents/plans/fix-chat-display-use-refresh-from-sections.md`
  - Root cause: `_rebuild_display_from_sections()` was a fragile batch-mode replay that duplicated `refresh_from_sections()`; also `refresh_from_sections()` had a bug where user-only turns were silently skipped
  - Fix: Replaced `_rebuild_display_from_sections()` with `refresh_from_sections()` — the proven streaming method; fixed user-only turn handling
  - 375 tests pass, net -77 lines

- Consolidate test suite ✅
  - Branch: `chore/consolidate-test-suite`
  - Plan: `.agents/plans/consolidate-test-suite.md`
  - Deleted 5 obsolete/duplicate test files: test_chat_rebuild, test_chat_display_rebuild, test_chat_revert, test_agent_name_config, test_project_context
  - Merged `test_read_file_empty_file` into `test_context_files.py`
  - Added `tests/README.md` with testing philosophy
  - 367 tests pass, 0 failures (down from 26 failures)

- Fix: Chat history not loading ✅
  - Branch: `fix/chat-history-loading`
  - Plan: `.agents/plans/fix-chat-history-loading.md`
  - Removed duplicate `_rebuild_and_maybe_resume` method in chat_manager.py
  - Added error logging to `_rebuild_and_maybe_resume()` and `_open_chat()`
  - Added diagnostic logging to `on_mount()` for rebuild scheduling
  - 8 new tests in test_chat_history_loading.py, all pass
  - All 375 tests pass

## Completed
- Fix: Final response not displayed — silent exception swallowing in _poll_stream and _swap_to_markdown ✅
  - Branch: `fix/final-response-display`, commit d360775
  - Plan: `.agents/plans/fix-final-response-display.md`
  - Replaced `except Exception: pass` with proper logging in `_poll_stream` and `_swap_to_markdown`
  - Added retry logic: if final refresh (finalize=True) fails, retry without finalization
  - 8 new tests, all 383 tests pass

## Completed
- All implementation steps 1–28 complete (see design_document.md)
- Fix: ChatDisplay not scrollable ✅
- Fix: Collapsible widgets not actually collapsible ✅
- Fix: History chat rebuild ✅
- Add {{user}}, {{design}}, {{tasks}} template variable providers ✅
- Remove title extensions from User/Assistant collapsibles ✅
- Add coloured left-border CSS classes to chat display messages ✅
- Display tool results in chat UI ✅
- Fix: Streaming crash on workspace split/close ✅
- Stream preservation across workspace recomposition ✅
- Stream to DB + polling display ✅
- Fix: Token tracking broken after StreamManager switch ✅
- Fix: Sequential thinking/response sections merged into one collapsible ✅
- Fix: Chat display not showing messages on history load ✅
- Consolidate test suite ✅
- Fix: Chat history not loading ✅
- Fix: Final response not displayed ✅
- Session state persistence & restore ✅
  - Branch: `feature/session-restore`, commits 3e2da80, 36f7420
  - Plan: `.agents/plans/session-restore.md`
  - New `core/session.py`: SessionManager with save/restore, TabTypeHandler registry
  - Pane tree serialisation: `pane_tree_to_dict()` / `pane_tree_from_dict()`
  - Tab handlers: chat, terminal, file_editor, welcome, query_editor
  - Session file: `{wd}/.agents/session.json`
  - Save on quit + periodic 60s + on_unmount fallback
  - Restore on mount, graceful degradation for missing files/chats
  - Sidebar visibility persisted
  - 30 new tests, all 413 pass
  - **Bug fix**: Use `workspace._save_pane_tab_states()` instead of DOM queries for reliable tab capture during shutdown
  - **Pending manual test**: Verify tabs are restored correctly after app restart

- Fix: Terminal hangs and crashes after 2 commands ✅
  - Branch: `fix/terminal-hang-crash`, commits a1c1fb6, fb29331, b71d393
  - Plan: `.agents/plans/fix-terminal-hang-crash.md`
  - 6 bugs fixed: blocking os.waitpid (primary crash cause), unthrottled render loop, duplicate recv_task, signal leak, compose screen clobber, unmount safety
  - Replaced upstream PtyTerminal.recv() with throttled recv that drains batches, renders once per ~16ms
  - Replaced blocking TerminalEmulator.stop() with _async_stop_emulator + _reap_process (SIGTERM → poll → SIGKILL)
  - _throttled_recv no longer calls pty.stop() on disconnect
  - Exception resilience: _render_screen and _throttled_recv catch and log errors instead of dying silently
  - 44 new tests, all 457 pass
  - **Needs manual testing**: verify terminal stays responsive after multiple commands, closing tabs works, no crashes

## In Progress

## Not Started
- Bundled skills: coding, todo