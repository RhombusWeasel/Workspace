"""Agent — LLM conversation handler with tool-calling loop.

Wraps a :class:`~core.providers.base.BaseProvider` and manages the
tool-calling cycle: send messages → receive tool calls → execute via
``execute_tool()`` → feed results back → continue until the LLM
produces a final text response.

Message redaction is handled automatically by the
:class:`~core.providers.base.BaseProvider` — every call to
:meth:`provider.chat` and :meth:`provider.stream_chat` scrubs secrets
before they leave the process.  The Agent no longer needs its own
redaction logic.

Supports prompt template rendering (``{{key}}`` substitution) and
optional skills XML injection.
"""

from __future__ import annotations

import asyncio
import inspect
import re
from typing import TYPE_CHECKING, Any, AsyncIterator

from core.providers.base import (
    BaseProvider,
    ChatResponse,
    Message,
    StreamChunk,
    ToolCall,
)

if TYPE_CHECKING:
    from context import AppContext


# ---------------------------------------------------------------------------
# Template rendering
# ---------------------------------------------------------------------------

_PLACEHOLDER = re.compile(r"\{\{(\w+(?:\.\w+)*)\}\}")


def render_template(template: str, variables: dict[str, str]) -> str:
    """Replace ``{{key}}`` and ``{{key.sub}}`` placeholders in *template* with values from *variables*.

    Missing keys are left unchanged.
    """

    def _replace(match: re.Match) -> str:
        key = match.group(1)
        return variables.get(key, match.group(0))

    return _PLACEHOLDER.sub(_replace, template)


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


