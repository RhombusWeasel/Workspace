"""Chat tab — workspace tab integration for the AI chat.

Provides:

- ``ChatTabState`` — persistent state that survives workspace recomposition
- ``open_chat_tab()`` — opens a chat tab in the focused workspace pane
- ``@register_handler("chat.open")`` — event handler to open a chat tab
- ``register_chat_leader_chords()`` — leader chord ``Ctrl+Space a``

Chat state (conversation history, agent, database) is stored in
``ChatTabState`` and survives workspace splits and closes.  When the
workspace is recomposed, ``ChatManager.flush_state()`` copies widget
state into ``ChatTabState``, and the content factory restores it in
the fresh widget.
"""

from __future__ import annotations

from typing import Any

from core.events import register_handler
from core.leader import register_action
from context import AppContext
from ui.workspace.tabs import TabState
from plugins.chat.chat_manager import ChatManager


# ---------------------------------------------------------------------------
# ChatTabState — persists across workspace recomposition
# ---------------------------------------------------------------------------


class ChatTabState(TabState):
    """Persistent state for a chat workspace tab.

    Owns the conversation state (history, sections, agent, database
    reference) so it survives DOM recomposition.  When the workspace is
    split or closed, ``ChatManager.flush_state()`` writes widget state
    back here.  The content factory then creates a fresh ChatManager
    that reads from this state, restoring the conversation.
    """

    def __init__(self, ctx: AppContext | None = None) -> None:
        super().__init__()
        self._ctx: AppContext | None = ctx
        # Conversation state — populated by flush_state(), read by the
        # content factory when recreating the widget after recomposition.
        self._history: list[dict[str, Any]] = []
        self._sections: list[dict[str, str]] = []
        self._agent: Any = None
        self._tools: list[dict[str, Any]] | None = None
        self._db: Any = None
        self._chat_id: str | None = None

    def dispose(self) -> None:
        """Release resources when the chat tab is permanently closed."""
        # Release database chat reference (the DB itself is shared).
        self._db = None
        self._chat_id = None


# ---------------------------------------------------------------------------
# Content factory — recreates ChatManager from ChatTabState
# ---------------------------------------------------------------------------


def _create_chat_content(state: TabState) -> ChatManager:
    """Content factory that creates a ChatManager wired from the tab state.

    Called by WorkspaceTabs when the tab content needs to be recreated
    after a DOM recomposition (e.g. workspace split/close).

    If the state already carries conversation data (from a prior
    ChatManager that was flushed), the new ChatManager restores that
    data and rebuilds the visual display.
    """
    manager = ChatManager()
    if isinstance(state, ChatTabState):
        manager.set_state(state)
        if not state._history and state._ctx is not None:
            # No prior conversation — just wire the agent.
            manager.wire_from_context(state._ctx)
    return manager


# ---------------------------------------------------------------------------
# Open chat tab
# ---------------------------------------------------------------------------


def open_chat_tab(ctx: AppContext) -> None:
    """Open a chat tab in the focused workspace pane.

    If a chat tab already exists in the focused pane, switch to it.
    The tab is identified by the ID ``"chat"``.
    """
    app = ctx.app
    if app is None:
        return

    from ui.workspace.workspace import Workspace

    try:
        workspace = app.query_one(Workspace)
    except Exception:
        return

    # Find the focused pane's WorkspaceTabs
    from ui.workspace.tabs import WorkspaceTabs

    try:
        container_id = f"pane-{workspace.focused_id}"
        container = app.query_one(f"#{container_id}")
        tabs = container.query_one(WorkspaceTabs)
    except Exception:
        return

    # If a chat tab already exists, switch to it
    if "chat" in tabs._tabs:
        tabs.switch_tab("chat")
        return

    # Create state and open the tab
    chat_state = ChatTabState(ctx=ctx)
    tabs.open_tab(
        "chat",
        "󰭟 AI Chat",
        state=chat_state,
        content_factory=_create_chat_content,
    )


# ---------------------------------------------------------------------------
# Event handler
# ---------------------------------------------------------------------------


@register_handler("chat.open")
def _on_chat_open(data: dict, ctx: AppContext) -> None:
    """Handle ``chat.open`` events — open a chat workspace tab."""
    open_chat_tab(ctx)


# ---------------------------------------------------------------------------
# Leader chord registration
# ---------------------------------------------------------------------------


def register_chat_leader_chords() -> None:
    """Register the ``Ctrl+Space a`` leader chord for opening AI chat."""
    register_action(
        ["a"],
        "AI Chat",
        event_type="chat.open",
    )