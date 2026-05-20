"""Terminal plugin — embedded terminal emulator for workspace panes.

Importing this module triggers all side-effect registrations:
- ``@register_handler("terminal.open")`` for opening terminal tabs
- ``register_terminal_leader_chords`` for the ``Ctrl+Space t o`` chord
"""

# Side-effect imports — trigger decorator registrations.
from plugins.terminal.terminal_handler import (  # noqa: F401
    register_terminal_leader_chords,
)

# Register leader chords at plugin load time.
register_terminal_leader_chords()