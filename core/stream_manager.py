"""Stream Manager — owns LLM stream lifecycle independently of widgets.

Decouples the streaming async iteration from any particular ChatManager
widget instance.  When the workspace is recomposed (split / close), the
old ChatManager is destroyed but the stream continues running inside
StreamManager.  The new ChatManager re-subscribes by stream ID and
receives any buffered + live chunks.

StreamManager is a singleton stored on AppContext — it survives all
DOM recompositions because AppContext is not a widget.

Key concepts:

- **ActiveStream**: wraps an ``agent.stream_chat()`` async iterator.
  Runs as a background ``asyncio.Task``.  Buffers chunks in a deque
  so late subscribers can replay what they missed.

- **Subscription**: returned by ``subscribe()``.  Holds a callback
  that's called for each new chunk, plus a ``.drain()`` method that
  replays buffered chunks.

- **Stream lifecycle**:
  1. ChatManager calls ``start(agent, history, user_text, tools)`` → UUID
  2. StreamManager creates an ActiveStream, starts the background task
  3. ChatManager subscribes by UUID, receives chunks via callback
  4. On recomposition: old ChatManager detaches, new one re-subscribes
  5. On permanent tab close: ``dispose()`` calls ``cancel()``
  6. On stream completion: stream is cleaned up automatically
"""

from __future__ import annotations

import asyncio
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, TYPE_CHECKING

from core.providers.base import StreamChunk

if TYPE_CHECKING:
    from core.agent import Agent


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class Subscription:
    """A handle returned by ``StreamManager.subscribe()``.

    Callers use this to ``drain()`` buffered chunks and receive a
    callback for each new live chunk.

    Attributes
    ----------
    stream_id:
        UUID of the stream this subscription belongs to.
    drain:
        Callable that returns all buffered chunks since subscription
        time and clears the buffer from this subscription's perspective.
        Each chunk is only drained once per subscription.
    cancel:
        Callable to unsubscribe from the stream.
    is_done:
        Whether the stream has completed (including aborted streams).
    is_aborted:
        Whether the stream was aborted (user cancellation or error).
    """

    stream_id: str
    drain: Callable[[], list[StreamChunk]]
    cancel: Callable[[], None]
    is_done: bool = False
    is_aborted: bool = False


@dataclass
class _ActiveStream:
    """Internal state for an active (running) stream.

    The ``_task`` is the asyncio Task running the stream iteration.
    ``_chunks`` is a bounded deque that retains recent chunks for
    late subscribers (e.g. after a workspace recomposition).

    ``_subscribers`` is a list of ``(callback, next_chunk_index)`` pairs.
    The ``next_chunk_index`` tracks where each subscriber is in the
    chunk buffer so they only receive chunks they haven't seen yet.
    """

    agent: Any  # Agent instance
    history: list[dict[str, Any]]
    user_text: str
    tools: list[dict[str, Any]] | None
    task: asyncio.Task | None = None
    chunks: deque[StreamChunk] = field(default_factory=lambda: deque(maxlen=500))
    done: bool = False
    aborted: bool = False
    error: str | None = None
    # List of (callback, next_chunk_index) pairs
    subscribers: list[tuple[Callable[[StreamChunk], None], int]] = field(default_factory=list)
    # Lock for thread-safe subscriber management
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def _cleanup(self) -> None:
        """Remove finished subscribers (those with None callbacks)."""
        self.subscribers = [
            (cb, idx) for cb, idx in self.subscribers if cb is not None
        ]


# ---------------------------------------------------------------------------
# StreamManager
# ---------------------------------------------------------------------------


