"""File editor — editable file viewer with syntax highlighting and inline AI suggestions.

Uses Textual's :class:`~textual.widgets.TextArea` to provide a rich
editing experience with syntax highlighting, line numbers, and undo/redo.

Inline AI suggestions are displayed as ghost text at the cursor position.
Suggestions are triggered automatically after a configurable pause
(default 400 ms) or manually with ``Ctrl+A``.  Press ``Ctrl+F`` to
accept the current suggestion.  Multi-line suggestions also appear in a
docked :class:`~ui.workspace.suggestion_overlay.SuggestionOverlay` at
the bottom of the editor.  Press ``Escape`` to dismiss either.

Because :class:`~textual.widgets.TextArea` with ``tab_behavior=\"indent\"``
intercepts Escape to move focus (calling ``focus_next()`` and
``event.stop()``), the priority binding alone is not guaranteed to
reach :meth:`action_dismiss_ai_suggestion`.  A ``on_blur`` handler
acts as a safety-net: when focus leaves the editor while a suggestion
is active, the overlay is cleaned up regardless of how the focus
change occurred.

Opened inside workspace tabs when a file is selected from the file browser.
Reads the file from disk on mount.  Supports saving changes back to disk
via :meth:`save_file`.

Tab state is managed by :class:`FileEditorState`, which holds only the
file path (content lives on disk).  When the workspace is reorganised,
the fresh widget re-reads from disk — no ``flush_state()`` needed.
"""

from __future__ import annotations

import os

from textual.app import ComposeResult
from textual.widgets import TextArea
from textual.widget import Widget
from textual.binding import Binding
from textual import events

from ui.workspace.suggestion_overlay import SuggestionOverlay
from ui.workspace.tabs import TabState
from utils.dom_id import path_to_id


# ---------------------------------------------------------------------------
# Language mapping — file extensions → Textual TextArea language names
# ---------------------------------------------------------------------------

_EXTENSION_TO_LANGUAGE: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "javascript",
    ".jsx": "javascript",
    ".tsx": "javascript",
    ".rs": "rust",
    ".go": "go",
    ".java": "java",
    ".html": "html",
    ".htm": "html",
    ".css": "css",
    ".scss": "css",
    ".less": "css",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".xml": "xml",
    ".sql": "sql",
    ".sh": "bash",
    ".bash": "bash",
    ".zsh": "bash",
    ".md": "markdown",
    ".ps1": "pwsh",
    ".psm1": "pwsh",
    ".psd1": "pwsh",
}


def _language_for_file(filepath: str) -> str | None:
    """Return the Textual TextArea language name for *filepath*, or None."""
    _, ext = os.path.splitext(filepath)
    return _EXTENSION_TO_LANGUAGE.get(ext.lower())


def _register_custom_languages(text_area: TextArea) -> None:
    """Register tree-sitter languages that aren't built into Textual.

    Textual ships highlight queries for a set of built-in languages, but
    additional languages (like PowerShell) need to be registered manually
    with their tree-sitter ``Language`` object and highlight query.
    """
    if "pwsh" not in text_area._languages:
        try:
            from textual._tree_sitter import get_language
            import tree_sitter_pwsh

            lang = get_language("pwsh")
            if lang is not None:
                highlights_path = os.path.join(
                    os.path.dirname(tree_sitter_pwsh.__file__),
                    "queries",
                    "highlights.scm",
                )
                highlight_query = ""
                if os.path.exists(highlights_path):
                    with open(highlights_path) as f:
                        highlight_query = f.read()
                text_area.register_language("pwsh", lang, highlight_query)
        except ImportError:
            # tree-sitter-pwsh not installed — PowerShell files will
            # open as plain text.
            pass


# ---------------------------------------------------------------------------
# FileEditorState — persistent state for file editor tabs
# ---------------------------------------------------------------------------


class FileEditorState(TabState):
    """State for a file editor tab that survives workspace recomposition.

    Content lives on disk, so this only needs the file path.  The widget
    re-reads from disk on mount — no ``flush_state()`` needed.
    """

    def __init__(self, filepath: str):
        self.filepath = filepath


# ---------------------------------------------------------------------------
# FileEditor
# ---------------------------------------------------------------------------


