"""Conversation history panel — sidebar tab for browsing and resuming past chats.

Lists all chats stored in the database, showing a preview of the first
user message as the title.  Clicking a conversation opens it in a new
workspace tab, restoring the full message history so the user can
continue the conversation.

The panel also provides:

* **Refresh** — reload the list from the database
* **Delete** — delete a conversation after confirmation
"""

from __future__ import annotations

from datetime import datetime, timezone

from textual.app import ComposeResult
from textual.containers import Container

from ui.sidebar.registry import register_sidebar_tab
from ui.tree.tree import Tree, NodeSelected
from ui.tree.tree_row import RowButton, TreeNode, TreeRow
from utils.icons import DELETE, REFRESH
from context import AppContext
from skills.chat.chat_tab import ChatTabState
from ui.workspace.tabs import TabState

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEL = "del"

# ---------------------------------------------------------------------------
# Helper — generate a short preview from a chat's sections
# ---------------------------------------------------------------------------


def _chat_preview(sections: list[dict], max_len: int = 80) -> str:
    """Return a short preview string from a list of section dicts.

    Looks for the first user message and truncates it.  Falls back to
    "New conversation" if no user message is found.
    """
    for sec in sections:
        if sec.get("content_type") == "user" and sec.get("content"):
            text = sec["content"].strip().split("\n")[0]
            if len(text) > max_len:
                return text[: max_len - 3] + "..."
            return text
    return "New conversation"


def _format_timestamp(ts: str) -> str:
    """Format an ISO timestamp into a short human-readable string."""
    try:
        dt = datetime.fromisoformat(ts)
        now = datetime.now(timezone.utc)
        delta = now - dt
        if delta.days == 0:
            return "today"
        if delta.days == 1:
            return "yesterday"
        if delta.days < 7:
            return f"{delta.days}d ago"
        if delta.days < 365:
            return f"{delta.days // 7}w ago"
        return dt.strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return ""


# ---------------------------------------------------------------------------
# HistoryPanel
# ---------------------------------------------------------------------------


