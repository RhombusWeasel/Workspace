"""Provider base protocol and shared dataclasses.

Defines the contract that every LLM provider must satisfy, plus the
normalised response types that insulate the rest of Cody from
provider-specific details.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, AsyncIterator, Protocol


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class TokenUsage:
    """Token counts for a single turn."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class ToolCall:
    """A single tool-call request emitted by the LLM."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class StreamChunk:
    """One chunk of a streaming response."""

    content: str
    done: bool = False
    usage: TokenUsage | None = None
    thinking: str | None = None
    """Reasoning / chain-of-thought emitted by the model (DeepSeek-R1, Qwen, etc.)."""
    tool_calls: list[ToolCall] | None = None
    """Tool calls emitted in this chunk (typically on the final ``done`` chunk)."""


@dataclass
class Message:
    """A chat message with role and content.

    For assistant messages that make tool calls, set ``tool_calls``.
    For tool-result messages, set ``name`` to the tool name (maps to
    Ollama's ``tool_name`` field).
    """

    role: str
    content: str
    tool_calls: list[ToolCall] | None = None
    name: str | None = None


@dataclass
class ChatResponse:
    """A complete (non-streaming) response from a provider."""

    content: str
    usage: TokenUsage | None = None
    tool_calls: list[ToolCall] | None = None
    thinking: str | None = None
    """Reasoning / chain-of-thought emitted by the model (DeepSeek-R1, Qwen, etc.)."""


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


class BaseProvider(Protocol):
    """Interface that every LLM provider must satisfy."""

    async def chat(
        self,
        messages: list[Message],
        model: str,
        tools: list[dict[str, Any]] | None = None,
    ) -> ChatResponse:
        """Send a chat request and return the complete response."""
        ...

    async def stream_chat(
        self,
        messages: list[Message],
        model: str,
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[StreamChunk]:
        """Send a chat request and stream the response as chunks."""
        ...
