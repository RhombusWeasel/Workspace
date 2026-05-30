"""AI chat skill — streaming conversation in a workspace tab.

Importing this module triggers all side-effect registrations:

- ``@register_handler("chat.open")`` to open a chat tab on demand
- ``register_chat_leader_chords()`` for the ``Ctrl+Space a`` leader chord
- ``@register_command("clear")`` and ``@register_command("new")``

The chat tab is opened via the leader chord or by posting a
``WorkspaceEvent("chat.open")``.  It is NOT auto-opened on startup.
"""

# Side-effect imports — trigger decorator registrations.
from skills.chat.chat_tab import register_chat_leader_chords  # noqa: F401
from skills.chat.commands import register_chat_commands       # noqa: F401

# Register leader chords at skill load time.
register_chat_leader_chords()

__all__ = ["register_chat_leader_chords"]