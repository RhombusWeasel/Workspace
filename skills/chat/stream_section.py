"""Stream section — owns one section of a streaming assistant turn.

Created when the stream transitions to a new section type (thinking,
tool_call, response).  Accumulates text, updates the ChatDisplay on
every append, and provides finalization / abort helpers.

ChatManager creates a new ``StreamSection`` each time the chunk type
changes; the old section is simply discarded.

**Batched flush** — Chunks are accumulated and flushed to the display
at a fixed interval (default 50 ms) rather than on every single chunk.
This dramatically reduces the number of ``Static.update()`` calls
during fast streaming (e.g. reasoning models that emit hundreds of
tiny thinking tokens per second).  ``replace()`` and ``flush()`` bypass
the interval and update immediately.
"""

from __future__ import annotations

import asyncio

from skills.chat.chat_display import ChatDisplay


# Mapping from persistence content_type → display section_type.
# The database uses "tool_call" to distinguish from the display "tools".
_DISPLAY_TYPE = {
    "tool_call": "tools",
}

# Default interval between display flushes during streaming (seconds).
# At 50 ms the display updates ~20 times/second, which is smooth enough
# for human perception while reducing update frequency 10–15× compared
# to per-chunk updates on fast models.
_DEFAULT_FLUSH_INTERVAL = 0.05


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
    flush_interval:
        Minimum time in seconds between display updates.  Chunks
        that arrive faster than this are buffered and flushed as
        a batch.  Defaults to 50 ms.
    """

    def __init__(
        self,
        display: ChatDisplay,
        section_type: str,
        flush_interval: float = _DEFAULT_FLUSH_INTERVAL,
    ):
        self._display = display
        self.section_type = _DISPLAY_TYPE.get(section_type, section_type)
        self.section_id = display.add_section(self.section_type)
        self._text = ""
        self._flush_interval = flush_interval
        self._last_flush = 0.0
        self._dirty = False
        self._flush_task: asyncio.Task | None = None

    # ------------------------------------------------------------------
    # Content updates
    # ------------------------------------------------------------------

    async def append(self, text: str) -> None:
        """Add incremental text and schedule a display refresh.

        If the flush interval has elapsed since the last update, the
        display is refreshed immediately.  Otherwise the update is
        deferred to a timer that fires after the remaining interval.
        """
        self._text += text
        self._dirty = True
        now = asyncio.get_running_loop().time()
        if now - self._last_flush >= self._flush_interval:
            await self._do_flush()
        elif self._flush_task is None:
            self._flush_task = asyncio.ensure_future(self._delayed_flush())

    async def replace(self, text: str) -> None:
        """Replace the entire section content (used for tool-call batches).

        Cancels any pending batched flush and updates the display
        immediately — tool calls are discrete events that should appear
        without delay.
        """
        self._cancel_pending_flush()
        self._text = text
        self._dirty = False
        self._last_flush = asyncio.get_running_loop().time()
        await self._display.update_section(self.section_id, self._text)

    @property
    def text(self) -> str:
        """The accumulated text for this section."""
        return self._text

    # ------------------------------------------------------------------
    # Flush control
    # ------------------------------------------------------------------

    async def flush(self) -> None:
        """Force-flush any pending buffered content to the display.

        Call this before persisting a section or switching to a new one
        to ensure the display shows the latest accumulated text.
        """
        self._cancel_pending_flush()
        await self._do_flush()

    async def _delayed_flush(self) -> None:
        """Flush after the remaining interval has elapsed."""
        try:
            remaining = self._flush_interval - (
                asyncio.get_running_loop().time() - self._last_flush
            )
            if remaining > 0:
                await asyncio.sleep(remaining)
            await self._do_flush()
        except asyncio.CancelledError:
            pass

    async def _do_flush(self) -> None:
        """Perform the actual display update if content is dirty."""
        if self._dirty:
            self._dirty = False
            self._last_flush = asyncio.get_running_loop().time()
            await self._display.update_section(self.section_id, self._text)
        self._flush_task = None

    def _cancel_pending_flush(self) -> None:
        """Cancel any pending delayed flush task."""
        if self._flush_task is not None:
            self._flush_task.cancel()
            self._flush_task = None

    # ------------------------------------------------------------------
    # Abort handling
    # ------------------------------------------------------------------

    async def mark_aborted(self) -> StreamSection | None:
        """Append an ``[aborted]`` marker to the display.

        For ``response`` sections, the marker is appended inline.
        For other section types, a fresh ``response`` section is
        created with just the marker.

        Flushes immediately so the abort marker is visible without
        delay.

        Returns a new ``StreamSection`` if one was created (so the
        caller can replace its current watcher), or ``None``.
        """
        if self.section_type == "response":
            await self.append("\n\n*[aborted]*")
            await self.flush()
            return None
        # Flush the current section first.
        await self.flush()
        abort_section = StreamSection(self._display, "response")
        await abort_section.replace("*[aborted]*")
        return abort_section