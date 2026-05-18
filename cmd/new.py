"""/new — start a new conversation.

Resets the chat history and display, creating a fresh chat session
in the database.

Registered at import time via ``@register_command()``.
"""

from __future__ import annotations

from core.commands import register_command


@register_command(name="new", description="Start a new conversation")
async def new_chat(app, args: str) -> str:
    """Start a new conversation, resetting history and creating a fresh chat."""
    from ui.chat.chat_manager import ChatManager

    try:
        manager = app.query_one(ChatManager)
        manager.new_conversation()
    except Exception:
        pass

    return "New conversation started."