class FileEditor(Widget):
    """Editable file viewer with syntax highlighting and inline AI suggestions.

    Parameters
    ----------
    state:
        The :class:`FileEditorState` for this tab.  Provides the file
        path and handles any per-tab state.
    """

    BINDINGS = [
        Binding("ctrl+s", "save", "Save", show=True),
        Binding(
            "ctrl+a",
            "request_ai_suggestion",
            "AI Suggest",
            show=True,
            priority=True,
        ),
        Binding(
            "ctrl+f",
            "accept_ai_suggestion",
            "AI Fill",
            show=True,
            priority=True,
        ),
        Binding(
            "escape",
            "dismiss_ai_suggestion",
            "Dismiss suggestion",
            show=False,
            priority=True,
        ),
    ]

    def __init__(self, state: FileEditorState):
        super().__init__(id=path_to_id("fv", state.filepath))
        self.state = state
        self._content = ""
        self._language = _language_for_file(state.filepath)
        # Inline suggestion state
        self._debounce_id: int = 0
        """Monotonically increasing counter — stale timer callbacks check
        this and bail out if a newer request has superseded them."""
        self._suggestion_suppressed: bool = False
        """Set to ``True`` after accepting a suggestion so the subsequent
        :class:`~textual.widgets.TextArea.Changed` event from the insert
        doesn't immediately re-trigger a request."""
        self._full_suggestion: str | None = None
        """The complete multi-line suggestion text, or ``None`` when no
        suggestion is active.  For single-line suggestions this is the
        same as the inline ghost text.  For multi-line suggestions, the
        first line is shown inline and the full text is shown in the
        :class:`~ui.workspace.suggestion_overlay.SuggestionOverlay`."""

    @property
    def filepath(self) -> str:
        return self.state.filepath

    @property
    def editor(self) -> TextArea:
        """Return the inner :class:`TextArea` widget."""
        return self.query_one(TextArea)

    @property
    def overlay(self) -> SuggestionOverlay:
        """Return the :class:`SuggestionOverlay` widget."""
        return self.query_one(SuggestionOverlay)

    def compose(self) -> ComposeResult:
        text_area = TextArea.code_editor(
            self._content,
            language=None,  # set after registering custom languages
            theme="monokai",
            soft_wrap=False,
            show_line_numbers=True,
            read_only=False,
            tab_behavior="indent",
        )
        _register_custom_languages(text_area)
        if self._language:
            text_area.language = self._language
        yield text_area
        yield SuggestionOverlay()

    def on_mount(self) -> None:
        self._load_file()

    def _load_file(self) -> None:
        """Read the file from disk and update the editor."""
        try:
            with open(self.state.filepath, "r", encoding="utf-8", errors="replace") as f:
                self._content = f.read()
        except (OSError, UnicodeDecodeError):
            self._content = f"(Could not read file: {self.state.filepath})"

        # Update the TextArea if it's already mounted
        try:
            text_area = self.query_one(TextArea)
            text_area.load_text(self._content)
            # Apply language — None means plain text (no syntax highlighting)
            text_area.language = self._language
        except Exception:
            pass

    def refresh_file(self) -> None:
        """Re-read the file from disk and update the editor."""
        self._load_file()

    def save_file(self) -> bool:
        """Write the current editor content back to disk.

        Returns
        -------
        bool
            True if the save succeeded, False otherwise.
        """
        try:
            text_area = self.query_one(TextArea)
            content = text_area.text
            with open(self.state.filepath, "w", encoding="utf-8") as f:
                f.write(content)
            # Sync cached content so is_modified resets after save
            self._content = content
            return True
        except (OSError, Exception):
            return False

    def action_save(self) -> None:
        """Handle the Ctrl+S keybinding — save the file and notify the user."""
        if self.save_file():
            self.app.notify(f"Saved {os.path.basename(self.state.filepath)}")
        else:
            self.app.notify(
                f"Failed to save {os.path.basename(self.state.filepath)}",
                severity="error",
            )

    @property
    def is_modified(self) -> bool:
        """Whether the editor content differs from the on-disk file."""
        try:
            text_area = self.query_one(TextArea)
            return text_area.text != self._content
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Inline AI suggestions
    # ------------------------------------------------------------------

    def _get_suggest_config(self) -> dict:
        """Read inline suggestion config from the app context.

        Returns a dict of config values with sensible defaults if
        the context or config are unavailable.
        """
        try:
            ctx = self.app.context
            if ctx and ctx.config:
                return {
                    "enabled": ctx.config.get("inline_suggest.enabled", True),
                    "model": ctx.config.get("inline_suggest.model", ""),
                    "delay_ms": ctx.config.get("inline_suggest.delay_ms", 400),
                    "lines_above": ctx.config.get(
                        "inline_suggest.context_lines_above", 40
                    ),
                    "lines_below": ctx.config.get(
                        "inline_suggest.context_lines_below", 20
                    ),
                    "max_lines": ctx.config.get(
                        "inline_suggest.max_suggestion_lines", 8
                    ),
                }
        except Exception:
            pass
        return {
            "enabled": True,
            "model": "",
            "delay_ms": 400,
            "lines_above": 40,
            "lines_below": 20,
            "max_lines": 8,
        }

    def _make_provider_and_model(self):
        """Return the shared provider and model from the app context.

        Uses the provider registry to get the default provider instance.
        Falls back to ``session.model`` if ``inline_suggest.model`` is
        not set.

        Returns ``(provider, model)`` or ``(None, "")`` on failure.
        """
        try:
            ctx = self.app.context
            # Use provider registry (preferred) or backward-compat property
            if ctx.providers is not None:
                provider = ctx.providers.get_default()
            else:
                provider = ctx.provider
            model = ctx.config.get("inline_suggest.model", "")
            if not model:
                model = ctx.config.get("session.model", "")
            return provider, model
        except Exception:
            return None, ""

    def _clear_suggestion(self) -> None:
        """Clear both the inline ghost text and the overlay."""
        self._full_suggestion = None
        try:
            self.editor.suggestion = ""
        except Exception:
            pass
        try:
            self.overlay.hide_suggestion()
        except Exception:
            pass

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        """Handle text changes — debounce and schedule inline suggestion.

        Fires after every edit.  Increments the debounce counter so
        that any previously-scheduled timer callback becomes stale.
        Then schedules a new timer that will fire if no further edits
        happen before the configured delay.
        """
        cfg = self._get_suggest_config()
        if not cfg["enabled"]:
            return

        # Invalidate any pending debounce timer
        self._debounce_id += 1

        # Clear any existing suggestion (context has changed)
        self._clear_suggestion()

        # If the change came from accepting a suggestion, suppress
        # the auto-trigger for this one change.
        if self._suggestion_suppressed:
            self._suggestion_suppressed = False
            return

        # Schedule a new suggestion request after the configured delay.
        # The closure captures ``current_id`` — when the timer fires it
        # checks that no newer edit has happened in the meantime.
        current_id = self._debounce_id

        def _fire():
            if self._debounce_id == current_id:
                self._request_suggestion()

        delay = cfg["delay_ms"] / 1000.0
        self.set_timer(delay, _fire)

    def on_text_area_selection_changed(
        self, event: TextArea.SelectionChanged
    ) -> None:
        """Clear the suggestion when the cursor moves without typing.

        Without this, the ghost text would appear at the wrong position
        after cursor-only movements (arrow keys, mouse clicks).
        """
        self._clear_suggestion()

    def on_blur(self, event: events.Blur) -> None:
        """When a child loses focus and no descendant retains it, clear the overlay.

        This is a safety-net for the case where TextArea's default
        key handling absorbs the Escape keypress (when
        ``tab_behavior=\"indent\"``, TextArea calls ``focus_next()``
        and ``event.stop()``).  In that scenario the priority binding
        for Escape never fires, but focus still leaves the editor —
        so we use the blur event to clean up the docked overlay.

        We only clear when *no* descendant of FileEditor retains focus,
        so clicking into the SuggestionOverlay (if it were focusable)
        would not prematurely dismiss it.
        """
        if self._has_active_suggestion() and not self.has_focus_within:
            self._clear_suggestion()

    def action_dismiss_ai_suggestion(self) -> None:
        """Handle Escape: dismiss AI suggestion, or blur the editor.

        Uses a ``priority=True`` binding so this fires *before* the
        inner :class:`~textual.widgets.TextArea` consumes the key.  When
        ``tab_behavior=\"indent\"``, TextArea intercepts Escape to call
        ``focus_next()`` — we replicate that fallthrough here so the
        user doesn't lose the normal Escape behaviour when no suggestion
        is active.
        """
        if self._has_active_suggestion():
            self._clear_suggestion()
        else:
            # No suggestion — replicate TextArea's default Escape
            # behaviour (move focus to the next widget).
            self.screen.focus_next()

    def _has_active_suggestion(self) -> bool:
        """Whether an AI suggestion is currently showing (inline or overlay)."""
        if self._full_suggestion is not None:
            return True
        try:
            return bool(self.editor.suggestion)
        except Exception:
            return False

    def _request_suggestion(self) -> None:
        """Start a background worker to fetch an inline suggestion.

        Uses ``exclusive=True`` with the name ``"inline_suggest"`` so
        that a new request automatically cancels any old one that is
        still in flight.
        """
        self.run_worker(
            self._fetch_suggestion(),
            name="inline_suggest",
            exclusive=True,
        )

    async def _fetch_suggestion(self) -> None:
        """Fetch an inline suggestion from the LLM and display it.

        Gathers context, calls the LLM, and sets the TextArea's
        ``suggestion`` reactive if a valid completion is returned.
        For multi-line completions, also shows the
        :class:`SuggestionOverlay`.

        Verifies the cursor position before setting the suggestion to
        avoid showing stale completions after the user has moved.
        Redaction is handled automatically by the provider.
        """
        provider, model = self._make_provider_and_model()
        if provider is None or not model:
            return

        cfg = self._get_suggest_config()

        try:
            text_area = self.editor
            cursor_row, cursor_col = text_area.cursor_location

            from core.inline_suggest import get_inline_suggestion

            suggestion = await get_inline_suggestion(
                provider=provider,
                model=model,
                file_path=self.filepath,
                file_content=text_area.text,
                cursor_row=cursor_row,
                cursor_col=cursor_col,
                context_lines_above=cfg["lines_above"],
                context_lines_below=cfg["lines_below"],
                max_suggestion_lines=cfg["max_lines"],
                ctx=self.app.context,
            )

            if suggestion:
                # Verify the cursor hasn't moved since we made the request
                current_row, current_col = text_area.cursor_location
                if current_row == cursor_row and current_col == cursor_col:
                    self._display_suggestion(suggestion)
        except Exception:
            # Inline suggestions are non-critical UI hints — log but
            # don't disrupt the user with error notifications.
            from textual import log
            log.warning("Inline suggestion failed", exc_info=True)

    def _display_suggestion(self, suggestion: str) -> None:
        """Show a suggestion — inline ghost text, and overlay if multi-line."""
        self._full_suggestion = suggestion
        lines = suggestion.split("\n")

        try:
            if len(lines) == 1:
                # Single-line: show inline only
                self.editor.suggestion = suggestion
                self.overlay.hide_suggestion()
            else:
                # Multi-line: first line inline, full suggestion in overlay
                self.editor.suggestion = lines[0]
                self.overlay.show_suggestion(suggestion)
        except Exception:
            pass

    def action_request_ai_suggestion(self) -> None:
        """Manually trigger an AI suggestion (``Ctrl+A``).

        Cancels any pending debounce timer by incrementing the debounce
        counter and requests a suggestion immediately.
        """
        cfg = self._get_suggest_config()
        if not cfg["enabled"]:
            return

        # Invalidate any pending auto-debounce timer
        self._debounce_id += 1

        # Clear existing suggestion and request immediately
        self._clear_suggestion()
        self._request_suggestion()

    def action_accept_ai_suggestion(self) -> None:
        """Accept the current AI suggestion (``Ctrl+F``).

        Inserts the full suggestion text (which may span multiple lines)
        at the cursor and clears the ghost text and overlay.  Sets
        ``_suggestion_suppressed`` so the subsequent
        :class:`~textual.widgets.TextArea.Changed` event from the insert
        doesn't immediately re-trigger a suggestion.
        """
        try:
            text_area = self.editor
            if self._full_suggestion:
                text_area.suggestion = ""
                self._suggestion_suppressed = True
                text_area.insert(self._full_suggestion)
                self._full_suggestion = None
                self.overlay.hide_suggestion()
            elif text_area.suggestion:
                # Fallback: accept whatever inline ghost text is there
                suggestion = text_area.suggestion
                text_area.suggestion = ""
                self._suggestion_suppressed = True
                text_area.insert(suggestion)
                self._full_suggestion = None
        except Exception:
            pass