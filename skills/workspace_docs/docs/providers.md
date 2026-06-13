# LLM Providers

**Files:** `core/providers/base.py` (base class + redaction + data classes), `core/providers/ollama.py` (Ollama implementation), `core/providers/registry.py` (named instance management)
**Depends on:** `core.config` (for config defaults), `core.vault` (for API key resolution + secret redaction)

---

## Purpose

Providers are the abstraction layer between Workspace and LLM backends.  The
`BaseProvider` base class defines the interface every provider must satisfy
and handles automatic message redaction.  The `Agent` class wraps a provider
and handles the tool-calling loop — providers only need to implement
`_do_chat()` and `_do_stream_chat()`.

---

## Architecture

```
Agent
  │
  ├── provider.chat(messages, model, tools)        ← non-streaming
  │   └── BaseProvider.chat() → redact → _do_chat()
  └── provider.stream_chat(messages, model, tools) ← streaming
      └── BaseProvider.stream_chat() → redact → _do_stream_chat()
         │
         ▼
  OllamaProvider / OpenAIProvider / ...
      │
      ▼
  LLM API (HTTP)
```

Messages are **automatically redacted** by `BaseProvider` before being
passed to the provider-specific `_do_chat()` / `_do_stream_chat()` methods.
Subclasses never see raw (un-redacted) messages.

---

## Provider Registry

The `ProviderRegistry` (in `core/providers/registry.py`) manages named
provider instances from config.  It lazily creates provider objects on
first access.

### Config format

```json
{
  "providers": {
    "ollama": {
      "type": "ollama",
      "model": "deepseek-v4-pro:cloud",
      "base_url": "http://localhost:11434"
    },
    "openai": {
      "type": "openai",
      "model": "gpt-4o",
      "base_url": "https://api.openai.com/v1"
    }
  },
  "session": {
    "provider": "ollama",
    "max_tool_calls": 10,
    "yolo_mode": false
  }
}
```

- `providers.<name>.type` determines which provider class to instantiate.
- `providers.<name>` is a flat dict passed as keyword arguments to the
  provider constructor (after `config` and `vault`).
- `session.provider` selects the default provider by name.

### API

| Method | Signature | Description |
|---|---|---|
| `register_type` | `(name, cls)` | Register a provider class under a type name |
| `get` | `(name) → BaseProvider` | Get or lazily create a named provider instance |
| `get_default` | `() → BaseProvider` | Get the session's default provider |
| `list_instances` | `() → list[str]` | List configured provider names |

### Bootstrap registration

During bootstrap, the Ollama provider auto-registers itself:

```python
def register(registry):
    registry.register_type("ollama", OllamaProvider)
```

Additional provider types can be registered the same way.  The registry
stores the class and calls `cls(config, vault, **kwargs)` on first access,
where `kwargs` come from the `providers.<name>` config dict (minus `type`).

### AppContext access

```python
ctx.providers.get("ollama")   # Named provider
ctx.providers.get_default()   # Default provider (from session.provider)
ctx.provider                  # Backward-compat property → ctx.providers.get_default()
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
    context_length: int | None = None
    """Maximum context window size in tokens, if known."""
```

---

## BaseProvider

`BaseProvider` is a **concrete base class** (not a `Protocol`) that
handles automatic message redaction.  Subclasses override `_do_chat()`
and `_do_stream_chat()` — they receive **already-redacted** messages
and never see raw secrets.

### Constructor

```python
class BaseProvider:
    def __init__(self, vault=None, config=None):
        self._vault = vault
        self._config = config
        self._cached_secrets: list[str] = []
```

| Parameter | Type | Description |
|---|---|---|
| `vault` | `VaultManager \| None` | Vault for reading secrets to redact |
| `config` | `Config \| None` | Config for redaction settings (enabled flag, regex patterns) |

### Public API (automatic redaction)

