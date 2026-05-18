"""/clear — clear the chat display.

Removes all messages from the current conversation view.
History is preserved in the database; only the display is reset.

Registered at import time via ``@register_command()``.
"""

from __future__ import annotations

from core.commands import register_command


@register_command(name="clear", description="Clear the chat display")
async def clear(app, args: str) -> str:
    """Clear the chat display, removing all messages from the view."""
    from ui.chat.chat_display import ChatDisplay
    from ui.chat.chat_manager import ChatManager

    try:
        manager = app.query_one(ChatManager)
        display = manager.query_one(ChatDisplay)
        display.clear()
    except Exception:
        pass

    return "Chat cleared."