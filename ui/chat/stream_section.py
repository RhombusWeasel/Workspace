"""Stream section — owns one section of a streaming assistant turn.

Created when the stream transitions to a new section type (thinking,
tool_call, response).  Accumulates text, updates the ChatDisplay on
every append, and provides finalization / abort helpers.

ChatManager creates a new ``StreamSection`` each time the chunk type
changes; the old section is simply discarded.
"""

from __future__ import annotations

from ui.chat.chat_display import ChatDisplay


# Mapping from persistence content_type → display section_type.
# The database uses "tool_call" to distinguish from the display "tools".
_DISPLAY_TYPE = {
    "tool_call": "tools",
}


class StreamSection:
    """Owns one section of a streaming assistant turn.

    Parameters
    ----------
    display:
        The :class:`~ui.chat.chat_display.ChatDisplay` to update.
    section_type:
        Section type — ``"thinking"``, ``"tools"``, ``"response"``,
        or ``"system"``.  The alias ``"tool_call"`` is accepted and
        mapped to ``"tools"`` for display purposes.
    """

    def __init__(self, display: ChatDisplay, section_type: str):
        self._display = display
        self.section_type = _DISPLAY_TYPE.get(section_type, section_type)
        self.section_id = display.add_section(self.section_type)
        self._text = ""

    # ------------------------------------------------------------------
    # Content updates
    # ------------------------------------------------------------------

    async def append(self, text: str) -> None:
        """Add incremental text and refresh the display."""
        self._text += text
        await self._display.update_section(self.section_id, self._text)

    async def replace(self, text: str) -> None:
        """Replace the entire section content (used for tool-call batches)."""
        self._text = text
        await self._display.update_section(self.section_id, self._text)

    @property
    def text(self) -> str:
        """The accumulated text for this section."""
        return self._text

    # ------------------------------------------------------------------
    # Abort handling
    # ------------------------------------------------------------------

    async def mark_aborted(self) -> StreamSection | None:
        """Append an ``[aborted]`` marker to the display.

        For ``response`` sections, the marker is appended inline.
        For other section types, a fresh ``response`` section is
        created with just the marker.

        Returns a new ``StreamSection`` if one was created (so the
        caller can replace its current watcher), or ``None``.
        """
        if self.section_type == "response":
            await self.append("\n\n*[aborted]*")
            return None
        abort_section = StreamSection(self._display, "response")
        await abort_section.replace("*[aborted]*")
        return abort_section