```python
async def chat(self, messages, model, tools=None) -> ChatResponse:
    """Send a chat request.  Messages are redacted before sending."""
    redacted = self._redact(messages)
    return await self._do_chat(redacted, model, tools)

async def stream_chat(self, messages, model, tools=None) -> AsyncIterator[StreamChunk]:
    """Stream a chat request.  Messages are redacted before sending."""
    redacted = self._redact(messages)
    async for chunk in self._do_stream_chat(redacted, model, tools):
        yield chunk
```

### Subclass interface

```python
async def _do_chat(self, messages, model, tools=None) -> ChatResponse:
    """Provider-specific implementation.  Messages have been redacted."""
    raise NotImplementedError

async def _do_stream_chat(self, messages, model, tools=None) -> AsyncIterator[StreamChunk]:
    """Provider-specific implementation.  Messages have been redacted."""
    raise NotImplementedError
```

---

## Message Redaction

`BaseProvider` automatically redacts secrets from messages before sending
them to the LLM.  This happens transparently — the `Agent` and all
callers receive un-redacted messages, and only the provider-specific
methods see scrubbed content.

### How it works

1. **Vault secrets**: When the vault is unlocked, all credential passwords
   and secure notes are collected.  When locked, previously cached secrets
   are used.
2. **Quoted-string matching**: Secrets are only redacted when they appear
   as the *complete content* between matching quote delimiters (`'secret'`,
   `"secret"`, `` `secret` ``).  This prevents false positives (e.g.
   `"admin"` won't match `get_admin_user`).
3. **Config regex patterns**: Additional patterns from `redaction.patterns`
   config are applied as plain regex substitutions, replacing all matches
   with `REDACTED`.
4. **Caching**: Secrets are cached from the vault so redaction continues
   to work even if the vault is later re-locked mid-session.

### Config keys

```json
{
  "redaction": {
    "enabled": true,
    "patterns": []
  }
}
```

| Key | Type | Default | Description |
|---|---|---|---|
| `redaction.enabled` | `bool` | `true` | Enable/disable redaction entirely |
| `redaction.patterns` | `list[str]` | `[]` | Additional regex patterns to redact |

### Example

```
# Before redaction:
password = "my-secret-key"
api_key = 'sk-abc123'

# After redaction:
password = "REDACTED"
api_key = 'REDACTED'

# Not matched (not a complete quoted string):
my_secret_key = "..."     # ← different content in quotes
```

---

## OllamaProvider

The bundled Ollama provider demonstrates the full implementation:

```python
class OllamaProvider(BaseProvider):
    def __init__(self, config, vault=None, model=None, base_url=None):
        super().__init__(vault=vault, config=config)
        self._app_config = config
        self.model = model or "deepseek-v4-pro:cloud"
        self.base_url = base_url or "http://localhost:11434"
```

Key details:

- **Extends `BaseProvider`** and overrides `_do_chat()` / `_do_stream_chat()`.
- **Config defaults** are registered at import time via `register_defaults()`.
- **API key suppression**: Always sets an `Authorization` header (with key
  if available, empty string if not) to **suppress** the `OLLAMA_API_KEY`
  environment variable fallback.  Always passes an explicit `host` to
  suppress the `OLLAMA_HOST` env var fallback.  This is a security measure
  to ensure credentials come only from the vault.
- **Message normalization** converts `Message` objects to the Ollama
  client's expected format.
- **Response normalization** converts raw Ollama responses into
  `ChatResponse` / `StreamChunk` dataclasses.
- **Context length caching**: `get_context_length()` queries the Ollama
  `show` API once per model and caches the result.

### Auto-registration

OllamaProvider includes a `register(registry)` function for the provider
registry:

```python
def register(registry):
    registry.register_type("ollama", OllamaProvider)
```

---

## Creating a New Provider

To add a new LLM provider (e.g. for OpenAI, Anthropic, or a custom backend):

### 1. Create the provider module

```
core/providers/openai.py
```

### 2. Extend BaseProvider

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
    "providers": {
        "openai": {
            "type": "openai",
            "base_url": "https://api.openai.com/v1",
        },
    },
})


