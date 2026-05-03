"""Tests for the Ollama provider implementation."""

from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, patch

import pytest

from core.config import Config
from core.providers.base import ChatResponse, Message, StreamChunk, TokenUsage, ToolCall
from core.providers.ollama import OllamaProvider
from core.vault import VaultManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(
    tmp_path,
    overrides: dict | None = None,
) -> Config:
    """Create a Config with an empty (or overridden) project file in *tmp_path*."""
    path = str(tmp_path / "config.json")
    if overrides:
        import json

        tmp_path.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(overrides, f)
    return Config([path])


def _make_vault(tmp_path, unlocked: bool = True) -> VaultManager:
    """Create a VaultManager with an initialized master in *tmp_path*."""
    master_path = str(tmp_path / "vault.enc")
    mgr = VaultManager(master_path, str(tmp_path))
    mgr.initialize_master("pw")
    if not unlocked:
        mgr.lock()
    return mgr


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_creates_with_config_and_vault(self, tmp_path):
        config = _make_config(tmp_path)
        vault = _make_vault(tmp_path)
        provider = OllamaProvider(config=config, vault=vault)
        assert provider is not None

    def test_creates_with_config_only(self, tmp_path):
        config = _make_config(tmp_path)
        provider = OllamaProvider(config=config)
        assert provider is not None

    def test_creates_with_config_vault_and_model(self, tmp_path):
        config = _make_config(tmp_path)
        vault = _make_vault(tmp_path)
        provider = OllamaProvider(config=config, vault=vault, model="llama3")
        assert provider is not None


# ---------------------------------------------------------------------------
# Model resolution
# ---------------------------------------------------------------------------


class TestModelResolution:
    def test_uses_explicit_model_param(self, tmp_path):
        config = _make_config(tmp_path)
        provider = OllamaProvider(config=config, model="mistral")
        assert provider.model == "mistral"

    def test_falls_back_to_config(self, tmp_path):
        config = _make_config(tmp_path, {"session": {"model": "phi3"}})
        provider = OllamaProvider(config=config)
        assert provider.model == "phi3"

    def test_default_model_when_nothing_configured(self, tmp_path):
        config = _make_config(tmp_path)
        provider = OllamaProvider(config=config)
        assert provider.model == "llama3.2"


# ---------------------------------------------------------------------------
# Base URL resolution
# ---------------------------------------------------------------------------


class TestBaseUrlResolution:
    def test_default_base_url(self, tmp_path):
        config = _make_config(tmp_path)
        provider = OllamaProvider(config=config)
        assert provider.base_url == "http://localhost:11434"

    def test_custom_base_url_from_config(self, tmp_path):
        config = _make_config(
            tmp_path,
            {"ollama": {"base_url": "http://ollama.internal:9999"}},
        )
        provider = OllamaProvider(config=config)
        assert provider.base_url == "http://ollama.internal:9999"


# ---------------------------------------------------------------------------
# API key resolution (vault only)
# ---------------------------------------------------------------------------


class TestApiKeyResolution:
    def test_no_key_when_no_vault(self, tmp_path):
        config = _make_config(tmp_path)
        provider = OllamaProvider(config=config)
        assert provider._resolve_api_key() is None

    def test_no_key_when_credential_absent(self, tmp_path):
        config = _make_config(tmp_path)
        vault = _make_vault(tmp_path)
        provider = OllamaProvider(config=config, vault=vault)
        assert provider._resolve_api_key() is None

    def test_key_from_vault(self, tmp_path):
        config = _make_config(tmp_path)
        vault = _make_vault(tmp_path)
        vault.register_credential("ollama", "apiuser", "sk-vault-key")
        provider = OllamaProvider(config=config, vault=vault)
        assert provider._resolve_api_key() == "sk-vault-key"

    def test_locked_vault_returns_none(self, tmp_path):
        config = _make_config(tmp_path)
        vault = _make_vault(tmp_path, unlocked=False)
        # Can't register while locked, so no credential exists.
        provider = OllamaProvider(config=config, vault=vault)
        assert provider._resolve_api_key() is None

    def test_does_not_read_config_key(self, tmp_path):
        """API keys MUST NOT leak from config — vault only."""
        config = _make_config(tmp_path, {"ollama": {"api_key": "sk-config-leak"}})
        vault = _make_vault(tmp_path)
        provider = OllamaProvider(config=config, vault=vault)
        assert provider._resolve_api_key() is None

    def test_does_not_read_env_var(self, tmp_path, monkeypatch):
        """API keys MUST NOT leak from environment — vault only."""
        monkeypatch.setenv("OLLAMA_API_KEY", "sk-env-leak")
        config = _make_config(tmp_path)
        vault = _make_vault(tmp_path)
        provider = OllamaProvider(config=config, vault=vault)
        assert provider._resolve_api_key() is None