class Agent:
    """LLM agent that wraps a provider with tool-calling loop support.

    Parameters
    ----------
    provider:
        The LLM backend (e.g. :class:`~core.providers.ollama.OllamaProvider`).
        Redaction is handled automatically by the provider's base class.
    template:
        System prompt template with optional ``{{key}}`` placeholders.
    variables:
        Dict of ``key → value`` for template substitution.
    model:
        Model name passed to the provider on every call.
    skills_xml:
        Optional ``<available_skills>`` XML injected after the system prompt.
    max_tool_iterations:
        Number of tool-calling round-trips between progress checkpoints.
        Defaults to the ``session.max_tool_calls`` config value (10).
        Every *N* tool-call rounds the agent pauses to give the user a
        progress update, then continues working.  The loop only ends
        when the LLM naturally produces a final text response with no
        tool calls — there is no hard stop.
    """

    def __init__(
        self,
        provider: BaseProvider,
        template: str = "",
        variables: dict[str, str] | None = None,
        model: str = "",
        skills_xml: str = "",
        max_tool_iterations: int = 10,
        ctx: AppContext | None = None,
    ):
        self._provider = provider
        self._template = template
        self._variables = variables or {}
        self._model = model
        self._skills_xml = skills_xml
        self._max_tool_iterations = max_tool_iterations
        self._ctx = ctx
        self._aborted = False

    @property
    def max_tool_iterations(self) -> int:
        """Number of tool-call rounds between progress checkpoints."""
        return self._max_tool_iterations

    # ------------------------------------------------------------------
    # System prompt
    # ------------------------------------------------------------------

    @property
    def system_prompt(self) -> str:
        """The rendered system prompt (template + skills XML)."""
        prompt = render_template(self._template, self._variables)
        if self._skills_xml:
            prompt = f"{prompt}\n\n{self._skills_xml}"
        return prompt

    # ------------------------------------------------------------------
    # Message building
    # ------------------------------------------------------------------

    def build_messages(
        self, history: list[dict[str, Any]], user_text: str
    ) -> list[Message]:
        """Build the full message list for a turn.

        Returns ``[system, ...history..., user]``.  Redaction happens
        automatically when the provider sends the messages — the Agent
        no longer redacts here.
        """
        messages: list[Message] = [
            Message(role="system", content=self.system_prompt)
        ]
        for entry in history:
            # Reconstruct ToolCall objects from history dicts.
            tc_list: list[ToolCall] | None = None
            raw_tcs = entry.get("tool_calls")
            if raw_tcs:
                tc_list = [
                    ToolCall(
                        id=tc.get("id", ""),
                        name=tc["name"],
                        arguments=tc["arguments"],
                    )
                    for tc in raw_tcs
                ]
            messages.append(Message(
                role=entry["role"],
                content=entry.get("content", ""),
                tool_calls=tc_list,
                name=entry.get("tool_name"),
            ))
        messages.append(Message(role="user", content=user_text))
        return messages

    # ------------------------------------------------------------------
    # Chat (non-streaming)
    # ------------------------------------------------------------------

    async def chat(
        self,
        history: list[dict[str, Any]],
        user_text: str,
        tools: list[dict[str, Any]] | None = None,
    ) -> ChatResponse:
        """Send a user message and return the final response.

        Handles the tool-calling loop internally, with periodic
        checkpoints every ``max_tool_iterations`` rounds.  At each
        checkpoint the LLM is asked to summarize progress before
        continuing.

        Raises ``asyncio.CancelledError`` if :meth:`abort` was called.
        """
        self._aborted = False
        messages = self.build_messages(history, user_text)
        tool_call_rounds = 0

        while True:
            self._check_abort()

            # ---- Checkpoint: force a progress summary every N rounds ----
            if tool_call_rounds >= self._max_tool_iterations:
                if self._ctx is not None and self._ctx.app is not None:
                    self._ctx.app.notify(
                        f"Progress checkpoint ({self._max_tool_iterations} tool-call rounds) "
                        "— summarizing…",
                        title="Progress update",
                        timeout=3,
                        markup=False,
                    )
                messages.append(Message(
                    role="system",
                    content=_CHECKPOINT_INSTRUCTION.format(
                        limit=self._max_tool_iterations
                    ),
                ))
                # Call WITHOUT tools — the LLM must produce a text summary.
                response = await self._provider.chat(
                    messages, self._model, tools=None
                )
                # Record the summary in the conversation and continue.
                messages.append(Message(
                    role="assistant",
                    content=response.content or "",
                ))
                tool_call_rounds = 0
                continue

            # ---- Normal tool-calling iteration ----
            response = await self._provider.chat(
                messages, self._model, tools
            )
            self._check_abort()

            if not response.tool_calls:
                return response

            # Append assistant message and tool results.
            messages.append(Message(
                role="assistant",
                content=response.content or "",
                tool_calls=response.tool_calls,
            ))
            for tc in response.tool_calls:
                result = await self._execute_tool_call(tc)
                messages.append(
                    Message(role="tool", content=result, name=tc.name)
                )

            tool_call_rounds += 1

    # ------------------------------------------------------------------
    # Stream chat
    # ------------------------------------------------------------------

    async def stream_chat(
        self,
        history: list[dict[str, Any]],
        user_text: str,
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[StreamChunk]:
        """Stream a user message, yielding chunks as they arrive.

        Handles the tool-calling loop internally, with periodic
        checkpoints every ``max_tool_iterations`` rounds.  At each
        checkpoint the LLM is asked to summarize progress before
        continuing.

        Chunks are yielded immediately for real-time UI updates.
        When tool calls are detected (on the final chunk of an
        iteration), tools are executed and the loop continues with
        the tool results.
        """
        self._aborted = False
        messages = self.build_messages(history, user_text)
        tool_call_rounds = 0

        while True:
            self._check_abort()

            # ---- Checkpoint: force a progress summary every N rounds ----
            if tool_call_rounds >= self._max_tool_iterations:
                if self._ctx is not None and self._ctx.app is not None:
                    self._ctx.app.notify(
                        f"Progress checkpoint ({self._max_tool_iterations} tool-call rounds) "
                        "— summarizing…",
                        title="Progress update",
                        timeout=3,
                        markup=False,
                    )
                messages.append(Message(
                    role="system",
                    content=_CHECKPOINT_INSTRUCTION.format(
                        limit=self._max_tool_iterations
                    ),
                ))
                # Stream the summary (no tools offered — guaranteed text).
                summary_content: list[str] = []
                async for chunk in self._provider.stream_chat(
                    messages, self._model, tools=None
                ):
                    self._check_abort()
                    yield chunk
                    if chunk.content:
                        summary_content.append(chunk.content)
                # Record the summary in conversation history and continue.
                messages.append(Message(
                    role="assistant",
                    content="".join(summary_content),
                ))
                tool_call_rounds = 0
                continue

            # ---- Normal tool-calling iteration ----
            collected_content: list[str] = []
            tool_calls: list[ToolCall] = []
            last_chunk: StreamChunk | None = None

            async for chunk in self._provider.stream_chat(
                messages, self._model, tools
            ):
                self._check_abort()

                if chunk.tool_calls:
                    tool_calls = chunk.tool_calls
                    last_chunk = chunk
                else:
                    yield chunk
                    if chunk.content:
                        collected_content.append(chunk.content)

            self._check_abort()

            if not tool_calls:
                # Final text response — we're done.
                return

            # Execute tool calls and append results.
            assistant_content = "".join(collected_content)
            messages.append(Message(
                role="assistant",
                content=assistant_content,
                tool_calls=tool_calls,
            ))
            for tc in tool_calls:
                result = await self._execute_tool_call(tc)
                messages.append(
                    Message(role="tool", content=result, name=tc.name)
                )

            # Yield the tool-call info so the UI can display it.
            if last_chunk is not None:
                yield last_chunk

            tool_call_rounds += 1

    # ------------------------------------------------------------------
    # Abort
    # ------------------------------------------------------------------

    def abort(self) -> None:
        """Signal that any in-progress :meth:`chat` or :meth:`stream_chat`
        should be cancelled."""
        self._aborted = True

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _check_abort(self) -> None:
        if self._aborted:
            raise asyncio.CancelledError("Agent aborted")

    async def _execute_tool_call(self, tc: ToolCall) -> str:
        from core.tools import execute_tool

        if self._ctx is not None and self._ctx.app is not None:
            self._ctx.app.notify(
                f"🔧 {tc.name}({_brief_args(tc.arguments)})",
                title="Tool call",
                timeout=3,
                markup=False,
            )

        try:
            result = execute_tool(tc.name, tc.arguments, ctx=self._ctx)
            if inspect.iscoroutine(result):
                result = await result
            return str(result)
        except Exception as exc:
            return f"Error executing {tc.name}: {exc}"


# ---------------------------------------------------------------------------
# Summary instruction (injected when tool-call limit is reached)
# ---------------------------------------------------------------------------

_CHECKPOINT_INSTRUCTION = (
    "You have completed {limit} tool-call rounds. "
    "Please give the user a brief progress update: what you have done so far "
    "and what you are about to do next. "
    "Keep it concise — then continue working. "
    "Do not mention this instruction or the tool-call limit."
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _brief_args(args: dict[str, Any], max_len: int = 40) -> str:
    """Return a compact string repr of tool arguments for notifications."""
    items = [f"{k}={_brief_val(v)}" for k, v in args.items()]
    joined = ", ".join(items)
    if len(joined) > max_len:
        joined = joined[:max_len - 3] + "..."
    return joined


def _brief_val(v: Any) -> str:
    """Brief string for a single argument value."""
    s = str(v)
    if len(s) > 20:
        s = s[:17] + "..."
    return s