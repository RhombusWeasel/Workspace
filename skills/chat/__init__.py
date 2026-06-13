"""AI chat skill — streaming conversation in a workspace tab.

Importing this module triggers all side-effect registrations:

- ``@register_handler("chat.open")`` to open a chat tab on demand
- ``register_chat_leader_chords()`` for the ``Ctrl+Space a`` leader chord
- ``@register_command("clear")`` and ``@register_command("new")``
- ``register_defaults`` for ``session.open_thinking``, ``session.open_tools``, and ``session.show_system_prompt``

The chat tab is opened via the leader chord or by posting a
``WorkspaceEvent("chat.open")``.  It is NOT auto-opened on startup.
"""

from core.config import register_defaults

# Config defaults for the chat skill.
# When False, thinking/tool-call branches in the chat tree start collapsed.
# When True, show_system_prompt displays the LLM system prompt at the start
# of each conversation.
register_defaults({
    "session": {
        "open_thinking": False,
        "open_tools": False,
        "show_system_prompt": False,
    },
})

# Side-effect imports — trigger decorator registrations.
from skills.chat.chat_tab import register_chat_leader_chords  # noqa: F401
from skills.chat.commands import register_chat_commands       # noqa: F401

# Register leader chords at skill load time.
register_chat_leader_chords()

__all__ = ["register_chat_leader_chords"]