# ---------------------------------------------------------------------------
# Message mapping
# ---------------------------------------------------------------------------


class TestMessageMapping:
    def test_maps_message_to_ollama_dict(self, tmp_path):
        config = _make_config(tmp_path)
        provider = OllamaProvider(config=config)
        msg = Message(role="user", content="hello")
        result = provider._to_ollama_message(msg)
        assert result == {"role": "user", "content": "hello"}

    def test_maps_system_message(self, tmp_path):
        config = _make_config(tmp_path)
        provider = OllamaProvider(config=config)
        msg = Message(role="system", content="You are helpful.")
        result = provider._to_ollama_message(msg)
        assert result == {"role": "system", "content": "You are helpful."}

    def test_maps_multiple_messages(self, tmp_path):
        config = _make_config(tmp_path)
        provider = OllamaProvider(config=config)
        messages = [
            Message(role="system", content="Be helpful."),
            Message(role="user", content="Hi"),
        ]
        result = provider._to_ollama_messages(messages)
        assert result == [
            {"role": "system", "content": "Be helpful."},
            {"role": "user", "content": "Hi"},
        ]


# ---------------------------------------------------------------------------
# Tool mapping
# ---------------------------------------------------------------------------


class TestToolMapping:
    def test_no_tools_returns_none(self, tmp_path):
        config = _make_config(tmp_path)
        provider = OllamaProvider(config=config)
        assert provider._to_ollama_tools(None) is None

    def test_empty_tools_returns_none(self, tmp_path):
        config = _make_config(tmp_path)
        provider = OllamaProvider(config=config)
        assert provider._to_ollama_tools([]) is None

    def test_maps_tools_to_ollama_format(self, tmp_path):
        config = _make_config(tmp_path)
        provider = OllamaProvider(config=config)
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "Read a file",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"}
                        },
                        "required": ["path"],
                    },
                },
            }
        ]
        result = provider._to_ollama_tools(tools)
        assert result == tools


# ---------------------------------------------------------------------------
# Response normalisation
# ---------------------------------------------------------------------------


