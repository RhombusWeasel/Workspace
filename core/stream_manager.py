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

**Sequential sections** -- When the LLM produces multiple thinking→response
transitions within a single turn (e.g. during tool-calling loops), each
section gets its own unique ``section_id`` and DB row.  This preserves the
sequential order: Thinking #1 → Response #1 → Tool Call #1 → Thinking #2 →
Response #2.  Transitions are detected in ``_handle_chunk`` when a thinking
chunk arrives while the current section is response (or vice versa), or when
tool calls arrive (which finalize the current text section).
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
        # Completed stream usage data — keyed by stream_id.
        # Populated when a stream finishes with a done chunk that carries usage.
        # Persisted after the stream task is cleaned up so callers can retrieve it.
        self._usage: dict[str, StreamChunk] = {}

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

        Sequential sections are tracked so that transitions (e.g. thinking
        → response → tool_call → thinking → response) create separate
        DB rows rather than merging all thinking or all response text
        into single accumulated blobs.
        """
        stream_id = uuid.uuid4().hex

        self._metadata[stream_id] = {
            "db": db,
            "chat_id": chat_id,
            "turn_id": turn_id,
            "flush_interval": flush_interval,
            "agent": agent,
            # Sequential section tracking.
            # ``sections`` is a list of completed sections, each dict with:
            #   section_id, content_type, text, dirty
            # The current in-progress section is tracked separately via
            # current_section_type / current_section_id / current_section_text.
            "sections": [],
            "section_counter": 0,
            "current_section_type": None,
            "current_section_id": None,
            "current_section_text": "",
            "current_section_dirty": False,
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
        # Clean up usage data for cancelled streams.
        self._usage.pop(stream_id, None)
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

    def get_usage(self, stream_id: str) -> StreamChunk | None:
        """Return the usage data for a completed stream, or None.

        The returned ``StreamChunk`` has its ``done`` flag set and carries
        the ``usage`` attribute with token counts.  Returns ``None`` if
        the stream is still running, was cancelled, or did not produce
        usage data.
        """
        return self._usage.get(stream_id)

    # ------------------------------------------------------------------
    # Section management helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _next_section_id(meta: dict[str, Any], content_type: str) -> str:
        """Generate the next unique section_id for the given content type."""
        meta["section_counter"] += 1
        turn_id = meta.get("turn_id") or "unknown"
        return f"{turn_id}-{content_type}-{meta['section_counter']}"

    @staticmethod
    def _finalize_current_section(meta: dict[str, Any]) -> None:
        """Move the current in-progress section to the completed sections list.

        Called when a section transition is detected (e.g. thinking→response)
        or when tool calls arrive.  If there is no current section, this is a
        no-op.
        """
        ct = meta.get("current_section_type")
        if ct is None:
            return
        meta["sections"].append({
            "section_id": meta["current_section_id"],
            "content_type": ct,
            "text": meta["current_section_text"],
            "dirty": meta.get("current_section_dirty", False),
        })
        # Mark the section as complete in the DB.
        db = meta.get("db")
        chat_id = meta.get("chat_id")
        turn_id = meta.get("turn_id")
        if db is not None and chat_id is not None and turn_id is not None:
            try:
                db.finalize_section(chat_id, turn_id, meta["sections"][-1]["section_id"])
            except Exception:
                pass
        meta["current_section_type"] = None
        meta["current_section_id"] = None
        meta["current_section_text"] = ""
        meta["current_section_dirty"] = False

    @staticmethod
    def _ensure_section(meta: dict[str, Any], content_type: str) -> str:
        """Ensure there is an active section of the given type.

        If the current section is already of the same type, reuse it.
        If the current section is of a different type (or None), finalize
        the current one and start a new section.

        Returns the section_id of the active section.
        """
        current = meta.get("current_section_type")
        if current == content_type:
            # Same type — continue accumulating.
            return meta["current_section_id"]

        # Transition — finalize the old section and start a new one.
        StreamManager._finalize_current_section(meta)

        section_id = StreamManager._next_section_id(meta, content_type)
        meta["current_section_type"] = content_type
        meta["current_section_id"] = section_id
        meta["current_section_text"] = ""
        meta["current_section_dirty"] = False
        return section_id

    def _write_text_sections(self, stream_id: str) -> None:
        """Flush all completed and current text sections to the DB.

        Writes any dirty completed sections and the current in-progress
        section (if dirty).  Marks them clean after writing.
        """
        meta = self._metadata.get(stream_id, {})
        db: DatabaseManager | None = meta.get("db")
        chat_id: str | None = meta.get("chat_id")
        turn_id: str | None = meta.get("turn_id")
        if db is None or chat_id is None or turn_id is None:
            # Mark everything clean so we don't keep retrying.
            for sec in meta.get("sections", []):
                sec["dirty"] = False
            meta["current_section_dirty"] = False
            return

        # Write completed sections.
        for sec in meta.get("sections", []):
            if sec.get("dirty"):
                try:
                    db.upsert_streaming_section(
                        chat_id,
                        turn_id,
                        sec["section_id"],
                        sec["content_type"],
                        sec["text"],
                    )
                except Exception:
                    pass
                sec["dirty"] = False

        # Write the current in-progress section.
        if meta.get("current_section_dirty") and meta.get("current_section_id"):
            try:
                db.upsert_streaming_section(
                    chat_id,
                    turn_id,
                    meta["current_section_id"],
                    meta["current_section_type"],
                    meta["current_section_text"],
                )
            except Exception:
                pass
            meta["current_section_dirty"] = False

    def _write_all_sections(self, stream_id: str) -> None:
        """Finalize the current section and write everything to the DB.

        Called at stream completion and in the finally block.
        """
        meta = self._metadata.get(stream_id, {})
        # Finalize the current section so it joins the completed list.
        self._finalize_current_section(meta)
        self._write_text_sections(stream_id)

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

            # Final flush — finalize current section and write everything.
            self._write_all_sections(stream_id)

        except asyncio.CancelledError:
            # User abort -- mark final content as aborted.
            self._finalize_current_section(meta)
            # Append [aborted] to the last section if it's a response,
            # or create a new response section.
            if meta.get("sections"):
                last_sec = meta["sections"][-1]
                if last_sec["content_type"] == "response":
                    last_sec["text"] += "\n\n*[aborted]*"
                else:
                    abort_id = self._next_section_id(meta, "response")
                    meta["sections"].append({
                        "section_id": abort_id,
                        "content_type": "response",
                        "text": "*[aborted]*",
                        "dirty": True,
                    })
            else:
                # No sections at all — create an aborted response.
                abort_id = self._next_section_id(meta, "response")
                meta["sections"].append({
                    "section_id": abort_id,
                    "content_type": "response",
                    "text": "*[aborted]*",
                    "dirty": True,
                })
            self._write_text_sections(stream_id)

        except Exception as exc:
            self._finalize_current_section(meta)
            # Create an error response section.
            error_id = self._next_section_id(meta, "response")
            meta["sections"].append({
                "section_id": error_id,
                "content_type": "response",
                "text": f"Error: {exc}",
                "dirty": True,
            })
            self._write_text_sections(stream_id)

        finally:
            # Ensure at least one response row exists even if the stream
            # yielded nothing.  If the current section is still open,
            # finalize it first.
            self._finalize_current_section(meta)

            if db is not None and chat_id is not None and turn_id is not None:
                # Write all sections one final time.
                self._write_text_sections(stream_id)

                # If no sections exist at all, create an empty response.
                if not meta.get("sections"):
                    empty_id = self._next_section_id(meta, "response")
                    try:
                        db.upsert_streaming_section(
                            chat_id,
                            turn_id,
                            empty_id,
                            "response",
                            "",
                        )
                    except Exception:
                        pass

                # Safety net: mark any remaining streaming sections
                # as complete.  Individual sections are finalized by
                # _finalize_current_section() and tool-result handlers,
                # but this catches anything that slipped through.
                try:
                    db.finalize_sections_for_turn(chat_id, turn_id)
                except Exception:
                    pass

            self._streams.pop(stream_id, None)
            self._metadata.pop(stream_id, None)

    def _handle_chunk(self, stream_id: str, chunk: StreamChunk) -> None:
        """Persist a single stream chunk to the database.

        Detects section transitions: when a thinking chunk arrives while
        the current section is a response (or vice versa), the current
        section is finalized and a new one is started.  Tool calls also
        finalize the current text section.
        """
        meta = self._metadata.get(stream_id, {})
        db: DatabaseManager | None = meta.get("db")
        chat_id: str | None = meta.get("chat_id")
        turn_id: str | None = meta.get("turn_id")

        # --- Tool calls finalize the current text section ---
        if chunk.tool_calls:
            # Finalize the current text section before persisting tool calls.
            # This ensures the tool call rows come after the text in DB order.
            self._finalize_current_section(meta)

            if db is not None and chat_id is not None and turn_id is not None:
                # Write any completed sections so they appear in the DB
                # before the tool call rows.
                self._write_text_sections(stream_id)

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

        # --- Tool results finalize the current text section ---
        if chunk.tool_results:
            self._finalize_current_section(meta)

            if db is not None and chat_id is not None and turn_id is not None:
                self._write_text_sections(stream_id)

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
                        # Tool call with result is now complete.
                        db.finalize_section(chat_id, turn_id, tc_id)
                    except Exception:
                        pass

        # --- Thinking content ---
        if chunk.thinking:
            section_id = self._ensure_section(meta, "thinking")
            meta["current_section_text"] += chunk.thinking
            meta["current_section_dirty"] = True

        # --- Response content ---
        if chunk.content:
            section_id = self._ensure_section(meta, "response")
            meta["current_section_text"] += chunk.content
            meta["current_section_dirty"] = True

        # Capture token usage on the final done chunk.
        if chunk.done:
            self._usage[stream_id] = chunk