"""Stream Manager -- owns the LLM stream task and writes to the database.

The streaming async iterator runs as a background ``asyncio.Task``.  Every
chunk is immediately converted into a database row (response text, thinking,
tool call, or tool result) so the chat display can poll the database instead
of receiving callbacks.

When the workspace is recomposed (split / close), the old ChatManager is
destroyed but the stream continues writing to the DB.  The new ChatManager
simply polls the same ``chat_id`` and rebuilds the display from the latest
rows.

On permanent tab close, ``ChatTabState.dispose()`` calls ``cancel()``, which
aborts the agent and cancels the background task.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any, TYPE_CHECKING

from core.providers.base import StreamChunk

if TYPE_CHECKING:
    from core.agent import Agent
    from core.database import DatabaseManager


# How often accumulated streaming content is written to the DB.
DEFAULT_FLUSH_INTERVAL = 0.25


def _format_tool_call_json(name: str, arguments: dict[str, Any], result: str | None = None) -> str:
    """Serialise a tool call as JSON for database storage."""
    data: dict[str, Any] = {"name": name, "arguments": arguments}
    if result is not None:
        data["result"] = result
    return json.dumps(data)


class StreamManager:
    """Owns active LLM streams and persists their content to the database.

    Usage::

        stream_id = manager.start(
            agent, history, user_text, tools=tools,
            db=db, chat_id=chat_id, turn_id=turn_id,
        )
        ...
        manager.cancel(stream_id)  # abort
    """

    def __init__(self) -> None:
        self._streams: dict[str, asyncio.Task] = {}
        self._metadata: dict[str, dict[str, Any]] = {}

    def start(
        self,
        agent: Agent,
        history: list[dict[str, Any]],
        user_text: str,
        *,
        tools: list[dict[str, Any]] | None = None,
        db: DatabaseManager | None = None,
        chat_id: str | None = None,
        turn_id: str | None = None,
        flush_interval: float = DEFAULT_FLUSH_INTERVAL,
    ) -> str:
        """Start a streaming conversation and return the stream UUID.

        The agent's ``stream_chat()`` iterator runs as a background task.
        Chunks are written to *db* immediately (tool calls) or flushed
        every *flush_interval* seconds (response / thinking text).
        """
        stream_id = uuid.uuid4().hex

        self._metadata[stream_id] = {
            "db": db,
            "chat_id": chat_id,
            "turn_id": turn_id,
            "flush_interval": flush_interval,
            "agent": agent,
            # Accumulators for in-progress text sections.
            "response_id": f"{turn_id}-response",
            "response_text": "",
            "response_dirty": False,
            "thinking_id": f"{turn_id}-thinking",
            "thinking_text": "",
            "thinking_dirty": False,
            # Track tool calls we have already persisted so results can be merged.
            "tool_calls": {},
        }

        loop = asyncio.get_running_loop()
        task = loop.create_task(
            self._run_stream(stream_id, agent, history, user_text, tools),
            name=f"stream-{stream_id[:8]}",
        )
        self._streams[stream_id] = task
        return stream_id

    def cancel(self, stream_id: str) -> None:
        """Abort the stream and remove it from the manager."""
        task = self._streams.pop(stream_id, None)
        meta = self._metadata.pop(stream_id, None)
        if task is None:
            return

        if not task.done():
            task.cancel()

        agent = meta.get("agent") if meta else None
        if agent is not None:
            try:
                agent.abort()
            except Exception:
                pass

    def has_stream(self, stream_id: str) -> bool:
        """Return True if *stream_id* refers to a still-running stream."""
        task = self._streams.get(stream_id)
        if task is None:
            return False
        return not task.done()

    def get_stream_ids(self) -> list[str]:
        """Return all active stream IDs."""
        return [
            sid for sid, task in self._streams.items()
            if not task.done()
        ]

    def _write_text_sections(self, stream_id: str) -> None:
        """Flush accumulated response/thinking text to the DB."""
        meta = self._metadata.get(stream_id, {})
        db: DatabaseManager | None = meta.get("db")
        chat_id: str | None = meta.get("chat_id")
        turn_id: str | None = meta.get("turn_id")
        if db is None or chat_id is None or turn_id is None:
            meta["response_dirty"] = False
            meta["thinking_dirty"] = False
            return

        if meta.get("response_dirty"):
            try:
                db.upsert_streaming_section(
                    chat_id,
                    turn_id,
                    meta["response_id"],
                    "response",
                    meta["response_text"],
                )
            except Exception:
                pass
            meta["response_dirty"] = False

        if meta.get("thinking_dirty"):
            try:
                db.upsert_streaming_section(
                    chat_id,
                    turn_id,
                    meta["thinking_id"],
                    "thinking",
                    meta["thinking_text"],
                )
            except Exception:
                pass
            meta["thinking_dirty"] = False

    async def _run_stream(
        self,
        stream_id: str,
        agent: Agent,
        history: list[dict[str, Any]],
        user_text: str,
        tools: list[dict[str, Any]] | None,
    ) -> None:
        """Iterate the LLM stream and persist every chunk to the DB."""
        meta = self._metadata.get(stream_id, {})
        db: DatabaseManager | None = meta.get("db")
        chat_id: str | None = meta.get("chat_id")
        turn_id: str | None = meta.get("turn_id")
        flush_interval: float = meta.get("flush_interval", DEFAULT_FLUSH_INTERVAL)

        last_flush = 0.0

        def _flush() -> None:
            nonlocal last_flush
            self._write_text_sections(stream_id)
            last_flush = asyncio.get_running_loop().time()

        try:
            async for chunk in agent.stream_chat(history, user_text, tools=tools):
                self._handle_chunk(stream_id, chunk)

                now = asyncio.get_running_loop().time()
                if now - last_flush >= flush_interval:
                    _flush()

            _flush()

        except asyncio.CancelledError:
            # User abort -- mark final content as aborted.
            if meta.get("response_text"):
                meta["response_text"] += "\n\n*[aborted]*"
            else:
                meta["response_text"] = "*[aborted]*"
            meta["response_dirty"] = True
            _flush()

        except Exception as exc:
            meta["response_text"] = f"Error: {exc}"
            meta["response_dirty"] = True
            _flush()

        finally:
            # Ensure a response row exists even if the stream yielded nothing.
            if db is not None and chat_id is not None and turn_id is not None:
                try:
                    db.upsert_streaming_section(
                        chat_id,
                        turn_id,
                        meta["response_id"],
                        "response",
                        meta.get("response_text", ""),
                    )
                except Exception:
                    pass

            self._streams.pop(stream_id, None)
            self._metadata.pop(stream_id, None)

    def _handle_chunk(self, stream_id: str, chunk: StreamChunk) -> None:
        """Persist a single stream chunk to the database."""
        meta = self._metadata.get(stream_id, {})
        db: DatabaseManager | None = meta.get("db")
        chat_id: str | None = meta.get("chat_id")
        turn_id: str | None = meta.get("turn_id")

        if chunk.content:
            meta["response_text"] = meta.get("response_text", "") + chunk.content
            meta["response_dirty"] = True

        if chunk.thinking:
            meta["thinking_text"] = meta.get("thinking_text", "") + chunk.thinking
            meta["thinking_dirty"] = True

        if chunk.tool_calls and db is not None and chat_id is not None and turn_id is not None:
            for tc in chunk.tool_calls:
                tc_id = tc.id or f"{turn_id}-tc-{len(meta['tool_calls'])}"
                meta["tool_calls"][tc_id] = tc
                try:
                    db.upsert_streaming_section(
                        chat_id,
                        turn_id,
                        tc_id,
                        "tool_call",
                        _format_tool_call_json(tc.name, tc.arguments),
                    )
                except Exception:
                    pass

        if chunk.tool_results and db is not None and chat_id is not None and turn_id is not None:
            for tc_id, tc in meta["tool_calls"].items():
                result = chunk.tool_results.get(tc.id, "")
                if not result:
                    continue
                try:
                    db.upsert_streaming_section(
                        chat_id,
                        turn_id,
                        tc_id,
                        "tool_call",
                        _format_tool_call_json(tc.name, tc.arguments, result=result),
                    )
                except Exception:
                    pass