class TestResponseNormalisation:
    def test_normalises_simple_response(self, tmp_path):
        config = _make_config(tmp_path)
        provider = OllamaProvider(config=config)

        class FakeOllamaMsg:
            role = "assistant"
            content = "Hello, user!"

        class FakeOllamaResponse:
            message = FakeOllamaMsg()
            prompt_eval_count = 10
            eval_count = 5

        result = provider._normalise_response(FakeOllamaResponse())
        assert isinstance(result, ChatResponse)
        assert result.content == "Hello, user!"
        assert result.tool_calls is None
        assert result.thinking is None
        assert result.usage is not None
        assert result.usage.prompt_tokens == 10
        assert result.usage.completion_tokens == 5
        assert result.usage.total_tokens == 15

    def test_normalises_response_with_thinking(self, tmp_path):
        config = _make_config(tmp_path)
        provider = OllamaProvider(config=config)

        class FakeOllamaMsg:
            role = "assistant"
            content = "The answer is 42."
            thinking = "Let me calculate... 6 * 7 = 42."

        class FakeOllamaResponse:
            message = FakeOllamaMsg()
            prompt_eval_count = 30
            eval_count = 10

        result = provider._normalise_response(FakeOllamaResponse())
        assert result.content == "The answer is 42."
        assert result.thinking == "Let me calculate... 6 * 7 = 42."
        assert result.usage.prompt_tokens == 30
        assert result.usage.completion_tokens == 10

    def test_normalises_response_with_tool_calls(self, tmp_path):
        config = _make_config(tmp_path)
        provider = OllamaProvider(config=config)

        class FakeToolCallFunction:
            name = "read_file"
            arguments = {"path": "/tmp/x"}

        class FakeToolCall:
            id = "call_1"
            function = FakeToolCallFunction()

        class FakeOllamaMsg:
            role = "assistant"
            content = ""
            tool_calls = [FakeToolCall()]

        class FakeOllamaResponse:
            message = FakeOllamaMsg()
            prompt_eval_count = 20
            eval_count = 10

        result = provider._normalise_response(FakeOllamaResponse())
        assert result.content == ""
        assert result.tool_calls is not None
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].id == "call_1"
        assert result.tool_calls[0].name == "read_file"
        assert result.tool_calls[0].arguments == {"path": "/tmp/x"}

    def test_normalises_streaming_chunk(self, tmp_path):
        config = _make_config(tmp_path)
        provider = OllamaProvider(config=config)

        class FakeOllamaMsg:
            role = "assistant"
            content = "partial"

        class FakeOllamaChunk:
            message = FakeOllamaMsg()
            done = False

        result = provider._normalise_stream_chunk(FakeOllamaChunk())
        assert isinstance(result, StreamChunk)
        assert result.content == "partial"
        assert result.done is False
        assert result.usage is None
        assert result.thinking is None

    def test_normalises_stream_chunk_with_thinking(self, tmp_path):
        config = _make_config(tmp_path)
        provider = OllamaProvider(config=config)

        class FakeOllamaMsg:
            role = "assistant"
            content = ""
            thinking = "Hmm..."

        class FakeOllamaChunk:
            message = FakeOllamaMsg()
            done = False

        result = provider._normalise_stream_chunk(FakeOllamaChunk())
        assert result.content == ""
        assert result.thinking == "Hmm..."
        assert result.done is False

    def test_normalises_final_streaming_chunk(self, tmp_path):
        config = _make_config(tmp_path)
        provider = OllamaProvider(config=config)

        class FakeOllamaMsg:
            role = "assistant"
            content = "final"

        class FakeOllamaChunk:
            message = FakeOllamaMsg()
            done = True
            prompt_eval_count = 5
            eval_count = 3

        result = provider._normalise_stream_chunk(FakeOllamaChunk())
        assert result.content == "final"
        assert result.done is True
        assert result.usage is not None
        assert result.usage.prompt_tokens == 5
        assert result.usage.completion_tokens == 3


# ---------------------------------------------------------------------------
# chat() — integration with mocked AsyncClient
# ---------------------------------------------------------------------------


class FakeOllamaAsyncClient:
    """Mimics ollama.AsyncClient with canned responses."""

    def __init__(self, host=None, headers=None, chat_return=None, chat_stream_items=None):
        self._host = host
        self._headers = headers
        self._chat_return = chat_return
        self._chat_stream_items = chat_stream_items or []
        self.chat_calls: list[dict] = []

    async def chat(self, **kwargs):
        self.chat_calls.append(kwargs)
        if kwargs.get("stream"):
            async def _stream():
                for item in self._chat_stream_items:
                    yield item
            return _stream()
        else:
            return self._chat_return