class OpenAIProvider(BaseProvider):
    """OpenAI LLM provider."""

    def __init__(self, config, vault=None, model=None, base_url=None):
        super().__init__(vault=vault, config=config)
        self._app_config = config
        self.model = model or "gpt-4o"
        self.base_url = base_url or config.get("providers.openai.base_url")

    async def _do_chat(
        self,
        messages: list[Message],
        model: str | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> ChatResponse:
        # Messages have already been redacted by BaseProvider.
        # Call the OpenAI API and return a ChatResponse
        ...

    async def _do_stream_chat(
        self,
        messages: list[Message],
        model: str | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[StreamChunk]:
        # Messages have already been redacted by BaseProvider.
        # Call the OpenAI API in streaming mode and yield StreamChunks
        ...


def register(registry):
    """Register with the provider registry."""
    registry.register_type("openai", OpenAIProvider)
```

**Important**: Subclass `BaseProvider` and override `_do_chat()` and
`_do_stream_chat()`, **not** `chat()` and `stream_chat()`.  The base
class methods handle redaction before delegating to the underscore-prefixed
methods.

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
keys from config files.  Environment variables should be explicitly
suppressed (as OllamaProvider does) rather than used as fallbacks.

### 4. Register config defaults

Call `register_defaults()` at module top level so the config system
knows the defaults before any config files are loaded:

```python
register_defaults({
    "providers": {
        "openai": {
            "type": "openai",
            "base_url": "https://api.openai.com/v1",
        },
    },
})
```

### 5. Wire into application startup

Add a `register(registry)` function so the provider registry can create
instances on demand.  During bootstrap, call:

```python
from core.providers.openai import OpenAIProvider
registry.register_type("openai", OpenAIProvider)
```

Users configure providers in their workspace config:

```json
{
  "providers": {
    "openai": {
      "type": "openai",
      "model": "gpt-4o"
    }
  },
  "session": {
    "provider": "openai"
  }
}
```

---

## Provider API Key Pattern

All providers follow the same pattern for API key resolution:

1. The provider receives a `VaultManager` instance (or `None`) via
   `BaseProvider.__init__()`.
2. On each request, the provider calls `vault.get_credential(service_name)`.
3. If the vault is locked or the credential doesn't exist, the provider
   returns `None` or sets an empty auth header.
4. The credential name matches the provider (e.g. `"ollama"`, `"openai"`).

Users store API keys via the Vault panel in the sidebar, which calls:
```python
vault.register_credential("openai", "api-key", "sk-...")
```

### Environment variable suppression

Providers that wrap libraries with env-var fallbacks (like Ollama)
**must** explicitly suppress those fallbacks:

- OllamaProvider always sets an `Authorization` header (empty string if
  no key) to prevent the `OLLAMA_API_KEY` env var from being used.
- OllamaProvider always passes an explicit `host` to prevent the
  `OLLAMA_HOST` env var from being used.

This ensures credentials come exclusively from the vault.

---

## Design Decisions

1. **Base class, not Protocol** — `BaseProvider` is a concrete base class
  that handles redaction automatically.  Subclasses override `_do_chat()`
  and `_do_stream_chat()` instead of `chat()` and `stream_chat()`.

2. **Normalized data classes** — `ChatResponse`, `StreamChunk`, `ToolCall`,
  and `Message` insulate the rest of Workspace from provider-specific response
  formats.  Each provider does its own normalization.

3. **API keys from vault only** — No fallback to config or env vars.
  Mixing sources creates ambiguity about which value is active.  Env vars
  are explicitly suppressed rather than used as fallbacks.

4. **Config defaults at import time** — Each provider module calls
  `register_defaults()` at the top level so defaults are available
  before the `Config` object is constructed.

5. **Tool-calling loop is in Agent, not providers** — Providers return
  tool calls as part of their response; the `Agent` class handles
  executing tools and feeding results back.  Providers are thin wrappers.

6. **Automatic redaction in base class** — `BaseProvider.chat()` and
  `BaseProvider.stream_chat()` redact all messages before delegating to
  the subclass.  Subclasses never see un-redacted messages.

7. **Provider registry for named instances** — The `ProviderRegistry`
  lazily creates provider instances from config, allowing multiple
  provider configurations (e.g. local Ollama + remote OpenAI).