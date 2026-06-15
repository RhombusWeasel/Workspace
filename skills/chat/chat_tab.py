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
from skills.chat.chat_manager import ChatManager


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

    If ``agent_id`` is set, the chat tab uses that specific agent
    definition instead of the session default.
    """

    def __init__(self, ctx: AppContext | None = None, agent_id: str | None = None) -> None:
        super().__init__()
        self._ctx: AppContext | None = ctx
        self._agent_id: str | None = agent_id
        # Conversation state — populated by flush_state(), read by the
        # content factory when recreating the widget after recomposition.
        self._history: list[dict[str, Any]] = []
        self._sections: list[dict[str, str]] = []
        self._agent: Any = None
        self._tools: list[dict[str, Any]] | None = None
        self._db: Any = None
        self._chat_id: str | None = None
        # Stream ID — set when streaming is active so that the new
        # ChatManager can re-subscribe after workspace recomposition.
        self._stream_id: str | None = None

    def dispose(self) -> None:
        """Release resources when the chat tab is permanently closed.

        Cancels any active stream via the StreamManager so the LLM
        agent is aborted and the background task is cleaned up.
        """
        if self._stream_id and self._ctx and self._ctx.stream_manager:
            self._ctx.stream_manager.cancel(self._stream_id)
            self._stream_id = None
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
            if state._agent_id:
                manager.wire_agent_from_id(state._ctx, state._agent_id)
            else:
                manager.wire_from_context(state._ctx)
    return manager


# ---------------------------------------------------------------------------
# Open chat tab
# ---------------------------------------------------------------------------


def open_chat_tab(ctx: AppContext, agent_id: str | None = None) -> None:
    """Open a chat tab in the focused workspace pane.

    If a chat tab already exists in the focused pane, switch to it.
    The tab is identified by the ID ``"chat"``.

    If *agent_id* is provided, the chat tab will use that specific
    agent definition instead of the session default.
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

    # Determine tab ID — use a unique ID per agent if specified,
    # otherwise reuse the default "chat" tab.
    if agent_id:
        tab_id = f"chat-{agent_id}"
        label_prefix = f"󰭟 {agent_id}"
    else:
        tab_id = "chat"
        label_prefix = "󰭟 AI Chat"

    # If a tab with this agent already exists, switch to it
    if tab_id in tabs._tabs:
        tabs.switch_tab(tab_id)
        return

    # Create state and open the tab
    chat_state = ChatTabState(ctx=ctx, agent_id=agent_id)
    tabs.open_tab(
        tab_id,
        label_prefix,
        state=chat_state,
        content_factory=_create_chat_content,
    )


# ---------------------------------------------------------------------------
# Event handler
# ---------------------------------------------------------------------------


@register_handler("chat.open")
def _on_chat_open(data: dict, ctx: AppContext) -> None:
    """Handle ``chat.open`` events — open a chat workspace tab.

    If ``data`` contains an ``agent_id`` key, the chat tab uses that
    specific agent definition.
    """
    agent_id = data.get("agent_id") if data else None
    open_chat_tab(ctx, agent_id=agent_id)


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


# ---------------------------------------------------------------------------
# Session handler registration
# ---------------------------------------------------------------------------

from core.session import TabTypeHandler, register_tab_type


def _serialise_chat(state: ChatTabState) -> dict:
    """Extract persistent data from a ChatTabState."""
    return {
        "chat_id": state._chat_id,
        "agent_id": state._agent_id,
    }


def _deserialise_chat(data: dict, ctx: AppContext) -> ChatTabState:
    """Reconstruct a ChatTabState from serialised data."""
    state = ChatTabState(ctx=ctx, agent_id=data.get("agent_id"))
    state._chat_id = data.get("chat_id")
    return state


def _make_chat_label(state: ChatTabState) -> str:
    """Produce the tab label for a restored chat tab."""
    if state._agent_id:
        return f"ë ° {state._agent_id}"
    return "ë ° AI Chat"


register_tab_type(TabTypeHandler(
    tab_type="chat",
    serialise=_serialise_chat,
    deserialise=_deserialise_chat,
    content_factory=_create_chat_content,
    make_label=_make_chat_label,
))