class TestChatMethod:
    @pytest.mark.asyncio
    async def test_chat_returns_normalised_response(self, tmp_path):
        config = _make_config(tmp_path)

        class FakeMsg:
            role = "assistant"
            content = "Hi from Ollama!"

        class FakeResp:
            message = FakeMsg()
            prompt_eval_count = 1
            eval_count = 1

        fake_client = FakeOllamaAsyncClient(chat_return=FakeResp())

        with patch(
            "core.providers.ollama.AsyncClient", return_value=fake_client
        ):
            provider = OllamaProvider(config=config, model="llama3")
            response = await provider.chat(
                messages=[Message(role="user", content="Hello")],
                model="llama3",
            )

        assert response.content == "Hi from Ollama!"
        assert response.usage is not None

    @pytest.mark.asyncio
    async def test_chat_passes_messages_correctly(self, tmp_path):
        config = _make_config(tmp_path)

        class FakeMsg:
            role = "assistant"
            content = "ok"

        class FakeResp:
            message = FakeMsg()
            prompt_eval_count = 0
            eval_count = 0

        fake_client = FakeOllamaAsyncClient(chat_return=FakeResp())

        with patch(
            "core.providers.ollama.AsyncClient", return_value=fake_client
        ):
            provider = OllamaProvider(config=config, model="llama3")
            await provider.chat(
                messages=[
                    Message(role="system", content="Be brief."),
                    Message(role="user", content="Hello"),
                ],
                model="llama3",
            )

        call = fake_client.chat_calls[0]
        assert call["model"] == "llama3"
        assert call["messages"] == [
            {"role": "system", "content": "Be brief."},
            {"role": "user", "content": "Hello"},
        ]

    @pytest.mark.asyncio
    async def test_chat_passes_tools_when_provided(self, tmp_path):
        config = _make_config(tmp_path)

        class FakeMsg:
            role = "assistant"
            content = "ok"

        class FakeResp:
            message = FakeMsg()
            prompt_eval_count = 0
            eval_count = 0

        fake_client = FakeOllamaAsyncClient(chat_return=FakeResp())
        tools = [{"type": "function", "function": {"name": "t"}}]

        with patch(
            "core.providers.ollama.AsyncClient", return_value=fake_client
        ):
            provider = OllamaProvider(config=config, model="llama3")
            await provider.chat(
                messages=[Message(role="user", content="Hi")],
                model="llama3",
                tools=tools,
            )

        assert fake_client.chat_calls[0]["tools"] == tools

    @pytest.mark.asyncio
    async def test_chat_uses_provider_model_when_not_passed(self, tmp_path):
        config = _make_config(tmp_path)

        class FakeMsg:
            role = "assistant"
            content = "ok"

        class FakeResp:
            message = FakeMsg()
            prompt_eval_count = 0
            eval_count = 0

        fake_client = FakeOllamaAsyncClient(chat_return=FakeResp())

        with patch(
            "core.providers.ollama.AsyncClient", return_value=fake_client
        ):
            provider = OllamaProvider(config=config, model="phi3")
            await provider.chat(
                messages=[Message(role="user", content="Hi")],
            )

        assert fake_client.chat_calls[0]["model"] == "phi3"

    @pytest.mark.asyncio
    async def test_chat_passes_base_url_to_client(self, tmp_path):
        config = _make_config(
            tmp_path,
            {"ollama": {"base_url": "http://ollama.local:1234"}},
        )

        class FakeMsg:
            role = "assistant"
            content = "ok"

        class FakeResp:
            message = FakeMsg()
            prompt_eval_count = 0
            eval_count = 0

        fake_client = FakeOllamaAsyncClient(chat_return=FakeResp())

        def make_client(host=None, headers=None):
            fake_client._host = host
            fake_client._headers = headers
            return fake_client

        with patch(
            "core.providers.ollama.AsyncClient", side_effect=make_client
        ):
            provider = OllamaProvider(config=config, model="llama3")
            await provider.chat(
                messages=[Message(role="user", content="Hi")],
                model="llama3",
            )

        assert fake_client._host == "http://ollama.local:1234"

    @pytest.mark.asyncio
    async def test_chat_passes_api_key_header_from_vault(self, tmp_path):
        config = _make_config(
            tmp_path,
            {"ollama": {"base_url": "http://ollama.local:1234"}},
        )
        vault = _make_vault(tmp_path)
        vault.register_credential("ollama", "apiuser", "sk-vault-key")

        class FakeMsg:
            role = "assistant"
            content = "ok"

        class FakeResp:
            message = FakeMsg()
            prompt_eval_count = 0
            eval_count = 0

        fake_client = FakeOllamaAsyncClient(chat_return=FakeResp())

        def make_client(host=None, headers=None):
            fake_client._host = host
            fake_client._headers = headers
            return fake_client

        with patch(
            "core.providers.ollama.AsyncClient", side_effect=make_client
        ):
            provider = OllamaProvider(config=config, vault=vault, model="llama3")
            await provider.chat(
                messages=[Message(role="user", content="Hi")],
                model="llama3",
            )

        assert fake_client._headers == {"Authorization": "Bearer sk-vault-key"}


