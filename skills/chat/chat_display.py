"""Chat display — a VerticalScroll + Collapsible conversation view with streaming Markdown sections.

Each assistant turn is a **Vertical** container holding collapsible sections.
Sections are added on demand via :meth:`add_section` as their content arrives
during streaming, producing a natural sequential layout (e.g. Thinking →
Tools → Thinking → Response).

**Default expand/collapse** — Response and system sections are expanded
automatically when created.  Thinking sections and tool call branches
are collapsed by default, controlled by the ``open_thinking`` and
``open_tools`` constructor parameters (both default to ``False``).

**System prompt display** — When ``show_system_prompt`` is True, the
LLM system prompt is displayed as a collapsible section at the start
of each conversation.

**Streaming optimisation** — During streaming, ALL section types use
plain :class:`~textual.widgets.Static` text instead of
:class:`~textual.widgets.Markdown`.  This eliminates expensive markdown
parsing on every chunk — Textual's ``Markdown.update()`` re-parses the
entire accumulated text and recreates all child widgets on every call,
which is O(n²) over the length of the response.  ``Static.update()``
is a lightweight string replacement + refresh by contrast.

When the turn is finalised (``finalize_turn()``), response and tools
sections are swapped from ``Static`` to ``Markdown`` for rich rendering.
Thinking sections remain as ``Static`` permanently — they don't benefit
from markdown rendering and the swap cost isn't justified.

The display auto-scrolls to the bottom when new content is added or
updated, so the view follows along with streaming output.

**Architecture** — This replaces the previous Tree-based implementation
with VerticalScroll + Collapsible.  Each message is a self-contained
widget mounted directly into the scroll container.  This makes all
operations O(1): adding a message, adding a section, expanding/
collapsing — no tree walks, no rebuilds, no prefix computation.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.widget import Widget
from textual.widgets import Collapsible, Markdown, Static

from skills.chat.tool_format import (
    format_tool_call_branch_label,
    format_tool_call_branch_label_expanded,
    format_tool_call_detail,
)


# ---------------------------------------------------------------------------
# Section type constants
# ---------------------------------------------------------------------------

_VALID_SECTIONS = frozenset({"thinking", "response", "system"})
_SECTION_ICONS: dict[str, str] = {
    "thinking": "  \U000f0df6 Thinking",
    "response": "  \U000f0b79 Response",
    "system": "  \U000f0e38 System",
}

# Section types that stay as Static even after finalize (never swapped to Markdown).
_KEEP_STATIC_SECTIONS = frozenset({"thinking"})


# ---------------------------------------------------------------------------
# Chat section widgets
# ---------------------------------------------------------------------------


class UserMessage(Collapsible):
    """A collapsible section for a user message.

    Shows a truncated preview in the collapsed title and the full
    Markdown content when expanded.
    """

    def __init__(
        self,
        text: str,
        message_id: str,
        **kwargs,
    ):
        self.message_id = message_id
        self.full_text = text
        preview = _truncate(text, 60)
        super().__init__(
            title=f"\uf007  [cyan]User:[/cyan] {preview}",
            id=f"msg-{message_id}",
            **kwargs,
        )
        # User messages start expanded.
        self.collapsed = False

    def compose(self) -> ComposeResult:
        yield Markdown(self.full_text, id=f"md-msg-{self.message_id}")


class AssistantTurn(Vertical):
    """A vertical container for all sections of one assistant turn.

    Contains a header label and one or more Section widgets.  Provides
    a :meth:`set_header` method to update the collapsed-state preview.
    """

    DEFAULT_CSS = """
    AssistantTurn {
        padding: 0;
        margin: 0;
    }
    """

    def __init__(self, turn_id: str, **kwargs):
        self.turn_id = turn_id
        super().__init__(id=f"asst-{turn_id}", **kwargs)
        self._header: Static | None = None

    def compose(self) -> ComposeResult:
        self._header = Static(
            "\uf4ad  [green]Assistant[/green]",
            classes="assistant-header",
            id=f"header-{self.turn_id}",
        )
        yield self._header

    def set_header(self, text: str) -> None:
        """Update the header label text."""
        if self._header is not None:
            self._header.update(text)


class Section(Collapsible):
    """A collapsible section within an assistant turn.

    Contains a content widget (Static during streaming, Markdown after
    finalize for response/tools sections).  The ``section_id`` attribute
    links back to the ChatDisplay's tracking dicts.
    """

    DEFAULT_CSS = """
    Section {
        padding: 0;
        margin: 0;
    }
    """

    def __init__(
        self,
        section_id: str,
        title: str,
        content: Widget,
        *,
        start_collapsed: bool = False,
        **kwargs,
    ):
        self.section_id = section_id
        self._content_widget = content
        super().__init__(
            title=title,
            collapsed=start_collapsed,
            id=f"sec-{section_id}",
            **kwargs,
        )

    def compose(self) -> ComposeResult:
        yield self._content_widget


class ToolCallSection(Collapsible):
    """A collapsible section for a tool call within an assistant turn.

    Shows the tool name in the title and Markdown detail content.
    """

    DEFAULT_CSS = """
    ToolCallSection {
        padding: 0;
        margin: 0;
    }
    """

    def __init__(
        self,
        section_id: str,
        title: str,
        title_expanded: str,
        detail: str,
        *,
        start_collapsed: bool = False,
        **kwargs,
    ):
        self.section_id = section_id
        self._title_collapsed = title
        self._title_expanded = title_expanded
        self._detail_text = detail
        super().__init__(
            title=title,
            collapsed=start_collapsed,
            id=f"tc-{section_id}",
            **kwargs,
        )

    def compose(self) -> ComposeResult:
        yield Markdown(self._detail_text, id=f"md-tc-{self.section_id}")


class SystemMessage(Collapsible):
    """A collapsible section for a system message."""

    def __init__(
        self,
        text: str,
        message_id: str,
        **kwargs,
    ):
        self.message_id = message_id
        self.full_text = text
        super().__init__(
            title="  \U000f0e38 [dim]System[/dim]",
            id=f"msg-{message_id}",
            **kwargs,
        )
        self.collapsed = False

    def compose(self) -> ComposeResult:
        yield Markdown(self.full_text, id=f"md-msg-{self.message_id}")


class SystemPromptSection(Collapsible):
    """A collapsible section for the LLM system prompt."""

    def __init__(
        self,
        text: str,
        message_id: str,
        **kwargs,
    ):
        self.message_id = message_id
        self.full_text = text
        super().__init__(
            title="  \U000f0e38 System Prompt",
            id=f"msg-{message_id}",
            **kwargs,
        )
        # System prompt starts collapsed.
        self.collapsed = True

    def compose(self) -> ComposeResult:
        yield Markdown(self.full_text, id=f"md-msg-{self.message_id}")


# ---------------------------------------------------------------------------
# ChatDisplay
# ---------------------------------------------------------------------------


class ChatDisplay(Widget):
    """Streaming conversation display using VerticalScroll + Collapsible.

    Provides a high-level API for building and updating a conversation:

    * ``add_user_message(text)`` → UserMessage Collapsible
    * ``begin_assistant_turn()`` → AssistantTurn Vertical container
    * ``add_section(section_type)`` → Section Collapsible, returns ID
    * ``update_section(section_id, text)`` → streaming update
    * ``add_tool_call(name, arguments)`` → ToolCallSection Collapsible
    * ``finalize_turn()`` → removes empty sections, swaps Static→Markdown

    During streaming, ALL sections are rendered as plain ``Static`` text
    (no markdown parsing) to reduce re-rendering cost.  On
    ``finalize_turn()``, response and tools sections are swapped to
    ``Markdown`` for rich formatting.  Thinking sections stay as
    ``Static`` permanently.

    When ``show_system_prompt`` is True, the LLM system prompt is displayed
    as a collapsible system section at the start of each conversation.
    """

    DEFAULT_CSS = """
    ChatDisplay {
        height: 1fr;
    }

    ChatDisplay > VerticalScroll {
        height: 1fr;
    }

    ChatDisplay .assistant-header {
        color: $text;
        padding: 0 0 0 1;
    }

    ChatDisplay .streaming-content {
        width: 1fr;
    }

    ChatDisplay .thinking-content {
        color: $text-muted;
        text-style: italic;
        padding: 0;
        width: 1fr;
    }
    """

    def __init__(
        self,
        *,
        open_thinking: bool = False,
        open_tools: bool = False,
        show_system_prompt: bool = False,
    ):
        super().__init__()
        self._turn_count = 0
        self._section_count = 0
        self._tool_call_count = 0
        self._active_asst_id: str | None = None

        # Config-driven defaults for whether thinking and tool-call
        # sections are expanded or collapsed when first created.
        self._open_thinking = open_thinking
        self._open_tools = open_tools

        # Whether to display the LLM system prompt at the start of each
        # conversation.
        self._show_system_prompt = show_system_prompt

        # Populated by add_section, cleared by finalize_turn.
        # Maps section_id → content widget (Markdown or Static).
        self._section_widgets: dict[str, Widget] = {}
        # Maps section_id → accumulated text (for emptiness checks).
        self._section_texts: dict[str, str] = {}
        # Maps section_id → section_type (for finalize swap decisions).
        self._section_types: dict[str, str] = {}

        # Maps section_id → Section Collapsible widget (for finding in DOM).
        self._section_map: dict[str, Section] = {}
        # Maps turn_id → AssistantTurn widget (for finding in DOM).
        self._turn_map: dict[str, AssistantTurn] = {}

        # Batch mode — when True, mount() calls are deferred to end_batch().
        self._batch_mode: bool = False
        self._batch_widgets: list[Widget] = []

        # Coalesced scroll — during streaming, _schedule_scroll() is called
        # on every update_section().  Without coalescing, each call creates
        # a new timer.  With the _scroll_pending flag, only one timer exists
        # at a time.
        self._scroll_pending: bool = False

    # ------------------------------------------------------------------
    # Composition
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield VerticalScroll(id="chat-scroll")

    # ------------------------------------------------------------------
    # Scroll container access
    # ------------------------------------------------------------------

    def _scroll(self) -> VerticalScroll:
        """Get the VerticalScroll container."""
        return self.query_one(VerticalScroll)

    # ------------------------------------------------------------------
    # Scrolling
    # ------------------------------------------------------------------

    def _scroll_to_bottom(self) -> None:
        """Scroll the chat display to show the latest content."""
        try:
            scroll = self._scroll()
            scroll.scroll_end(animate=False)
        except Exception:
            pass

    def _schedule_scroll(self) -> None:
        """Schedule a deferred scroll-to-bottom after layout recalculates.

        During batch mode, scroll is suppressed — it will be triggered
        once by :meth:`end_batch`.
        """
        if self._batch_mode:
            return
        if self._scroll_pending:
            return
        self._scroll_pending = True
        self.set_timer(1 / 60, self._do_deferred_scroll)

    def _do_deferred_scroll(self) -> None:
        """Fire the deferred scroll and reset the pending flag."""
        self._scroll_pending = False
        self._scroll_to_bottom()

    # ------------------------------------------------------------------
    # User messages
    # ------------------------------------------------------------------

    def add_user_message(self, text: str) -> str:
        """Add a user message as a Collapsible with Markdown content.

        Returns the message ID.
        """
        self._turn_count += 1
        msg_id = f"user-{self._turn_count}"

        user_msg = UserMessage(text, msg_id)

        if self._batch_mode:
            self._batch_widgets.append(user_msg)
        else:
            self._scroll().mount(user_msg)

        self._schedule_scroll()
        return msg_id

    # ------------------------------------------------------------------
    # Assistant turn lifecycle
    # ------------------------------------------------------------------

    def begin_assistant_turn(self) -> str:
        """Create an assistant turn container with a header label.

        Returns the turn ID.
        """
        self._turn_count += 1
        asst_id = f"asst-{self._turn_count}"

        turn = AssistantTurn(asst_id)

        if self._batch_mode:
            self._batch_widgets.append(turn)
        else:
            self._scroll().mount(turn)

        self._active_asst_id = asst_id
        self._turn_map[asst_id] = turn

        # In batch mode, accumulate section tracking across turns.
        if not self._batch_mode:
            self._section_widgets = {}
            self._section_texts = {}
            self._section_types = {}

        self._schedule_scroll()
        return asst_id

    def add_section(self, section_type: str) -> str:
        """Add a new section to the current assistant turn.

        *section_type* must be one of ``'thinking'``, ``'tools'``, or
        ``'response'``.  Returns the section ID for use with
        :meth:`update_section`.
        """
        if section_type not in _VALID_SECTIONS:
            raise ValueError(
                f"Unknown section type {section_type!r}; "
                f"must be one of {sorted(_VALID_SECTIONS)}"
            )
        if self._active_asst_id is None:
            raise RuntimeError(
                "No active assistant turn — call begin_assistant_turn first"
            )

        self._section_count += 1
        section_id = f"{section_type}-sec{self._section_count}"

        # All sections use Static during streaming.
        css_class = "thinking-content" if section_type == "thinking" else "streaming-content"
        content_widget: Widget = Static(
            "", markup=False,
            id=f"md-{section_id}", classes=css_class,
        )

        self._section_widgets[section_id] = content_widget
        self._section_texts[section_id] = ""
        self._section_types[section_id] = section_type

        # Determine collapsed state.
        if section_type == "thinking" and not self._open_thinking:
            start_collapsed = True
        else:
            start_collapsed = False

        title = _SECTION_ICONS.get(section_type, section_type)
        section = Section(
            section_id,
            title=title,
            content=content_widget,
            start_collapsed=start_collapsed,
        )
        self._section_map[section_id] = section

        # Mount inside the current AssistantTurn.
        turn = self._turn_map.get(self._active_asst_id)
        if turn is not None:
            if self._batch_mode:
                self._batch_widgets.append(section)
            else:
                turn.mount(section)

        self._schedule_scroll()
        return section_id

    async def update_section(self, section_id: str, text: str) -> None:
        """Update the content widget for the section identified by *section_id*.

        During streaming all sections are ``Static``, so this is a
        lightweight synchronous update — no markdown parsing.
        """
        widget = self._section_widgets.get(section_id)
        if widget is None:
            return

        self._section_texts[section_id] = text

        if isinstance(widget, Static):
            widget.update(text)
        elif isinstance(widget, Markdown):
            await widget.update(text)

    async def finalize_turn(self) -> None:
        """Remove empty sections, swap Static→Markdown for rich sections, clear state.

        After removing empty section children, response and tools sections
        are swapped from plain ``Static`` to ``Markdown`` for rich formatting.
        Thinking sections remain as ``Static``.
        """
        asst_id = self._active_asst_id
        if asst_id is None:
            return

        turn = self._turn_map.get(asst_id)
        if turn is not None:
            # Remove empty sections.
            sections_to_remove = []
            for section_id in list(self._section_map):
                section = self._section_map.get(section_id)
                if section is None:
                    continue
                if self._is_empty_section(section_id):
                    sections_to_remove.append(section)

            for section in sections_to_remove:
                section.remove()
                self._section_map.pop(section.section_id, None)

            # Swap response/tools sections from Static → Markdown.
            await self._swap_sections_to_markdown()

            # Update header to show a preview of the response.
            preview = self._turn_preview()
            if preview:
                turn.set_header(f"\uf4ad  [green]Assistant:[/green] {preview}")

        self._active_asst_id = None
        self._section_widgets = {}
        self._section_texts = {}
        self._section_types = {}

        # Scroll to bottom after the Static→Markdown swap.
        self._schedule_scroll()

    # ------------------------------------------------------------------
    # System messages (command feedback)
    # ------------------------------------------------------------------

    def add_system_message(self, text: str) -> str:
        """Add a system message as a Collapsible with Markdown content.

        Returns the message ID.
        """
        self._turn_count += 1
        msg_id = f"sys-{self._turn_count}"

        sys_msg = SystemMessage(text, msg_id)

        if self._batch_mode:
            self._batch_widgets.append(sys_msg)
        else:
            self._scroll().mount(sys_msg)

        self._schedule_scroll()
        return msg_id

    # ------------------------------------------------------------------
    # System prompt display
    # ------------------------------------------------------------------

    def add_system_prompt(self, text: str) -> str:
        """Add the LLM system prompt as a collapsible section.

        Only displayed when the ``show_system_prompt`` config option is True.
        Starts collapsed.

        Returns the message ID.
        """
        self._turn_count += 1
        msg_id = f"prompt-{self._turn_count}"

        prompt_section = SystemPromptSection(text, msg_id)

        if self._batch_mode:
            self._batch_widgets.append(prompt_section)
        else:
            self._scroll().mount(prompt_section)

        self._schedule_scroll()
        return msg_id

    # ------------------------------------------------------------------
    # Reset
    # ------------------------------------------------------------------

    def clear(self) -> None:
        """Remove all messages from the display and reset internal state."""
        scroll = self._scroll()
        # Remove all children from the scroll container.
        for child in list(scroll.children):
            child.remove()

        self._turn_count = 0
        self._section_count = 0
        self._tool_call_count = 0
        self._active_asst_id = None
        self._section_widgets = {}
        self._section_texts = {}
        self._section_types = {}
        self._section_map = {}
        self._turn_map = {}
        self._batch_mode = False
        self._batch_widgets = []
        self._scroll_pending = False

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _is_empty_section(self, section_id: str) -> bool:
        """Return True if the section has no meaningful content."""
        text = self._section_texts.get(section_id, "")
        return not text

    def _turn_preview(self) -> str:
        """Build a short preview string from the current turn's content.

        Looks for a response section first, then thinking, then any
        non-empty section.  Returns up to 60 characters of the content.
        """
        for section_type in ("response", "thinking"):
            for section_id, st in self._section_types.items():
                if st == section_type:
                    text = self._section_texts.get(section_id, "")
                    if text:
                        return _truncate(text, 60)
        # Fall back to any non-empty section.
        for section_id, text in self._section_texts.items():
            if text:
                return _truncate(text, 60)
        return ""

    def _find_section(self, section_id: str) -> Section | None:
        """Find a Section widget by its section_id."""
        return self._section_map.get(section_id)

    def _find_assistant_turn(self, turn_id: str) -> AssistantTurn | None:
        """Find an AssistantTurn widget by its turn_id."""
        return self._turn_map.get(turn_id)

    # ------------------------------------------------------------------
    # Batch mode
    # ------------------------------------------------------------------

    def begin_batch(self) -> None:
        """Enter batch mode — defer mount() calls until end_batch().

        During batch mode, adding messages and sections does not trigger
        individual mount() calls.  Call :meth:`end_batch` to mount all
        deferred widgets at once.
        """
        self._batch_mode = True
        self._batch_widgets = []

    def end_batch(self) -> None:
        """Exit batch mode — mount all deferred widgets and scroll.

        Restores normal operation: subsequent add/update calls will
        trigger individual mount() calls as before.

        Also clears section tracking dicts that were needed during
        the batch rebuild but are no longer needed after finalization.
        """
        self._batch_mode = False

        # Mount all deferred widgets in a single batch.
        scroll = self._scroll()
        if self._batch_widgets:
            for widget in self._batch_widgets:
                scroll.mount(widget)
        self._batch_widgets = []

        # Apply expand/collapse config.
        self._apply_expand_config()

        # Clear section tracking — after batch finalize, these are
        # no longer needed (the widgets are already in the DOM).
        self._section_widgets = {}
        self._section_texts = {}
        self._section_types = {}

        self._scroll_to_bottom()

    def _apply_expand_config(self) -> None:
        """Apply open_thinking and open_tools config after batch rebuild.

        After mounting, all sections default to their Collapsible
        collapsed/expanded state.  We need to explicitly collapse
        thinking and tool sections if config says they should start
        collapsed.
        """
        if not self._open_thinking:
            for section_id, section in self._section_map.items():
                section_type = section.section_id.split("-")[0] if "-" in section.section_id else ""
                # Find section type from the ID prefix.
                # IDs are like "thinking-sec1", "response-sec2", "tools-sec3".
                pass
        # Actually, in the new architecture, the collapsed state is set
        # at construction time via start_collapsed parameter.  In batch
        # mode, those sections are created with the correct collapsed state.
        # So _apply_expand_config is only needed for batch_finalize_turns
        # where we may need to override.
        pass

    def batch_finalize_turns(self) -> None:
        """Finalize all completed assistant turns in batch mode.

        Removes empty sections, swaps Static → Markdown in the DOM,
        and prepares headers.

        Must be called while in batch mode (between :meth:`begin_batch`
        and :meth:`end_batch`).
        """
        # Find all assistant turns and finalize them.
        for section_id in list(self._section_map):
            section = self._section_map.get(section_id)
            if section is None:
                continue
            section_type = self._section_types.get(section_id, "")
            if section_type in _KEEP_STATIC_SECTIONS:
                continue

            # Swap Static → Markdown for response/tools sections.
            widget = self._section_widgets.get(section_id)
            if not isinstance(widget, Static):
                continue
            text = self._section_texts.get(section_id, "")
            if not text:
                continue

            # Replace the content widget in the Section.
            new_widget = Markdown(text, id=f"{widget.id}-rendered")
            section._content_widget = new_widget

            # Update tracking.
            self._section_widgets[section_id] = new_widget

        # Remove empty sections from batch widgets list.
        self._batch_widgets = [
            w for w in self._batch_widgets
            if not (isinstance(w, Section) and self._is_empty_section(w.section_id))
        ]

        # Mark active turn as done.
        self._active_asst_id = None

    # ------------------------------------------------------------------
    # Tool call entries
    # ------------------------------------------------------------------

    def add_tool_call(
        self,
        name: str,
        arguments: dict,
    ) -> str:
        """Add a tool call section under the current assistant turn.

        Returns the tool call section ID.
        """
        if self._active_asst_id is None:
            raise RuntimeError(
                "No active assistant turn — call begin_assistant_turn first"
            )

        self._tool_call_count += 1
        tc_id = f"tc-{self._tool_call_count}"

        # Collapsed: name + short args.  Expanded: just the name.
        label = format_tool_call_branch_label(name, arguments)
        label_expanded = format_tool_call_branch_label_expanded(name)

        # Detail content — Markdown with formatted arguments.
        detail = format_tool_call_detail(name, arguments)

        start_collapsed = not self._open_tools

        tool_section = ToolCallSection(
            tc_id,
            title=label,
            title_expanded=label_expanded,
            detail=detail,
            start_collapsed=start_collapsed,
        )

        # Mount inside the current AssistantTurn.
        turn = self._turn_map.get(self._active_asst_id)
        if turn is not None:
            if self._batch_mode:
                self._batch_widgets.append(tool_section)
            else:
                turn.mount(tool_section)

        self._schedule_scroll()
        return tc_id

    # ------------------------------------------------------------------
    # Static → Markdown swap (called from finalize_turn)
    # ------------------------------------------------------------------

    async def _swap_sections_to_markdown(self) -> None:
        """Swap completed response/tools sections from Static → Markdown.

        Iterates over all section widgets from the current turn.  For
        response and tools sections that are still ``Static``, creates a
        ``Markdown`` widget with the accumulated text and swaps it into
        the Section in-place.

        Thinking sections are left as ``Static``.
        """
        for section_id in list(self._section_widgets):
            section_type = self._section_types.get(section_id, "")
            if section_type in _KEEP_STATIC_SECTIONS:
                continue
            widget = self._section_widgets.get(section_id)
            if not isinstance(widget, Static):
                continue
            text = self._section_texts.get(section_id, "")
            if not text:
                continue
            await self._swap_to_markdown(section_id)

    async def _swap_to_markdown(self, section_id: str) -> None:
        """Replace a section's Static content widget with a Markdown widget.

        Updates the Section's content widget reference and swaps the
        widget in the DOM.
        """
        old_widget = self._section_widgets.get(section_id)
        if old_widget is None or not isinstance(old_widget, Static):
            return

        text = self._section_texts.get(section_id, "")
        if not text:
            return

        # Create new Markdown widget.
        new_widget = Markdown(text, id=f"{old_widget.id}-rendered")

        # Find the Section Collapsible and swap the content.
        section = self._section_map.get(section_id)
        if section is not None:
            # Remove old widget, mount new one inside the Section.
            try:
                old_widget.remove()
                await section.mount(new_widget)
            except Exception:
                pass  # Best-effort — non-critical visual improvement

            # Update the section's content widget reference.
            section._content_widget = new_widget

        # Update the widget mapping.
        self._section_widgets[section_id] = new_widget


def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."