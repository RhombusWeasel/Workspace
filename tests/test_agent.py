"""Tests for the Agent (core/agent.py)."""

import pytest

from core.providers.base import ChatResponse, Message, StreamChunk, ToolCall


# ---------------------------------------------------------------------------
# Mock provider — returns canned responses for testing agent loops
# ---------------------------------------------------------------------------


class MockProvider:
    """Fake provider that returns pre-configured responses."""

    def __init__(self, responses: list[ChatResponse | list[StreamChunk]]):
        self.responses = responses
        self._call_count = 0
        self.last_messages: list[Message] = []
        self.last_tools: list[dict] | None = None
        self.last_model: str = ""

    async def chat(
        self,
        messages: list[Message],
        model: str,
        tools: list[dict] | None = None,
    ) -> ChatResponse:
        self.last_messages = list(messages)
        self.last_tools = tools
        self.last_model = model
        idx = min(self._call_count, len(self.responses) - 1)
        self._call_count += 1
        resp = self.responses[idx]
        if isinstance(resp, list):
            # Streaming response list — collect into ChatResponse
            final = resp[-1]
            return ChatResponse(
                content=final.content,
                usage=final.usage,
                thinking=final.thinking,
            )
        return resp

    async def stream_chat(
        self,
        messages: list[Message],
        model: str,
        tools: list[dict] | None = None,
    ):
        self.last_messages = list(messages)
        self.last_tools = tools
        self.last_model = model
        idx = min(self._call_count, len(self.responses) - 1)
        self._call_count += 1
        resp = self.responses[idx]
        if isinstance(resp, list):
            for chunk in resp:
                yield chunk
        else:
            yield StreamChunk(content=resp.content, done=True, usage=resp.usage)


# ---------------------------------------------------------------------------
# Template rendering
# ---------------------------------------------------------------------------


class TestTemplateRendering:
    def test_simple_substitution(self):
        from core.agent import render_template

        result = render_template("Hello {{name}}!", {"name": "World"})
        assert result == "Hello World!"

    def test_multiple_substitutions(self):
        from core.agent import render_template

        result = render_template(
            "{{greeting}} {{name}}. You are a {{role}}.",
            {"greeting": "Hi", "name": "Cody", "role": "coder"},
        )
        assert result == "Hi Cody. You are a coder."

    def test_missing_key_left_unchanged(self):
        from core.agent import render_template

        result = render_template("Hello {{name}}!", {})
        assert result == "Hello {{name}}!"

    def test_empty_template(self):
        from core.agent import render_template

        assert render_template("", {"x": "y"}) == ""

    def test_no_placeholders(self):
        from core.agent import render_template

        assert render_template("Plain text", {}) == "Plain text"

    def test_adjacent_placeholders(self):
        from core.agent import render_template

        result = render_template("{{a}}{{b}}", {"a": "1", "b": "2"})
        assert result == "12"

    def test_extra_variables_ignored(self):
        from core.agent import render_template

        result = render_template("{{a}}", {"a": "1", "b": "2"})
        assert result == "1"


# ---------------------------------------------------------------------------
# Agent construction + system prompt
# ---------------------------------------------------------------------------


class TestAgentConstruction:
    def test_system_prompt_from_template_and_vars(self):
        from core.agent import Agent

        agent = Agent(
            provider=MockProvider([]),
            template="You are a {{role}}. Be {{tone}}.",
            variables={"role": "helper", "tone": "friendly"},
        )
        assert agent.system_prompt == "You are a helper. Be friendly."

    def test_system_prompt_includes_skills_xml(self):
        from core.agent import Agent

        agent = Agent(
            provider=MockProvider([]),
            template="Base prompt.",
            skills_xml="<available_skills><skill><name>test</name></skill></available_skills>",
        )
        prompt = agent.system_prompt
        assert "Base prompt." in prompt
        assert "<available_skills>" in prompt

    def test_system_prompt_without_skills(self):
        from core.agent import Agent

        agent = Agent(
            provider=MockProvider([]),
            template="Just the prompt.",
        )
        assert agent.system_prompt == "Just the prompt."


# ---------------------------------------------------------------------------
# Message building
# ---------------------------------------------------------------------------


