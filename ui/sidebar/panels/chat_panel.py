"""Chat panel — thin sidebar tab wrapper around :class:`~ui.chat.chat_manager.ChatManager`.

The ChatPanel is a sidebar tab that composes a ``ChatManager`` widget
(which in turn composes ``ChatInput`` + ``ChatDisplay``) and wires it
from ``AppContext`` on mount.

This thin wrapper means the same ``ChatManager`` can also be embedded
in a workspace pane or any other container without the sidebar tie-in.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container

from ui.chat.chat_manager import ChatManager
from ui.sidebar.registry import register_sidebar_tab


@register_sidebar_tab(name="chat", icon="\uf4ad", side="right", tooltip="Chat")
class ChatPanel(Container):
    """Sidebar tab hosting a :class:`~ui.chat.chat_manager.ChatManager`.

    On mount, wires the manager from the running app's ``AppContext``
    (agent, tools, database).  The manager handles everything else.
    """

    def compose(self) -> ComposeResult:
        yield ChatManager()

    def on_mount(self) -> None:
        app = self.app
        if hasattr(app, "context") and app.context is not None:
            self.query_one(ChatManager).wire_from_context(app.context)
