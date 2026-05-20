"""Chat slash commands — /clear and /new.

These commands depend on the chat plugin's ChatManager, so they live
inside the plugin rather than in the core ``cmd/`` directory.

Registered at import time via ``@register_command()``.
"""

from __future__ import annotations

from core.commands import register_command


@register_command(name="clear", description="Clear the chat display")
async def clear(app, args: str) -> str:
    """Clear the chat display, removing all messages from the view."""
    from plugins.chat.chat_display import ChatDisplay
    from plugins.chat.chat_manager import ChatManager

    try:
        manager = app.query_one(ChatManager)
        display = manager.query_one(ChatDisplay)
        display.clear()
    except Exception:
        pass

    return "Chat cleared."


@register_command(name="new", description="Start a new conversation")
async def new_chat(app, args: str) -> str:
    """Start a new conversation, resetting history and creating a fresh chat."""
    from plugins.chat.chat_manager import ChatManager

    try:
        manager = app.query_one(ChatManager)
        manager.new_conversation()
    except Exception:
        pass

    return "New conversation started."


def register_chat_commands() -> None:
    """No-op — commands are registered by the decorators at import time.

    This function exists so ``__init__.py`` has a clear import target,
    but the actual registration happens when the decorators execute.
    """
    pass