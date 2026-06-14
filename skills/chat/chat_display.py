"""Chat display — a Tree-backed conversation view with streaming Markdown sections.

Each assistant turn is a **branch** node with dynamically-created section
branches.  Sections are added on demand via :meth:`add_section` as their
content arrives during streaming, producing a natural sequential layout
(e.g. Thinking → Tools → Thinking → Response).

**Default expand/collapse** — Response and system sections are expanded
automatically when created.  Thinking sections and tool call branches
are collapsed by default, controlled by the ``open_thinking`` and
``open_tools`` constructor parameters (both default to ``False``).  The
corresponding config keys are ``session.open_thinking`` and
``session.open_tools``.

**System prompt display** — When ``show_system_prompt`` is True, the
LLM system prompt is displayed as a collapsible branch at the start
of each conversation.  The corresponding config key is
``session.show_system_prompt``.

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
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Markdown, Static

from ui.tree.tree import Tree
from ui.tree.tree_row import TreeNode


# ---------------------------------------------------------------------------
# ChatDisplay
# ---------------------------------------------------------------------------

_VALID_SECTIONS = frozenset({"thinking", "response", "system"})
_SECTION_ICONS: dict[str, str] = {
    "thinking": "  \U000f0df6 Thinking",
    "response": "  \U000f0b79 Response",
    "system": "  \U000f0e38 System",
}

# Section types that stay as Static even after finalize (never swapped to Markdown).
# Thinking sections are plain text with no markdown benefit — the swap cost
# isn't justified.
_KEEP_STATIC_SECTIONS = frozenset({"thinking"})


class ChatDisplay(Widget):
    """Streaming conversation display backed by a collapsible Tree.

    Provides a high-level API for building and updating a conversation:

    * ``add_user_message(text)`` → branch node for user text (with Markdown leaf).
    * ``begin_assistant_turn()`` → empty assistant branch node.
    * ``add_section(section_type)`` → new section branch, returns ID.
    * ``update_section(section_id, text)`` → streaming update.
    * ``add_tool_call(name, arguments)`` → tool call branch with detail leaf.
    * ``finalize_turn()`` → removes any empty sections, clears state.

    During streaming, ALL sections are rendered as plain ``Static`` text
    (no markdown parsing) to reduce re-rendering cost.  On
    ``finalize_turn()``, response and tools sections are swapped to
    ``Markdown`` for rich formatting.  Thinking sections stay as
    ``Static`` permanently.

    When ``show_system_prompt`` is True, the LLM system prompt is displayed
    as a collapsible system section at the start of each conversation.
    """

    def __init__(
        self,
        *,
        open_thinking: bool = False,
        open_tools: bool = False,
        show_system_prompt: bool = False,
    ):
        super().__init__()
        self._root = TreeNode("chat-display-root", "Conversation")
        self._turn_count = 0
        self._section_count = 0
        self._tool_call_count = 0
        self._active_asst_id: str | None = None

        # Config-driven defaults for whether thinking and tool-call
        # branches are expanded or collapsed when first created.
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

        # Batch mode — when True, _rebuild() and _schedule_scroll() are
        # suppressed.  Call end_batch() to trigger a single rebuild +
        # scroll.  Used by ChatManager._rebuild_display_from_sections()
        # to avoid O(N²) rebuilds during conversation restore.
        self._batch_mode: bool = False

        # Coalesced scroll — during streaming, _schedule_scroll() is called
        # on every update_section().  Without coalescing, each call creates
        # a new timer.  With the _scroll_pending flag, only one timer exists
        # at a time — new calls while a timer is pending are no-ops.
        self._scroll_pending: bool = False

        # Throttled rebuild — during streaming, structural additions
        # (add_section, add_tool_call, begin_assistant_turn) each call
        # _rebuild().  With the _rebuild_pending flag, rapid calls are
        # coalesced into a single rebuild per frame.  The first call fires
        # immediately; subsequent calls within the same frame are skipped.
        # The flag is cleared after the rebuild completes.
        self._rebuild_pending: bool = False

        # Node lookup map — provides O(1) lookups for _find_node() instead
        # of recursive tree walks.  Maintained in sync with the tree data
        # model by _register_node() and _unregister_node().
        self._node_map: dict[str, TreeNode] = {}
        self._register_node(self._root)

    # ------------------------------------------------------------------
    # Composition
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Tree(self._root)

    # ------------------------------------------------------------------
    # Scrolling
    # ------------------------------------------------------------------

    def _scroll_to_bottom(self) -> None:
        """Scroll the chat tree to show the latest content.

        Best-effort — does not raise if the tree is not yet mounted.
        Called after adding content or updating sections so that the
        view follows the streaming output.
        """
        try:
            tree = self.query_one(Tree)
            tree.scroll_end(animate=False)
        except Exception:
            pass

    def _schedule_scroll(self) -> None:
        """Schedule a deferred scroll-to-bottom after layout recalculates.

        Content updates (adding nodes, updating sections) change the
        tree's virtual size, but the layout pass happens asynchronously.
        Calling ``scroll_end()`` immediately would use the old virtual
        size, so we defer by ~1 frame to let the layout catch up.

        During batch mode, scroll is suppressed — it will be triggered
        once by :meth:`end_batch`.

        Uses coalescing — only one scroll timer exists at a time.  If a
        scroll is already pending, this call is a no-op.  This avoids
        creating ~20 redundant timers per second during fast streaming.
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
        """Add a user message as a branch node with a Markdown leaf.

        Creates an expandable **User** branch whose child is a Markdown
        widget rendering the full message.  The branch auto-expands so
        the user can see what they just typed.

        When expanded the label shows ``\uf007  User``; when collapsed
        it shows a truncated preview like ``\uf007  User: Hello there...``.

        Returns the branch node ID.
        """
        self._turn_count += 1
        node_id = f"msg-{self._turn_count}"

        # Markdown leaf for the full user text.
        md = Markdown(text, id=f"md-{node_id}")
        leaf = TreeNode(f"{node_id}-leaf", "", content=md)

        # Branch — dual labels so collapsed state shows a preview.
        preview = _truncate(text, 60)
        branch = TreeNode(
            node_id,
            f"\uf007  [cyan]User:[/cyan] {preview}",
            label_expanded="\uf007  [cyan]User[/cyan]",
            data={"role": "user"},
            children=[leaf],
        )
        self._root.children.append(branch)
        self._register_node(branch)
        self._rebuild()

        # Expand the new user branch by default.
        tree = self.query_one(Tree)
        tree.expand_node(node_id)

        self._schedule_scroll()

        return node_id

    # ------------------------------------------------------------------
    # Assistant turn lifecycle
    # ------------------------------------------------------------------

    def begin_assistant_turn(self) -> str:
        """Create an assistant branch node with **no** section children.

        Sections are added on demand via :meth:`add_section` as their
        content arrives during streaming.  Returns the assistant branch
        node ID.

        The assistant branch is collapsible — the collapsed label shows
        a short identifier, and the expanded label shows just
        "Assistant".  This lets users collapse a whole response to
        save vertical space while reviewing earlier messages.
        """
        self._turn_count += 1
        asst_id = f"msg-{self._turn_count}"

        asst_node = TreeNode(
            asst_id,
            "\uf4ad  [green]Assistant[/green]",
            label_expanded="\uf4ad  [green]Assistant[/green]",
            data={"role": "assistant", "type": "branch"},
        )
        self._root.children.append(asst_node)
        self._register_node(asst_node)

        self._active_asst_id = asst_id
        # In batch mode, accumulate section tracking across turns
        # so that batch_finalize_turns can process all turns.
        if not self._batch_mode:
            self._section_widgets = {}
            self._section_texts = {}
            self._section_types = {}

        self._rebuild()

        # Expand the assistant branch.
        tree = self.query_one(Tree)
        tree.expand_node(asst_id)

        self._schedule_scroll()

        return asst_id

    def add_section(self, section_type: str) -> str:
        """Add a new section branch to the current assistant turn.

        *section_type* must be one of ``'thinking'``, ``'tools'``, or
        ``'response'``.  Returns the section ID for use with
        :meth:`update_section`.

        All sections use plain :class:`~textual.widgets.Static` during
        streaming to avoid the O(n²) cost of repeated
        :class:`~textual.widgets.Markdown` re-parses.  Response and tools
        sections are swapped to ``Markdown`` on ``finalize_turn()``.
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

        # All sections use Static during streaming — lightweight text updates
        # without the O(n²) cost of Markdown re-parsing on every chunk.
        css_class = "thinking-content" if section_type == "thinking" else "streaming-content"
        widget: Widget = Static(
            "", markup=False,
            id=f"md-{section_id}", classes=css_class,
        )

        self._section_widgets[section_id] = widget
        self._section_texts[section_id] = ""
        self._section_types[section_id] = section_type

        leaf = TreeNode(
            f"{section_id}-leaf", "",
            content=widget,
        )
        branch = TreeNode(
            section_id,
            _SECTION_ICONS.get(section_type, section_type),
            data={"section": section_type},
            children=[leaf],
        )

        # Append to the current assistant node.
        asst_node = self._find_node(self._active_asst_id)
        if asst_node is not None:
            asst_node.children.append(branch)
            self._register_node(branch)

        self._rebuild()

        # Expand the new section — unless config says it should start collapsed.
        # Thinking sections respect session.open_thinking; response and system
        # sections always expand.
        tree = self.query_one(Tree)
        if section_type == "thinking" and not self._open_thinking:
            tree.collapse_node(section_id)
        else:
            tree.expand_node(section_id)
        if not tree.is_user_collapsed(self._active_asst_id):
            tree.expand_node(self._active_asst_id)

        self._schedule_scroll()

        return section_id

    async def update_section(self, section_id: str, text: str) -> None:
        """Update the content widget for the section identified by *section_id*.

        During streaming all sections are ``Static``, so this is a
        lightweight synchronous update — no markdown parsing.

        The section must have been created by a prior :meth:`add_section`
        call during the current assistant turn.

        Note: This method does NOT trigger a scroll.  Scrolling is handled
        at structural boundaries (section creation, tool calls, turn start)
        and at stream completion (``chunk.done``), not on every content
        update.  This avoids ~20 redundant scroll events per second during
        streaming.
        """
        widget = self._section_widgets.get(section_id)
        if widget is None:
            return  # Unknown section — no-op.

        self._section_texts[section_id] = text

        if isinstance(widget, Static):
            # Plain text update — fast, no markdown parsing.
            widget.update(text)
        elif isinstance(widget, Markdown):
            # Markdown update (only after finalize swap) — async re-render.
            await widget.update(text)

    async def finalize_turn(self) -> None:
        """Remove empty sections, swap Static→Markdown for rich sections, clear state.

        After removing empty section children, response and tools sections
        are swapped from plain ``Static`` to ``Markdown`` for rich formatting.
        Thinking sections remain as ``Static`` (they don't benefit from
        markdown rendering).

        Finally, updates the assistant branch's collapsed label to show a
        short preview of the response content, making it easy to identify
        when collapsed.
        """
        asst_id = self._active_asst_id
        if asst_id is None:
            return

        node = self._find_node(asst_id)
        if node is not None:
            keep = [
                c for c in node.children
                if not self._is_empty_section(c)
            ]
            if len(keep) != len(node.children):
                # Unregister removed nodes from the lookup map.
                removed = [c for c in node.children if c not in keep]
                for rm in removed:
                    self._unregister_node(rm)
                node.children = keep
                self._immediate_rebuild()

            # Swap response/tools sections from Static → Markdown.
            await self._swap_sections_to_markdown()

            # Update collapsed label to show a preview of the response.
            # Compute preview BEFORE clearing _section_texts.
            preview = self._turn_preview(node)
            if preview:
                node.label = f"\uf4ad  [green]Assistant:[/green] {preview}"
                # Refresh the label in the tree.
                tree = self.query_one(Tree)
                tree.update_node_label(asst_id, node.label)

        self._active_asst_id = None
        self._section_widgets = {}
        self._section_texts = {}
        self._section_types = {}

    # ------------------------------------------------------------------
    # System messages (command feedback)
    # ------------------------------------------------------------------

    def add_system_message(self, text: str) -> str:
        """Add a system message as a standalone branch with a Markdown leaf.

        System messages are used for command feedback (e.g. "Chat cleared.").
        They appear as a single branch with a Markdown child, similar to
        user messages but styled differently.

        Returns the branch node ID.
        """
        self._turn_count += 1
        node_id = f"msg-{self._turn_count}"

        md = Markdown(text, id=f"md-{node_id}")
        leaf = TreeNode(f"{node_id}-leaf", "", content=md)

        branch = TreeNode(
            node_id,
            "  \U000f0e38 [dim]System[/dim]",
            data={"role": "system"},
            children=[leaf],
        )
        self._root.children.append(branch)
        self._register_node(branch)
        self._rebuild()

        tree = self.query_one(Tree)
        tree.expand_node(node_id)

        self._schedule_scroll()

        return node_id

    # ------------------------------------------------------------------
    # System prompt display
    # ------------------------------------------------------------------

    def add_system_prompt(self, text: str) -> str:
        """Add the LLM system prompt as a collapsible branch with a Markdown leaf.

        Only displayed when the ``show_system_prompt`` config option is True.
        The branch starts collapsed so it doesn't dominate the conversation
        view.  The caller (ChatManager) checks the config before calling.

        Returns the branch node ID.
        """
        self._turn_count += 1
        node_id = f"msg-{self._turn_count}"

        md = Markdown(text, id=f"md-{node_id}")
        leaf = TreeNode(f"{node_id}-leaf", "", content=md)

        branch = TreeNode(
            node_id,
            "  \U000f0e38 System Prompt",
            label_expanded="  \U000f0e38 System Prompt",
            data={"role": "system_prompt"},
            children=[leaf],
        )
        self._root.children.append(branch)
        self._register_node(branch)
        self._rebuild()

        tree = self.query_one(Tree)
        # Always collapse system prompt branches — the user can expand
        # them if they want to inspect the prompt.
        tree.collapse_node(node_id)

        self._schedule_scroll()

        return node_id

    # ------------------------------------------------------------------
    # Reset
    # ------------------------------------------------------------------

    def clear(self) -> None:
        """Remove all messages from the display and reset internal state.

        Does not affect the database — only clears the visual tree.
        """
        self._root.children.clear()
        self._turn_count = 0
        self._section_count = 0
        self._tool_call_count = 0
        self._active_asst_id = None
        self._section_widgets = {}
        self._section_texts = {}
        self._section_types = {}
        # Reset the node lookup map — only the root remains.
        self._node_map.clear()
        self._register_node(self._root)
        self._batch_mode = False
        self._rebuild_pending = False
        self._scroll_pending = False
        self._immediate_rebuild()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _is_empty_section(self, branch: TreeNode) -> bool:
        """Return True if the section branch has no meaningful content.

        A section branch is empty when its content leaf text is blank.
        Tool call branches are not section branches — they sit as
        direct children of the assistant node and should never be
        treated as empty sections.

        Checks ``_section_texts`` which tracks text for all sections
        in the current turn (and across turns during batch mode).
        """
        # Tool call branches are never "empty sections" — they have
        # their own content (Markdown detail leaf) and are not tracked
        # in _section_texts.
        if branch.data and branch.data.get("tool_call"):
            return False
        if not branch.children:
            return True
        return not self._section_texts.get(branch.id)

    def _turn_preview(self, asst_node: TreeNode) -> str:
        """Build a short preview string from the assistant turn's content.

        Looks for a response section first, then thinking, then any
        non-empty section.  Returns up to 60 characters of the content.
        """
        # Try response sections first, then thinking, then any.
        for section_type in ("response", "thinking"):
            for child in asst_node.children:
                if child.data and child.data.get("section") == section_type:
                    text = self._section_texts.get(child.id, "")
                    if text:
                        return _truncate(text, 60)
        # Fall back to any non-empty section.
        for child in asst_node.children:
            text = self._section_texts.get(child.id, "")
            if text:
                return _truncate(text, 60)
        return ""

    # ------------------------------------------------------------------
    # Node lookup map
    # ------------------------------------------------------------------

    def _register_node(self, node: TreeNode) -> None:
        """Register a node and all its children in the lookup map.

        Also registers in the Tree's _node_map so that expand_node()
        can find the node before the deferred rebuild fires.
        """
        self._node_map[node.id] = node
        try:
            tree = self.query_one(Tree)
            tree._node_map[node.id] = node
        except Exception:
            pass  # Tree not mounted yet — will be synced on rebuild
        for child in node.children:
            self._register_node(child)

    def _unregister_node(self, node: TreeNode) -> None:
        """Remove a node and all its children from the lookup map.

        Also removes from the Tree's _node_map.
        """
        self._node_map.pop(node.id, None)
        try:
            tree = self.query_one(Tree)
            tree._node_map.pop(node.id, None)
        except Exception:
            pass
        for child in node.children:
            self._unregister_node(child)

    def _find_node(self, node_id: str) -> TreeNode | None:
        """Find a node by ID using the O(1) lookup map.

        Falls back to recursive search if the node is not in the map
        (e.g. during initial construction before registration).
        """
        node = self._node_map.get(node_id)
        if node is not None:
            return node
        # Fallback — should not normally be needed.
        result = _find_node_recursive(self._root, node_id)
        if result is not None:
            self._node_map[node_id] = result
        return result

    # ------------------------------------------------------------------
    # Batch mode
    # ------------------------------------------------------------------

    def begin_batch(self) -> None:
        """Enter batch mode — suppress _rebuild() and _schedule_scroll().

        During batch mode, adding nodes and sections does not trigger
        individual tree rebuilds or scroll events.  Call :meth:`end_batch`
        to exit batch mode and perform a single rebuild + scroll.

        This is used by :meth:`ChatManager._rebuild_display_from_sections`
        to avoid O(N²) rebuild cost when replaying a full conversation.
        """
        self._batch_mode = True

    def end_batch(self) -> None:
        """Exit batch mode — perform a single rebuild and scroll.

        Restores normal operation: subsequent add/update calls will
        trigger individual rebuilds and scrolls as before.

        Also clears section tracking dicts (``_section_widgets``,
        ``_section_texts``, ``_section_types``) that were needed during
        the batch rebuild but are no longer needed after finalization.
        """
        self._batch_mode = False
        self._rebuild_pending = False
        self._scroll_pending = False
        self._section_widgets = {}
        self._section_texts = {}
        self._section_types = {}
        # Immediate rebuild — not throttled, since this is the final
        # rebuild that renders the entire conversation.
        self._immediate_rebuild()
        self._scroll_to_bottom()

    def batch_finalize_turns(self) -> None:
        """Finalize all completed assistant turns in batch mode.

        During batch rebuild, :meth:`finalize_turn` is called per-turn
        in :meth:`ChatManager._rebuild_display_from_sections`.  This method
        provides a single-pass alternative that processes all turns at once,
        removing empty sections, swapping Static → Markdown in the data
        model, and preparing labels.

        Must be called while in batch mode (between :meth:`begin_batch`
        and :meth:`end_batch`).  After this, call :meth:`end_batch` to
        trigger the final rebuild.

        Note: This does NOT clear ``_section_widgets`` / ``_section_texts`` /
        ``_section_types`` — those are cleared by :meth:`end_batch`.
        """
        # Find all assistant nodes that have sections to finalize.
        for child in list(self._root.children):
            if child.data and child.data.get("role") == "assistant":
                self._finalize_assistant_node(child)

        # Swap Static → Markdown in the data model (no DOM operations
        # needed — the tree will be rebuilt by end_batch which mounts
        # the correct widgets).
        self._swap_sections_in_data_model()

        # Mark active turn as done, but don't clear section tracking yet —
        # end_batch clears them after the rebuild.
        self._active_asst_id = None

    def _swap_sections_in_data_model(self) -> None:
        """Swap completed response/tools sections from Static → Markdown
        in the tree data model only.

        Unlike :meth:`_swap_sections_to_markdown`, this does not perform
        any DOM operations.  It replaces the content widget on the tree
        node so that when :meth:`end_batch` triggers a
        :meth:`Tree.rebuild`, the new Markdown widgets are mounted
        directly instead of Static widgets.

        Thinking sections are left as Static — they don't benefit from
        markdown rendering.
        """
        for section_id, section_type in self._section_types.items():
            if section_type in _KEEP_STATIC_SECTIONS:
                continue
            widget = self._section_widgets.get(section_id)
            if not isinstance(widget, Static):
                continue
            text = self._section_texts.get(section_id, "")
            if not text:
                continue

            # Update the tree data model — replace the Static widget reference
            # on the leaf node with a new Markdown widget.
            section_branch = self._find_node(section_id)
            if section_branch is not None and section_branch.children:
                leaf = section_branch.children[0]
                new_widget = Markdown(text, id=f"{widget.id}-rendered")
                leaf.content = new_widget
                # Also update the tracking dict so the tree mounts the
                # correct widget during rebuild.
                self._section_widgets[section_id] = new_widget

            # Unmount the old Static widget if it's in the DOM.
            # (During batch rebuild it may not be mounted yet.)
            try:
                if widget.parent is not None:
                    widget.remove()
            except Exception:
                pass

    def _finalize_assistant_node(self, asst_node: TreeNode) -> None:
        """Finalize a single assistant node: remove empty sections,
        update labels, and prepare for Static→Markdown swap.

        This is the batch-mode equivalent of the removal + label update
        parts of finalize_turn.  The Static→Markdown swap is done
        separately in batch_finalize_turns via _swap_sections_to_markdown.
        """
        # Remove empty section children.
        keep = [c for c in asst_node.children if not self._is_empty_section(c)]
        if len(keep) != len(asst_node.children):
            # Unregister removed nodes from the lookup map.
            removed = [c for c in asst_node.children if c not in keep]
            for node in removed:
                self._unregister_node(node)
            asst_node.children = keep

        # Update collapsed label to show a preview of the response.
        preview = self._turn_preview(asst_node)
        if preview:
            asst_node.label = f"\uf4ad  [green]Assistant:[/green] {preview}"

    # ------------------------------------------------------------------
    # Rebuild
    # ------------------------------------------------------------------

    def _rebuild(self) -> None:
        """Rebuild the tree with throttling for streaming performance.

        During streaming, multiple structural additions can happen in
        quick succession (e.g. add_section + add_tool_call).  Throttling
        coalesces rapid _rebuild() calls into a single rebuild per frame.

        The first call schedules a rebuild via ``set_timer(0, ...)``;
        subsequent calls within the same frame are skipped.  When the
        timer fires, :meth:`_do_deferred_rebuild` resets the pending
        flag and performs the rebuild.

        For immediate, non-throttled rebuilds (e.g. in :meth:`clear`
        or :meth:`end_batch`), use :meth:`_immediate_rebuild` instead.

        During batch mode, this is a no-op — the rebuild is deferred
        to :meth:`end_batch`.
        """
        if self._batch_mode:
            return
        if self._rebuild_pending:
            return
        self._rebuild_pending = True
        self.set_timer(1 / 60, self._do_deferred_rebuild)

    def _do_deferred_rebuild(self) -> None:
        """Fire the deferred rebuild and reset the pending flag.

        During streaming, this is a lightweight rebuild that doesn't
        call restore_expand_state() — each add method handles targeted
        expand of the new node.  Full restore_expand_state() is only
        needed during batch rebuild (end_batch).
        """
        self._rebuild_pending = False
        tree = self.query_one(Tree)
        tree.rebuild()
        # Note: no restore_expand_state() here.  Each add method
        # does targeted expand_node() for the new node, so we don't
        # need the O(n) walk.  Visibility is already refreshed by
        # tree.rebuild().

    def _immediate_rebuild(self) -> None:
        """Immediate, non-throttled rebuild with full expand state restore.

        Used by :meth:`clear` and :meth:`end_batch` where we need the
        rebuild to happen right away and want full expand state restoration.
        """
        self._rebuild_pending = False
        tree = self.query_one(Tree)
        tree.rebuild()
        tree.restore_expand_state()


    # ------------------------------------------------------------------
    # Tool call entries (individual branches under the Assistant node)
    # ------------------------------------------------------------------

    def add_tool_call(
        self,
        name: str,
        arguments: dict,
    ) -> str:
        """Add a tool call branch directly under the current assistant turn.

        Creates an expandable branch with the tool name as header.
        The collapsed label shows a short argument summary; the expanded
        label shows just the tool name.  A Markdown detail leaf below
        shows the full arguments.

        Tool calls sit alongside Thinking and Response sections as
        peers under the Assistant branch — no intermediate "Tools"
        wrapper.

        Parameters
        ----------
        name:
            Tool name (e.g. ``"read_file"``).
        arguments:
            Tool arguments as a dict.

        Returns the tool call node ID.
        """
        from skills.chat.tool_format import (
            format_tool_call_branch_label,
            format_tool_call_branch_label_expanded,
            format_tool_call_detail,
        )

        if self._active_asst_id is None:
            raise RuntimeError(
                "No active assistant turn — call begin_assistant_turn first"
            )

        self._tool_call_count += 1
        tc_id = f"tc-{self._tool_call_count}"

        # Collapsed: name + short args.  Expanded: just the name.
        label = format_tool_call_branch_label(name, arguments)
        label_expanded = format_tool_call_branch_label_expanded(name)

        # Detail leaf — Markdown with formatted arguments.
        detail = format_tool_call_detail(name, arguments)
        md = Markdown(detail, id=f"md-{tc_id}")
        leaf = TreeNode(f"{tc_id}-leaf", "", content=md)

        branch = TreeNode(
            tc_id,
            label,
            label_expanded=label_expanded,
            data={"tool_call": name},
            children=[leaf],
        )

        # Add directly to the assistant branch.
        asst_node = self._find_node(self._active_asst_id)
        if asst_node is not None:
            asst_node.children.append(branch)
            self._register_node(branch)

        self._rebuild()

        # Expand the tool call branch — unless config says it should start collapsed.
        tree = self.query_one(Tree)
        if self._open_tools:
            tree.expand_node(tc_id)
        else:
            tree.collapse_node(tc_id)
        if not tree.is_user_collapsed(self._active_asst_id):
            tree.expand_node(self._active_asst_id)

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
        the DOM in-place.

        Thinking sections are left as ``Static`` — they don't benefit from
        markdown rendering and the swap cost isn't justified.
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

        Updates the tree data model and swaps the widget in the DOM.
        Best-effort — failures are silently ignored since this is a
        non-critical visual upgrade.
        """
        old_widget = self._section_widgets.get(section_id)
        if old_widget is None or not isinstance(old_widget, Static):
            return

        text = self._section_texts.get(section_id, "")
        if not text:
            return

        # Create new Markdown widget.
        new_widget = Markdown(text, id=f"{old_widget.id}-rendered")

        # Update the tree data model so future rebuilds use the new widget.
        section_branch = self._find_node(section_id)
        if section_branch is not None and section_branch.children:
            leaf = section_branch.children[0]
            leaf.content = new_widget

        # Swap in the DOM: remove the old Static, mount the new Markdown
        # into the same parent container.
        try:
            parent = old_widget.parent
            if parent is not None:
                old_widget.remove()
                await parent.mount(new_widget)
        except Exception:
            pass  # Best-effort — non-critical visual improvement

        # Update the widget mapping.
        self._section_widgets[section_id] = new_widget


def _find_node_recursive(parent: TreeNode, node_id: str) -> TreeNode | None:
    """Recursively search for a node by ID."""
    for child in parent.children:
        if child.id == node_id:
            return child
        found = _find_node_recursive(child, node_id)
        if found is not None:
            return found
    return None


def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."