# LLM Providers

**Files:** `core/providers/base.py` (protocol + data classes), `core/providers/ollama.py` (Ollama implementation)
**Depends on:** `core.config` (for config defaults), `core.vault` (for API key resolution)

---

## Purpose

Providers are the abstraction layer between Workspace and LLM backends.  The
`BaseProvider` protocol defines the interface every provider must satisfy.
The `Agent` class wraps a provider and handles the tool-calling loop —
providers only need to implement `chat()` and `stream_chat()`.

---

## Architecture

```
Agent
  │
  ├── provider.chat(messages, model, tools)        ← non-streaming
  └── provider.stream_chat(messages, model, tools) ← streaming
       │
       ▼
  OllamaProvider / OpenAIProvider / ...
       │
       ▼
  LLM API (HTTP)
```

---

## Core Data Types

### `Message`

```python
@dataclass
class Message:
    role: str           # "system", "user", "assistant", "tool"
    content: str
    tool_calls: list[ToolCall] | None = None
    name: str | None = None  # Tool name (for "tool" role messages)
```

### `ToolCall`

```python
@dataclass
class ToolCall:
    id: str              # Call ID from the LLM
    name: str            # Tool function name
    arguments: dict[str, Any]  # JSON arguments
```

### `ChatResponse`

```python
@dataclass
class ChatResponse:
    content: str
    usage: TokenUsage | None = None
    tool_calls: list[ToolCall] | None = None
    thinking: str | None = None  # Chain-of-thought (DeepSeek-R1, etc.)
```

### `StreamChunk`

```python
@dataclass
class StreamChunk:
    content: str
    done: bool = False
    usage: TokenUsage | None = None
    thinking: str | None = None
    tool_calls: list[ToolCall] | None = None
```

### `TokenUsage`

```python
@dataclass
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
```

---

## BaseProvider Protocol

```python
class BaseProvider(Protocol):
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
```

Every provider must implement both methods.  `tools` is the JSON Schema
function definitions list from `get_tools()`.

---

## OllamaProvider

The bundled Ollama provider demonstrates the full implementation:

```python
class OllamaProvider:
    def __init__(self, config, vault=None, model=None):
        self._config = config
        self._vault = vault
        self.model = model or config.get("session.model") or "deepseek-v4-pro:cloud"
        self.base_url = config.get("ollama.base_url") or "http://localhost:11434"
```

Key details:

- **Config defaults** are registered at import time via `register_defaults()`.
- **API key** is resolved from the vault (never from config or env vars).
- **Message normalization** converts `Message` objects to the Ollama
  client's expected format.
- **Response normalization** converts raw Ollama responses into
  `ChatResponse` / `StreamChunk` dataclasses.

---

## Creating a New Provider

To add a new LLM provider (e.g. for OpenAI, Anthropic, or a custom backend):

### 1. Create the provider module

```
core/providers/openai.py
```

### 2. Implement the protocol

```python
# core/providers/openai.py
from typing import Any, AsyncIterator
from core.providers.base import (
    BaseProvider, ChatResponse, Message, StreamChunk,
    TokenUsage, ToolCall,
)
from core.config import register_defaults

# Register defaults at import time
register_defaults({
    "openai": {"base_url": "https://api.openai.com/v1"},
})


class OpenAIProvider:
    """OpenAI LLM provider."""

    def __init__(self, config, vault=None, model=None):
        self._config = config
        self._vault = vault
        self.model = model or config.get("session.model") or "gpt-4o"
        self.base_url = config.get("openai.base_url")

    async def chat(
        self,
        messages: list[Message],
        model: str | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> ChatResponse:
        # Call the OpenAI API and return a ChatResponse
        ...

    async def stream_chat(
        self,
        messages: list[Message],
        model: str | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[StreamChunk]:
        # Call the OpenAI API in streaming mode and yield StreamChunks
        ...
```

### 3. Resolve API keys from the vault

```python
def _resolve_api_key(self) -> str | None:
    if self._vault is None or self._vault.is_locked():
        return None
    try:
        cred = self._vault.get_credential("openai")
    except RuntimeError:
        return None
    if cred is None:
        return None
    _, key = cred
    return key
```

The vault is the single source of truth for secrets.  Never read API
keys from config files or environment variables.

### 4. Register config defaults

Call `register_defaults()` at module top level so the config system
knows the defaults before any config files are loaded:

```python
register_defaults({
    "openai": {"base_url": "https://api.openai.com/v1"},
})
```

### 5. Wire into application startup

The provider is instantiated in the chat skill (or wherever the `Agent`
is created).  The config's `session.provider` key determines which
provider class to use.  Update the provider selection logic to recognize
your new provider name.

---

## Provider API Key Pattern

All providers follow the same pattern for API key resolution:

1. The provider receives a `VaultManager` instance (or `None`).
2. On each request, it calls `vault.get_credential(service_name)`.
3. If the vault is locked or the credential doesn't exist, the provider
   falls back to "no authentication" (suitable for local servers like
   Ollama) or returns an error message.
4. The credential name matches the provider (e.g. `"ollama"`, `"openai"`).

Users store API keys via the Vault panel in the sidebar, which calls:
```python
vault.register_credential("openai", "api-key", "sk-...")
```

---

## Design Decisions

1. **Protocol, not ABC** — `BaseProvider` uses Python's `Protocol` so
   providers don't need to inherit from a base class.  Duck typing works.

2. **Normalized data classes** — `ChatResponse`, `StreamChunk`, `ToolCall`,
   and `Message` insulate the rest of Workspace from provider-specific response
  formats.  Each provider does its own normalization.

3. **API keys from vault only** — No fallback to config or env vars.
  Mixing sources creates ambiguity about which value is active.

4. **Config defaults at import time** — Each provider module calls
  `register_defaults()` at the top level so defaults are available
  before the `Config` object is constructed.

5. **Tool-calling loop is in Agent, not providers** — Providers return
  tool calls as part of their response; the `Agent` class handles
  executing tools and feeding results back.  Providers are thin wrappers.