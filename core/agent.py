"""Agent — LLM conversation handler with tool-calling loop.

Wraps a :class:`~core.providers.base.BaseProvider` and manages the
tool-calling cycle: send messages → receive tool calls → execute via
``execute_tool()`` → feed results back → continue until the LLM
produces a final text response.

Supports prompt template rendering (``{{key}}`` substitution) and
optional skills XML injection.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any, AsyncIterator

from core.providers.base import (
    BaseProvider,
    ChatResponse,
    Message,
    StreamChunk,
    ToolCall,
)


# ---------------------------------------------------------------------------
# Template rendering
# ---------------------------------------------------------------------------

_PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")


def render_template(template: str, variables: dict[str, str]) -> str:
    """Replace ``{{key}}`` placeholders in *template* with values from *variables*.

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
    template:
        System prompt template with optional ``{{key}}`` placeholders.
    variables:
        Dict of ``key → value`` for template substitution.
    model:
        Model name passed to the provider on every call.
    skills_xml:
        Optional ``<available_skills>`` XML injected after the system prompt.
    max_tool_iterations:
        Maximum number of tool-calling round-trips before stopping
        (safety limit to prevent infinite loops).
    """

    def __init__(
        self,
        provider: BaseProvider,
        template: str = "",
        variables: dict[str, str] | None = None,
        model: str = "",
        skills_xml: str = "",
        max_tool_iterations: int = 10,
    ):
        self._provider = provider
        self._template = template
        self._variables = variables or {}
        self._model = model
        self._skills_xml = skills_xml
        self._max_tool_iterations = max_tool_iterations
        self._aborted = False

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

        Returns ``[system, ...history..., user]``.
        """
        messages: list[Message] = [
            Message(role="system", content=self.system_prompt)
        ]
        for entry in history:
            msg = Message(role=entry["role"], content=entry.get("content", ""))
            messages.append(msg)
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

        Handles the tool-calling loop internally.
        Raises ``asyncio.CancelledError`` if :meth:`abort` was called.
        """
        self._aborted = False

        messages = self.build_messages(history, user_text)

        for _ in range(self._max_tool_iterations + 1):
            self._check_abort()

            response = await self._provider.chat(
                messages, self._model, tools
            )

            self._check_abort()

            if not response.tool_calls:
                return response

            # Execute tools and append results
            messages.append(
                Message(role="assistant", content=response.content or "")
            )
            for tc in response.tool_calls:
                result = self._execute_tool_call(tc)
                messages.append(
                    Message(role="tool", content=result)
                )

        # Hit max iterations — return the last response
        return response

    # ------------------------------------------------------------------
    # Stream chat
    # ------------------------------------------------------------------

    async def stream_chat(
        self,
        history: list[dict[str, Any]],
        user_text: str,
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[StreamChunk]:
        """Stream a user message, yielding chunks.

        Handles the tool-calling loop internally — tool execution results
        are not streamed to the UI; only the final text response is.
        """
        self._aborted = False

        messages = self.build_messages(history, user_text)

        for iteration in range(self._max_tool_iterations + 1):
            self._check_abort()

            collected: list[StreamChunk] = []
            tool_calls: list[ToolCall] = []
            async for chunk in self._provider.stream_chat(
                messages, self._model, tools
            ):
                self._check_abort()
                collected.append(chunk)
                if chunk.tool_calls:
                    tool_calls = chunk.tool_calls

            self._check_abort()

            if not tool_calls:
                # Final response — yield collected chunks
                for chunk in collected:
                    yield chunk
                return

            # Execute tools
            assistant_content = "".join(
                c.content for c in collected if c.content
            )
            messages.append(
                Message(role="assistant", content=assistant_content)
            )
            for tc in tool_calls:
                result = self._execute_tool_call(tc)
                messages.append(Message(role="tool", content=result))

        # Hit max iterations — yield whatever we have
        for chunk in collected:
            yield chunk

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

    @staticmethod
    def _execute_tool_call(tc: ToolCall) -> str:
        from core.tools import execute_tool

        try:
            result = execute_tool(tc.name, tc.arguments)
            return str(result)
        except Exception as exc:
            return f"Error executing {tc.name}: {exc}"