# ---------------------------------------------------------------------------
# stream_chat()
# ---------------------------------------------------------------------------


class TestStreamChat:
    @pytest.mark.asyncio
    async def test_stream_chat_yields_normalised_chunks(self, tmp_path):
        config = _make_config(tmp_path)

        class FakeMsg1:
            role = "assistant"
            content = "Hello"

        class FakeChunk1:
            message = FakeMsg1()
            done = False

        class FakeMsg2:
            role = "assistant"
            content = " world"

        class FakeChunk2:
            message = FakeMsg2()
            done = True
            prompt_eval_count = 2
            eval_count = 2

        fake_client = FakeOllamaAsyncClient(
            chat_stream_items=[FakeChunk1(), FakeChunk2()]
        )

        with patch(
            "core.providers.ollama.AsyncClient", return_value=fake_client
        ):
            provider = OllamaProvider(config=config, model="llama3")
            chunks = []
            async for chunk in provider.stream_chat(
                messages=[Message(role="user", content="Hi")],
                model="llama3",
            ):
                chunks.append(chunk)

        assert len(chunks) == 2
        assert chunks[0].content == "Hello"
        assert chunks[0].done is False
        assert chunks[1].content == " world"
        assert chunks[1].done is True
        assert chunks[1].usage is not None

    @pytest.mark.asyncio
    async def test_stream_chat_passes_correct_args(self, tmp_path):
        config = _make_config(tmp_path)

        class FakeMsg:
            role = "assistant"
            content = "x"

        class FakeChunk:
            message = FakeMsg()
            done = True
            prompt_eval_count = 0
            eval_count = 0

        fake_client = FakeOllamaAsyncClient(
            chat_stream_items=[FakeChunk()]
        )

        with patch(
            "core.providers.ollama.AsyncClient", return_value=fake_client
        ):
            provider = OllamaProvider(config=config, model="llama3")
            async for _ in provider.stream_chat(
                messages=[Message(role="user", content="Yo")],
                model="llama3",
            ):
                pass

        call = fake_client.chat_calls[0]
        assert call["model"] == "llama3"
        assert call["messages"] == [{"role": "user", "content": "Yo"}]

    @pytest.mark.asyncio
    async def test_stream_chat_returns_async_iterator(self, tmp_path):
        config = _make_config(tmp_path)
        provider = OllamaProvider(config=config, model="llama3")

        class FakeMsg:
            role = "assistant"
            content = "test"

        class FakeChunk:
            message = FakeMsg()
            done = True
            prompt_eval_count = 0
            eval_count = 0

        fake_client = FakeOllamaAsyncClient(
            chat_stream_items=[FakeChunk()]
        )

        with patch(
            "core.providers.ollama.AsyncClient", return_value=fake_client
        ):
            result = provider.stream_chat(
                messages=[Message(role="user", content="t")],
                model="llama3",
            )
            assert isinstance(result, AsyncIterator)


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    @pytest.mark.asyncio
    async def test_chat_propagates_connection_error(self, tmp_path):
        config = _make_config(tmp_path)
        provider = OllamaProvider(config=config, model="llama3")

        async def raise_error(**kwargs):
            raise ConnectionError("Ollama not running")

        with patch(
            "core.providers.ollama.AsyncClient"
        ) as mock_client:
            instance = mock_client.return_value
            instance.chat = raise_error

            with pytest.raises(ConnectionError, match="Ollama not running"):
                await provider.chat(
                    messages=[Message(role="user", content="Hi")],
                    model="llama3",
                )