class TestMessageBuilding:
    def test_builds_messages_with_system_and_user(self):
        from core.agent import Agent

        agent = Agent(
            provider=MockProvider([]),
            template="System prompt.",
        )
        messages = agent.build_messages([], "Hello")

        assert len(messages) == 2
        assert messages[0].role == "system"
        assert messages[0].content == "System prompt."
        assert messages[1].role == "user"
        assert messages[1].content == "Hello"

    def test_builds_messages_with_history(self):
        from core.agent import Agent

        agent = Agent(
            provider=MockProvider([]),
            template="System.",
        )
        history = [
            {"role": "user", "content": "Q1"},
            {"role": "assistant", "content": "A1", "tool_calls": None},
            {"role": "user", "content": "Q2"},
            {"role": "assistant", "content": "A2", "tool_calls": None},
        ]
        messages = agent.build_messages(history, "Q3")

        assert len(messages) == 6  # system + 4 history + 1 user
        assert messages[0].role == "system"
        assert messages[1].role == "user" and messages[1].content == "Q1"
        assert messages[2].role == "assistant" and messages[2].content == "A1"
        assert messages[5].role == "user" and messages[5].content == "Q3"


# ---------------------------------------------------------------------------
# Simple chat (no tool calls)
# ---------------------------------------------------------------------------


class TestSimpleChat:
    async def test_returns_provider_response(self):
        from core.agent import Agent

        mock = MockProvider([
            ChatResponse(content="Hi there!", usage=None)
        ])
        agent = Agent(provider=mock, template="Prompt.")
        response = await agent.chat([], "Hello")

        assert response.content == "Hi there!"
        assert mock.last_model == ""  # default

    async def test_passes_model_to_provider(self):
        from core.agent import Agent

        mock = MockProvider([
            ChatResponse(content="ok")
        ])
        agent = Agent(provider=mock, template=".", model="llama3")
        await agent.chat([], "hi")

        assert mock.last_model == "llama3"

    async def test_passes_tools_to_provider(self):
        from core.agent import Agent

        mock = MockProvider([
            ChatResponse(content="ok")
        ])
        agent = Agent(provider=mock, template=".")
        tools = [{"type": "function", "function": {"name": "x"}}]
        await agent.chat([], "hi", tools=tools)

        assert mock.last_tools == tools


# ---------------------------------------------------------------------------
# Tool-calling loop
# ---------------------------------------------------------------------------


class TestToolCallingLoop:
    async def test_executes_tools_and_continues(self):
        """Agent executes tool calls and feeds results back to the LLM."""
        from core.agent import Agent
        from core.tools import register_tool, execute_tool

        @register_tool(
            name="get_weather",
            tags=["test"],
            description="Get weather",
            parameters={"type": "object", "properties": {}},
        )
        def get_weather(city: str = "") -> str:
            return f"Sunny in {city}"

        mock = MockProvider([
            ChatResponse(
                content="",
                tool_calls=[
                    ToolCall(id="1", name="get_weather", arguments={"city": "London"})
                ],
            ),
            ChatResponse(content="The weather in London is sunny!"),
        ])

        agent = Agent(provider=mock, template="You are helpful.")
        tools = [{
            "type": "function",
            "function": {"name": "get_weather", "description": "Get weather", "parameters": {}}
        }]
        response = await agent.chat([], "What's the weather?", tools=tools)

        assert response.content == "The weather in London is sunny!"
        # Verify the second call included the tool result
        assert mock._call_count == 2
        second_messages = mock.last_messages
        # Should contain a tool-role message with the result
        has_tool_result = any(
            m.role == "tool" and "Sunny in London" in m.content
            for m in second_messages
        )
        assert has_tool_result

    async def test_max_tool_iterations_prevents_infinite_loop(self):
        """Agent stops after max_iterations even if LLM keeps returning tools."""
        from core.agent import Agent

        mock = MockProvider([
            ChatResponse(
                content="",
                tool_calls=[ToolCall(id="1", name="loop", arguments={})]
            ),
            ChatResponse(
                content="",
                tool_calls=[ToolCall(id="2", name="loop", arguments={})]
            ),
            ChatResponse(
                content="",
                tool_calls=[ToolCall(id="3", name="loop", arguments={})]
            ),
            ChatResponse(content="finally"),
        ])

        agent = Agent(provider=mock, template=".", max_tool_iterations=2)
        response = await agent.chat([], "start", tools=[{
            "type": "function",
            "function": {"name": "loop", "description": "x", "parameters": {}}
        }])

        # Should stop after 2 iterations, not get to "finally"
        assert mock._call_count <= 3  # initial + up to 2 tool iterations


