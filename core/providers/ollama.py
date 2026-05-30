"""Ollama provider — implements BaseProvider for local and remote Ollama servers.

API keys are resolved **exclusively** from the password vault (managed by
:class:`VaultManager`).  Environment variables ``OLLAMA_API_KEY`` and
``OLLAMA_HOST`` are explicitly suppressed: the ollama Python library reads
them as a fallback, which is a security risk in environments where
credentials must never appear in process environment or host config.

The auth header is always sent.  For local models the Ollama server ignores
it; for remote/cloud models the Ollama server forwards it.  If the vault is
locked or has no ``ollama`` credential, no key is sent — requests that
require auth will fail at the Ollama server, which is the correct outcome.

Message redaction is handled by the :class:`~core.providers.base.BaseProvider`
base class — messages passed to :meth:`_do_chat` and :meth:`_do_stream_chat`
have already been scrubbed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ollama import AsyncClient

from core.providers.base import (
    BaseProvider,
    ChatResponse,
    Message,
    StreamChunk,
    TokenUsage,
    ToolCall,
)
from core.config import register_defaults

if TYPE_CHECKING:
    from core.config import Config
    from core.vault import VaultManager

_DEFAULT_BASE_URL = "http://localhost:11434"
_DEFAULT_MODEL = "deepseek-v4-pro:cloud"

# Register config defaults so they flow through bootstrap → Config.apply_defaults()
register_defaults({
    "session": {"provider": "ollama", "model": _DEFAULT_MODEL},
    "ollama": {"base_url": _DEFAULT_BASE_URL},
})


class OllamaProvider(BaseProvider):
    """Ollama LLM provider.

    Parameters
    ----------
    config:
        Workspace config for non-secret settings (base URL, model).
    vault:
        Vault manager for API key lookup and secret redaction.
    model:
        Explicit model override.  Falls back to ``config.session.model``
        then to the default model.
    """

    def __init__(
        self,
        config: Config,
        vault: VaultManager | None = None,
        model: str | None = None,
    ) -> None:
        super().__init__(vault=vault, config=config)
        self._app_config = config
        self.model = model or config.get("session.model") or _DEFAULT_MODEL
        self.base_url = config.get("ollama.base_url") or _DEFAULT_BASE_URL

    # ------------------------------------------------------------------
    # BaseProvider implementation (receives already-redacted messages)
    # ------------------------------------------------------------------

    async def _do_chat(
        self,
        messages: list[Message],
        model: str,
        tools: list[dict[str, Any]] | None = None,
    ) -> ChatResponse:
        client = self._make_client()
        ollama_messages = self._to_ollama_messages(messages)
        ollama_tools = self._to_ollama_tools(tools)
        response = await client.chat(
            model=model or self.model,
            messages=ollama_messages,
            tools=ollama_tools,
        )
        return self._normalise_response(response)

    async def _do_stream_chat(
        self,
        messages: list[Message],
        model: str,
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[StreamChunk]:
        client = self._make_client()
        ollama_messages = self._to_ollama_messages(messages)
        ollama_tools = self._to_ollama_tools(tools)
        async for chunk in await client.chat(
            model=model or self.model,
            messages=ollama_messages,
            tools=ollama_tools,
            stream=True,
        ):
            yield self._normalise_stream_chunk(chunk)

    # ------------------------------------------------------------------
    # API key resolution
    # ------------------------------------------------------------------

    def _resolve_api_key(self) -> str | None:
        """Return the Ollama API key from the vault, or ``None``.

        Returns ``None`` if the vault is absent, locked, or has no
        ``ollama`` credential.  The caller decides how to handle that.
        """
        if self._vault is None:
            return None
        try:
            cred = self._vault.get_credential("ollama")
        except RuntimeError:
            return None  # vault is locked
        if cred is None:
            return None
        _, password = cred
        return password

    # ------------------------------------------------------------------
    # Client construction
    # ------------------------------------------------------------------

    def _make_client(self) -> AsyncClient:
        """Build an :class:`AsyncClient` with auth from the vault.

        * Always sets an explicit ``Authorization`` header so the ollama
          library does **not** fall back to the ``OLLAMA_API_KEY``
          environment variable.  If a vault key is available it is sent;
          otherwise an empty header suppresses the env var fallback.
          The Ollama server ignores auth headers for local-only models.
        * Always passes an explicit ``host`` so the ollama library does
          **not** fall back to the ``OLLAMA_HOST`` environment variable.
        """
        key = self._resolve_api_key()
        if key:
            headers: dict[str, str] = {"Authorization": f"Bearer {key}"}
        else:
            # No key available.  Set an empty Authorization header to
            # suppress the ollama library's OLLAMA_API_KEY env var fallback.
            # Requests that require auth will fail at the Ollama server.
            headers = {"Authorization": ""}

        # Pass explicit host to suppress the OLLAMA_HOST env var fallback.
        return AsyncClient(host=self.base_url, headers=headers)

    # -- message formatting ------------------------------------------------

    @staticmethod
    def _to_ollama_message(msg: Message) -> dict[str, Any]:
        result: dict[str, Any] = {"role": msg.role, "content": msg.content}
        if msg.tool_calls:
            result["tool_calls"] = [
                {
                    "function": {
                        "name": tc.name,
                        "arguments": tc.arguments,
                    }
                }
                for tc in msg.tool_calls
            ]
        if msg.name:
            # Ollama uses `tool_name` for tool-role messages.
            result["tool_name"] = msg.name
        return result

    @classmethod
    def _to_ollama_messages(cls, messages: list[Message]) -> list[dict[str, Any]]:
        return [cls._to_ollama_message(m) for m in messages]

    # -- tool formatting ---------------------------------------------------

    @staticmethod
    def _to_ollama_tools(
        tools: list[dict[str, Any]] | None,
    ) -> list[dict[str, Any]] | None:
        if not tools:
            return None
        return tools

    # -- response normalisation --------------------------------------------

    @staticmethod
    def _normalise_response(raw: Any) -> ChatResponse:
        msg = raw.message
        content = msg.content or ""
        thinking = getattr(msg, "thinking", None) or None
        tool_calls = None
        if getattr(msg, "tool_calls", None):
            tool_calls = [
                ToolCall(
                    id=getattr(tc, "id", ""),
                    name=tc.function.name,
                    arguments=tc.function.arguments,
                )
                for tc in msg.tool_calls
            ]
        usage = TokenUsage(
            prompt_tokens=getattr(raw, "prompt_eval_count", 0) or 0,
            completion_tokens=getattr(raw, "eval_count", 0) or 0,
            total_tokens=(
                (getattr(raw, "prompt_eval_count", 0) or 0)
                + (getattr(raw, "eval_count", 0) or 0)
            ),
        )
        return ChatResponse(
            content=content,
            usage=usage,
            tool_calls=tool_calls,
            thinking=thinking,
        )

    @staticmethod
    def _normalise_stream_chunk(raw: Any) -> StreamChunk:
        msg = raw.message
        content = msg.content or ""
        thinking = getattr(msg, "thinking", None) or None
        done = bool(raw.done)
        usage = None
        tool_calls = None
        if done:
            usage = TokenUsage(
                prompt_tokens=getattr(raw, "prompt_eval_count", 0) or 0,
                completion_tokens=getattr(raw, "eval_count", 0) or 0,
                total_tokens=(
                    (getattr(raw, "prompt_eval_count", 0) or 0)
                    + (getattr(raw, "eval_count", 0) or 0)
                ),
            )
        # Extract tool calls from any chunk — they may arrive on
        # non-done chunks depending on the Ollama server version.
        if getattr(msg, "tool_calls", None):
            tool_calls = [
                ToolCall(
                    id=getattr(tc, "id", ""),
                    name=tc.function.name,
                    arguments=tc.function.arguments,
                )
                for tc in msg.tool_calls
            ]
        return StreamChunk(
            content=content,
            done=done,
            usage=usage,
            thinking=thinking,
            tool_calls=tool_calls,
        )