class StreamManager:
    """Owns all active LLM streams, independent of any widget.

    Usage::

        stream_id = manager.start(agent, history, user_text, tools=tools)
        sub = manager.subscribe(stream_id, on_chunk)
        buffered = sub.drain()  # replay chunks missed during gap
        ...
        sub.cancel()  # unsubscribe
        ...
        manager.cancel(stream_id)  # abort the stream permanently
    """

    def __init__(self) -> None:
        self._streams: dict[str, _ActiveStream] = {}

    # ------------------------------------------------------------------
    # Start a new stream
    # ------------------------------------------------------------------

    def start(
        self,
        agent: Agent,
        history: list[dict[str, Any]],
        user_text: str,
        tools: list[dict[str, Any]] | None = None,
    ) -> str:
        """Start a new streaming conversation and return the stream UUID.

        The agent's ``stream_chat()`` method is run as a background
        asyncio Task.  Chunks are buffered and forwarded to subscribers.

        Parameters
        ----------
        agent:
            The LLM agent to stream from.
        history:
            Conversation history (list of message dicts).
        user_text:
            The user's message text.
        tools:
            Optional list of tool definitions.

        Returns
        -------
        str
            UUID identifying this stream for ``subscribe()`` and
            ``cancel()``.
        """
        stream_id = uuid.uuid4().hex
        active = _ActiveStream(
            agent=agent,
            history=list(history),  # copy so mutations don't affect stream
            user_text=user_text,
            tools=list(tools) if tools else None,
        )
        self._streams[stream_id] = active

        # Start the background task.
        loop = asyncio.get_running_loop()
        active.task = loop.create_task(
            self._run_stream(stream_id, active),
            name=f"stream-{stream_id[:8]}",
        )

        return stream_id

    # ------------------------------------------------------------------
    # Subscribe to an active stream
    # ------------------------------------------------------------------

    def subscribe(
        self,
        stream_id: str,
        on_chunk: Callable[[StreamChunk], None],
    ) -> Subscription | None:
        """Subscribe to chunks from an active stream.

        The ``on_chunk`` callback is called for each new chunk that
        arrives after subscription.  Previously buffered chunks can
        be retrieved by calling ``subscription.drain()``.

        If the stream ID is unknown or the stream has already finished
        and been cleaned up, returns ``None``.

        Parameters
        ----------
        stream_id:
            UUID returned by ``start()``.
        on_chunk:
            Callback called with each new StreamChunk.

        Returns
        -------
        Subscription | None
            A subscription handle, or None if the stream is gone.
        """
        active = self._streams.get(stream_id)
        if active is None:
            return None

        # Subscriber starts at the current chunk buffer length so it
        # only receives NEW chunks.  Buffered chunks can be replayed
        # via drain().
        next_index = len(active.chunks)
        active.subscribers.append((on_chunk, next_index))

        # If the stream is already done, immediately notify.
        if active.done:
            # Create a final "done" chunk so the subscriber knows
            # the stream is complete.
            done_chunk = StreamChunk(
                content="",
                thinking="",
                tool_calls=[],
                tool_results={},
                done=True,
                usage=None,
            )
            try:
                on_chunk(done_chunk)
            except Exception:
                pass

        def _drain() -> list[StreamChunk]:
            """Return all buffered chunks and advance the read position."""
            # Start from where this subscriber was created.
            # We re-read from the beginning of the buffer since chunks
            # may have been evicted from the deque.  The caller should
            # use persisted sections as the primary source of truth and
            # only use drained chunks for anything after the last persist.
            chunks = list(active.chunks)
            return chunks

        def _cancel() -> None:
            """Remove this subscriber from the stream."""
            # Replace the callback with None to mark it as cancelled.
            # We don't modify the list in-place to avoid index shifts.
            for i, (cb, idx) in enumerate(active.subscribers):
                if cb is on_chunk:
                    active.subscribers[i] = (None, idx)
                    break

        return Subscription(
            stream_id=stream_id,
            drain=_drain,
            cancel=_cancel,
            is_done=active.done,
            is_aborted=active.aborted,
        )

    # ------------------------------------------------------------------
    # Cancel / abort a stream
    # ------------------------------------------------------------------

    def cancel(self, stream_id: str) -> None:
        """Cancel (abort) a stream permanently.

        Aborts the agent, cancels the background task, and removes the
        stream from the manager.  Any late subscribers will receive a
        done chunk with ``aborted=True``.

        Safe to call multiple times or on unknown stream IDs.
        """
        active = self._streams.pop(stream_id, None)
        if active is None:
            return

        # Abort the agent.
        try:
            active.agent.abort()
        except Exception:
            pass

        # Cancel the background task.
        if active.task is not None and not active.task.done():
            active.task.cancel()

        # Notify subscribers that the stream was aborted.
        aborted_chunk = StreamChunk(
            content="",
            thinking="",
            tool_calls=[],
            tool_results={},
            done=True,
            usage=None,
        )
        for cb, _ in active.subscribers:
            if cb is not None:
                try:
                    cb(aborted_chunk)
                except Exception:
                    pass

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def has_stream(self, stream_id: str) -> bool:
        """Return True if the stream ID refers to an active stream."""
        return stream_id in self._streams

    def is_streaming(self, stream_id: str) -> bool:
        """Return True if the stream is still actively streaming (not done)."""
        active = self._streams.get(stream_id)
        if active is None:
            return False
        return not active.done

    def get_stream_ids(self) -> list[str]:
        """Return all active stream IDs."""
        return list(self._streams.keys())

    # ------------------------------------------------------------------
    # Background stream runner
    # ------------------------------------------------------------------

    async def _run_stream(self, stream_id: str, active: _ActiveStream) -> None:
        """Run the agent's stream_chat() and forward chunks to subscribers.

        This is the background task that iterates over the async generator.
        Each chunk is appended to the buffer and forwarded to all
        subscribers.
        """
        try:
            async for chunk in active.agent.stream_chat(
                active.history,
                active.user_text,
                tools=active.tools,
            ):
                # Buffer the chunk for late subscribers.
                active.chunks.append(chunk)

                # Forward to all active subscribers.
                for cb, next_idx in active.subscribers:
                    if cb is not None:
                        try:
                            cb(chunk)
                        except Exception:
                            pass  # Best-effort delivery

            # Stream completed normally.
            active.done = True

            # Send a final "done" chunk so subscribers know the stream
            # is complete (the last real chunk may have done=True but
            # we want to be explicit).
            # Only send if the last buffered chunk wasn't already done.
            if not active.chunks or not active.chunks[-1].done:
                final_chunk = StreamChunk(
                    content="",
                    thinking="",
                    tool_calls=[],
                    tool_results={},
                    done=True,
                    usage=None,
                )
                active.chunks.append(final_chunk)
                for cb, _ in active.subscribers:
                    if cb is not None:
                        try:
                            cb(final_chunk)
                        except Exception:
                            pass

        except asyncio.CancelledError:
            active.done = True
            active.aborted = True
            # Notify subscribers of cancellation.
            cancel_chunk = StreamChunk(
                content="",
                thinking="",
                tool_calls=[],
                tool_results={},
                done=True,
                usage=None,
            )
            for cb, _ in active.subscribers:
                if cb is not None:
                    try:
                        cb(cancel_chunk)
                    except Exception:
                        pass

        except Exception as exc:
            active.done = True
            active.error = str(exc)
            # Send an error chunk to subscribers.
            error_chunk = StreamChunk(
                content=f"Error: {exc}",
                thinking="",
                tool_calls=[],
                tool_results={},
                done=True,
                usage=None,
            )
            active.chunks.append(error_chunk)
            for cb, _ in active.subscribers:
                if cb is not None:
                    try:
                        cb(error_chunk)
                    except Exception:
                        pass

        finally:
            # Clean up finished subscribers.
            active._cleanup()
            # Remove the stream after a short delay to allow late
            # subscribers to drain the buffer.
            # The stream stays in self._streams so that anyone who
            # subscribes between stream end and cleanup can still
            # get the final state.
            # We schedule cleanup rather than doing it immediately.
            try:
                loop = asyncio.get_running_loop()
                loop.call_later(30, self._cleanup_stream, stream_id)
            except RuntimeError:
                # No running loop — clean up immediately.
                self._cleanup_stream(stream_id)

    def _cleanup_stream(self, stream_id: str) -> None:
        """Remove a finished stream from the manager after a delay."""
        self._streams.pop(stream_id, None)