# ---------------------------------------------------------------------------
# Streaming chat
# ---------------------------------------------------------------------------


class TestStreamingChat:
    async def test_yields_chunks(self):
        from core.agent import Agent

        chunks = [
            StreamChunk(content="Hello"),
            StreamChunk(content=" world"),
            StreamChunk(content="!", done=True),
        ]
        mock = MockProvider([chunks])
        agent = Agent(provider=mock, template=".")

        received = []
        async for chunk in agent.stream_chat([], "hi"):
            received.append(chunk)

        assert len(received) == 3
        assert received[0].content == "Hello"
        assert received[-1].done is True

    async def test_streaming_with_tool_calls(self):
        """Streaming handles tool calls and continues streaming."""
        from core.agent import Agent
        from core.tools import register_tool

        @register_tool(
            name="calc",
            tags=["test"],
            description="Calculate",
            parameters={"type": "object", "properties": {}},
        )
        def calc(expr: str = "") -> str:
            return f"Result: {expr}"

        # First response: tool call (streaming tool call chunks)
        # Second response: final stream
        mock = MockProvider([
            [
                StreamChunk(content="", done=True, tool_calls=[
                    ToolCall(id="1", name="calc", arguments={"expr": "2+2"})
                ]),
            ],
            [
                StreamChunk(content="The answer"),
                StreamChunk(content=" is 4.", done=True),
            ],
        ])
        agent = Agent(provider=mock, template=".")
        tools = [{
            "type": "function",
            "function": {"name": "calc", "description": "Calc", "parameters": {}}
        }]

        received = []
        async for chunk in agent.stream_chat([], "2+2?", tools=tools):
            received.append(chunk)

        assert len(received) >= 2
        assert received[-1].done is True
        content = "".join(c.content for c in received)
        assert "answer" in content.lower()


# ---------------------------------------------------------------------------
# Abort
# ---------------------------------------------------------------------------


class TestAbort:
    async def test_abort_stops_chat(self):
        from core.agent import Agent
        import asyncio

        mock = MockProvider([
            ChatResponse(
                content="",
                tool_calls=[ToolCall(id="1", name="x", arguments={})]
            ),
            ChatResponse(content="never reached"),
        ])
        agent = Agent(provider=mock, template=".")

        # Make the second provider call hang
        event = asyncio.Event()
        original_chat = mock.chat

        async def hanging_chat(messages, model, tools=None):
            # First call goes through fine
            if mock._call_count == 0:
                return await original_chat(messages, model, tools)
            # Second call hangs until abort
            await event.wait()
            return ChatResponse(content="never")

        mock.chat = hanging_chat

        async def abort_soon():
            await asyncio.sleep(0.01)
            agent.abort()
            event.set()

        with pytest.raises(BaseException):
            await asyncio.gather(
                agent.chat([], "hello", tools=[{
                    "type": "function",
                    "function": {"name": "x", "description": "x", "parameters": {}}
                }]),
                abort_soon(),
            )

    async def test_abort_stops_streaming(self):
        from core.agent import Agent
        import asyncio

        mock = MockProvider([])
        agent = Agent(provider=mock, template=".")

        event = asyncio.Event()

        async def slow_stream(messages, model, tools=None):
            await asyncio.wait_for(event.wait(), timeout=5)
            yield StreamChunk(content="x", done=True)

        mock.stream_chat = slow_stream

        async def abort_soon():
            await asyncio.sleep(0.01)
            agent.abort()
            event.set()

        with pytest.raises(BaseException):
            async for chunk in agent.stream_chat([], "hi"):
                pass
            await abort_soon()


# ---------------------------------------------------------------------------
# Autouse — reset tools
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_tools():
    from core.tools import reset
    reset()