@register_sidebar_tab(name="history", icon="󰉉", side="left", tooltip="History")
class HistoryPanel(Container):
    """Sidebar panel listing past conversations from the database.

    Each conversation is shown as a tree node.  Clicking a node opens
    the conversation in a new chat tab.  Each node has a delete button.
    """

    def __init__(self):
        super().__init__()
        self._db = None
        self._ctx: AppContext | None = None

    # ------------------------------------------------------------------
    # Compose
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        self._tree = Tree(TreeNode("history-root", "Loading...", buttons=[RowButton("refresh", REFRESH)]))
        yield self._tree

    def on_mount(self) -> None:
        app = self.app
        if hasattr(app, "context") and app.context is not None:
            self._ctx = app.context
            self._db = app.context.database
        self._rebuild()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def refresh_history(self) -> None:
        """Re-read chats from the database and rebuild the tree."""
        self._rebuild()

    # ------------------------------------------------------------------
    # Rebuild
    # ------------------------------------------------------------------

    def _rebuild(self) -> None:
        """Load chats from the database and populate the tree."""
        if self._db is None:
            self._tree.set_root(
                TreeNode("history-root", "No database available",
                         buttons=[RowButton("refresh", REFRESH)])
            )
            return

        try:
            chats = self._db.list_chats()
        except Exception:
            self._tree.set_root(
                TreeNode("history-root", "Error loading chats",
                         buttons=[RowButton("refresh", REFRESH)])
            )
            return

        if not chats:
            self._tree.set_root(
                TreeNode(
                    "history-root",
                    "󰉉  History",
                    buttons=[RowButton("refresh", REFRESH)],
                    children=[
                        TreeNode(
                            "history-empty",
                            "  No conversations yet",
                        )
                    ],
                )
            )
            self._tree.expand_all()
            return

        children: list[TreeNode] = []
        for chat in chats:
            chat_id = chat["id"]
            title = chat.get("title", "") or ""
            ts = chat.get("updated_at", "") or chat.get("created_at", "")

            # If no title was saved, build a preview from sections
            if not title:
                try:
                    sections = self._db.load_sections(chat_id)
                    title = _chat_preview(sections)
                except Exception:
                    title = "Conversation"

            # Truncate long titles for the tree label
            display = title if len(title) <= 60 else title[:57] + "..."
            time_str = _format_timestamp(ts) if ts else ""
            label = f"󰭟  {display}"
            if time_str:
                label = f"󰭟  {display}  [dim]{time_str}[/dim]"

            children.append(
                TreeNode(
                    f"chat-{chat_id}",
                    label,
                    data={
                        "chat_id": chat_id,
                        "type": "chat",
                    },
                    buttons=[RowButton(_DEL, DELETE, "history-del")],
                )
            )

        root = TreeNode(
            "history-root",
            "󰉉  History",
            buttons=[RowButton("refresh", REFRESH)],
            children=children,
        )
        self._tree.set_root(root)
        self._tree.expand_all()

    # ------------------------------------------------------------------
    # Tree selection — open chat in a new tab
    # ------------------------------------------------------------------

    def on_node_selected(self, msg: NodeSelected) -> None:
        """Open the selected conversation in a new chat tab."""
        msg.stop()
        node = msg.node
        if not node.data or node.data.get("type") != "chat":
            return
        chat_id = node.data.get("chat_id", "")
        if not chat_id:
            return
        self._open_chat(chat_id)

    # ------------------------------------------------------------------
    # Inline button handlers — Delete
    # ------------------------------------------------------------------

    def on_tree_row_button_pressed(self, event: TreeRow.ButtonPressed) -> None:
        """Handle inline button presses on tree rows."""
        event.stop()
        if event.action_id == "refresh":
            self._rebuild()
            return
        if event.action_id == _DEL:
            node = event.node
            chat_id = node.data.get("chat_id", "") if node.data else ""
            if not chat_id:
                return
            self._delete_chat(chat_id)

    # ------------------------------------------------------------------
    # Actions — Open chat
    # ------------------------------------------------------------------

    def _open_chat(self, chat_id: str) -> None:
        """Open a past conversation in a new chat tab.

        Creates a ChatTabState with just chat_id and db. The ChatManager
        handles loading sections from the DB and rebuilding the display
        via _sync_conversation(finalize=True) in on_mount().
        """
        if self._ctx is None or self._ctx.database is None:
            return
        ctx = self._ctx

        # Get chat metadata for the tab label.
        try:
            chat_meta = ctx.database.get_chat(chat_id)
        except Exception:
            chat_meta = None

        preview = "New conversation"
        if chat_meta and chat_meta.get("title"):
            preview = chat_meta["title"]
        else:
            # Load sections only for the tab label preview.
            try:
                sections = ctx.database.load_sections(chat_id)
                if sections:
                    preview = _chat_preview(sections)
                    # Update the chat title if it was empty.
                    if preview != "New conversation":
                        try:
                            ctx.database.update_chat(chat_id, preview)
                        except Exception:
                            pass
            except Exception:
                pass

        # Create a ChatTabState with just chat_id and db.
        # The ChatManager.on_mount() will see _chat_id is set and call
        # _rebuild_and_resume() → _sync_conversation(finalize=True)
        # which loads everything from the DB.
        state = ChatTabState(ctx=ctx, agent_id=None)
        state._db = ctx.database
        state._chat_id = chat_id

        # Open a chat tab with this state
        from ui.workspace.workspace import Workspace
        from ui.workspace.tabs import WorkspaceTabs

        app = self.app
        try:
            workspace = app.query_one(Workspace)
            container_id = f"pane-{workspace.focused_id}"
            container = app.query_one(f"#{container_id}")
            tabs = container.query_one(WorkspaceTabs)
        except Exception:
            import logging
            logging.getLogger(__name__).exception("Error finding workspace tabs")
            return

        # Use a unique tab ID based on the chat_id so each past
        # conversation gets its own tab
        tab_id = f"chat-{chat_id[:8]}"
        label = f"󰭟 {preview[:30]}"

        # If tab already exists, switch to it
        if tab_id in tabs._tabs:
            tabs.switch_tab(tab_id)
            return

        # Use the standard chat content factory — it calls set_state()
        # then wire_from_context(), giving us a working agent.
        # The ChatManager.on_mount() detects _chat_id and rebuilds from DB.
        from skills.chat.chat_tab import _create_chat_content

        tabs.open_tab(
            tab_id,
            label,
            state=state,
            content_factory=_create_chat_content,
        )

    # ------------------------------------------------------------------
    # Actions — Delete chat
    # ------------------------------------------------------------------

    def _delete_chat(self, chat_id: str) -> None:
        """Delete a chat after confirmation."""
        from ui.widgets.confirm_modal import ConfirmModal

        async def do_delete() -> None:
            confirmed = await self.app.push_screen_wait(
                ConfirmModal(
                    "Delete this conversation?",
                    "This will permanently remove the conversation and all its messages.",
                    confirm_label="Delete",
                )
            )
            if not confirmed:
                return

            if self._ctx is None or self._ctx.database is None:
                return

            try:
                self._ctx.database.delete_chat(chat_id)
            except Exception:
                pass

            self._rebuild()

        self.app.run_worker(do_delete())