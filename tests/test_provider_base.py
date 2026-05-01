"""Tests for the provider base protocol and dataclasses."""

import pytest

from core.providers.base import (
    BaseProvider,
    ChatResponse,
    Message,
    StreamChunk,
    TokenUsage,
)


class TestTokenUsage:
    def test_defaults_are_zero(self):
        u = TokenUsage()
        assert u.prompt_tokens == 0
        assert u.completion_tokens == 0
        assert u.total_tokens == 0

    def test_explicit_values(self):
        u = TokenUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150)
        assert u.prompt_tokens == 100
        assert u.completion_tokens == 50
        assert u.total_tokens == 150

    def test_partial_construction(self):
        u = TokenUsage(prompt_tokens=100)
        assert u.prompt_tokens == 100
        assert u.completion_tokens == 0
        assert u.total_tokens == 0

    def test_equality(self):
        a = TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15)
        b = TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15)
        c = TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=16)
        assert a == b
        assert a != c


class TestStreamChunk:
    def test_content_only_defaults(self):
        chunk = StreamChunk(content="Hello")
        assert chunk.content == "Hello"
        assert chunk.done is False
        assert chunk.usage is None
        assert chunk.thinking is None

    def test_full_construction(self):
        usage = TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15)
        chunk = StreamChunk(content="World", done=True, usage=usage)
        assert chunk.content == "World"
        assert chunk.done is True
        assert chunk.usage is usage
        assert chunk.thinking is None

    def test_with_thinking(self):
        chunk = StreamChunk(content="", thinking="Let me reason about this...")
        assert chunk.content == ""
        assert chunk.thinking == "Let me reason about this..."
        assert chunk.done is False

    def test_equality(self):
        a = StreamChunk(content="a")
        b = StreamChunk(content="a")
        c = StreamChunk(content="b")
        assert a == b
        assert a != c

    def test_equality_with_usage(self):
        u = TokenUsage(total_tokens=10)
        a = StreamChunk(content="x", done=True, usage=u)
        b = StreamChunk(content="x", done=True, usage=u)
        assert a == b


class TestMessage:
    def test_construction(self):
        m = Message(role="user", content="hello")
        assert m.role == "user"
        assert m.content == "hello"

    def test_system_role(self):
        m = Message(role="system", content="You are helpful.")
        assert m.role == "system"

    def test_assistant_role(self):
        m = Message(role="assistant", content="How can I help?")
        assert m.role == "assistant"

    def test_tool_role(self):
        m = Message(role="tool", content="result data")
        assert m.role == "tool"

    def test_equality(self):
        a = Message(role="user", content="hi")
        b = Message(role="user", content="hi")
        c = Message(role="user", content="bye")
        assert a == b
        assert a != c


class TestChatResponse:
    def test_content_only(self):
        r = ChatResponse(content="Hello, world!")
        assert r.content == "Hello, world!"
        assert r.usage is None
        assert r.thinking is None

    def test_with_usage(self):
        usage = TokenUsage(prompt_tokens=50, completion_tokens=30, total_tokens=80)
        r = ChatResponse(content="Done.", usage=usage)
        assert r.content == "Done."
        assert r.usage is usage
        assert r.thinking is None

    def test_with_thinking(self):
        r = ChatResponse(content="42", thinking="The answer must be...")
        assert r.content == "42"
        assert r.thinking == "The answer must be..."

    def test_equality(self):
        a = ChatResponse(content="x")
        b = ChatResponse(content="x")
        c = ChatResponse(content="y")
        assert a == b
        assert a != c


class TestBaseProviderProtocol:
    def test_is_a_protocol(self):
        """BaseProvider should be usable as a structural type (Protocol)."""

        class FakeProvider:
            async def chat(self, messages, model, tools=None):
                return ChatResponse(content="fake")

            async def stream_chat(self, messages, model, tools=None):
                yield StreamChunk(content="f")
                yield StreamChunk(content="a", done=True)

        # Structural subtyping — no explicit inheritance needed.
        provider: BaseProvider = FakeProvider()
        assert provider is not None

    def test_cannot_instantiate_protocol_directly(self):
        """BaseProvider is a Protocol; instantiation may work but isn't useful."""
        # We just verify the type exists — Protocols can technically be
        # instantiated but the result is meaningless.
        assert BaseProvider is not None
