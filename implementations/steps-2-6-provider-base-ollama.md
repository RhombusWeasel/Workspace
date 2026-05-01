# Steps 2+6: Provider Base Protocol & Ollama Provider

**Branch:** `step-2-6-provider-base-ollama`  
**Date:** 2026-05-01

---

## Files Created

### `core/providers/base.py`

Pure data module with zero internal dependencies. Defines the contract every LLM
provider must satisfy plus normalised response types.

**Dataclasses:**

| Class | Fields | Notes |
|---|---|---|
| `TokenUsage` | `prompt_tokens`, `completion_tokens`, `total_tokens` | All default to `0` |
| `ToolCall` | `id`, `name`, `arguments: dict[str, Any]` | Represents an LLM-requested tool call |
| `StreamChunk` | `content`, `done=False`, `usage=None`, `thinking=None` | One chunk of a streaming response |
| `Message` | `role`, `content` | Chat message (system/user/assistant/tool) |
| `ChatResponse` | `content`, `usage=None`, `tool_calls=None`, `thinking=None` | Complete non-streaming response |

**Protocol:**

```python
class BaseProvider(Protocol):
    async def chat(self, messages: list[Message], model: str,
                   tools: list[dict[str, Any]] | None = None) -> ChatResponse: ...
    async def stream_chat(self, messages: list[Message], model: str,
                          tools: list[dict[str, Any]] | None = None) -> AsyncIterator[StreamChunk]: ...
```

Structural subtyping — providers don't need to explicitly inherit from
`BaseProvider`, they just need to match the interface.

**`thinking` field:** Both `ChatResponse` and `StreamChunk` carry an optional
`thinking` string for reasoning-capable models (DeepSeek-R1, Qwen with thinking).
Defaults to `None`. The provider normalisers extract `message.thinking` from the
raw ollama response. The agent/UI layer decides how to display it.

### `core/providers/ollama.py`

Concrete `OllamaProvider` implementing the `BaseProvider` interface.

**Constructor:**
```python
OllamaProvider(config: Config, vault: Vault | None = None, model: str | None = None)
```

- `config` — for non-secret settings (base URL, model name)
- `vault` — for API key lookup. `None` means no key (local Ollama)
- `model` — explicit override, falls back to `config.get("session.model")`, then `"llama3.2"`

**Model resolution order:** explicit param → `session.model` config → `"llama3.2"`

**Base URL resolution:** `ollama.base_url` config → `"http://localhost:11434"`

**API key resolution (vault only):**  
`_resolve_api_key()` reads `vault.get_credential("ollama")`. Returns `None` if:
- No vault provided
- Vault is locked (catches `RuntimeError`)
- No credential named `"ollama"` exists

There is **no fallback** to config files or environment variables. Secrets live in
the vault, period. `keys.py` was deleted as unnecessary indirection.

**`chat()`:** Creates `AsyncClient(host=base_url, headers=...)`, maps `Message` →
ollama message dicts, calls `client.chat(stream=False)`, normalises response.

**`stream_chat()`:** Same setup, calls `client.chat(stream=True)`, yields
normalised `StreamChunk`s. Matches real ollama API: `await client.chat(stream=True)`
returns an async generator.

**Normalisation helpers:**
- `_normalise_response(raw) → ChatResponse` — extracts content, thinking,
  tool_calls, token counts
- `_normalise_stream_chunk(raw) → StreamChunk` — same for streaming chunks;
  token counts only populated on `done=True`

### Removed: `core/providers/keys.py`

Originally planned as a unified key resolution module. Deleted because the logic
is just `vault.get_credential("ollama")` — one line per provider. A shared module
added indirection without value.

---

## Tests

### `tests/test_provider_base.py` — 20 tests

- `TestTokenUsage` (4): defaults, explicit values, partial construction, equality
- `TestStreamChunk` (5): defaults, full construction, with thinking, equality, equality with usage
- `TestMessage` (5): construction, system/assistant/tool roles, equality
- `TestChatResponse` (4): content only, with usage, with thinking, equality
- `TestBaseProviderProtocol` (2): structural subtyping, protocol existence

### `tests/test_provider_ollama.py` — 36 tests

- `TestConstruction` (3): with vault, without vault, with model
- `TestModelResolution` (3): explicit param, config fallback, default
- `TestBaseUrlResolution` (2): default, custom from config
- `TestApiKeyResolution` (6): no vault, no credential, from vault, locked vault,
  does not read config, does not read env
- `TestMessageMapping` (3): single message, system message, multiple messages
- `TestToolMapping` (3): None → None, empty → None, maps to ollama format
- `TestResponseNormalisation` (6): simple response, with thinking, with tool calls,
  streaming chunk, streaming chunk with thinking, final streaming chunk
- `TestChatMethod` (6): returns normalised response, passes messages, passes tools,
  uses default model, passes base URL, passes API key header
- `TestStreamChat` (3): yields normalised chunks, passes correct args, returns
  AsyncIterator
- `TestErrorHandling` (1): propagates connection error

---

## Design Decisions

1. **Vault-only API keys.** No config fallback, no environment variable fallback.
   Core security property — the vault is the single source of truth for secrets.

2. **No `keys.py` module.** One-line per provider. Removed to reduce indirection.

3. **`thinking` field on response types.** Reasoning models emit thinking content
   that needs to be preserved through the pipeline. Defaults to `None` for models
   that don't use it.

4. **Ollama AsyncClient API shape.** `chat(stream=True)` returns an async generator
   behind `await` — the provider matches this exactly so mocking in tests is
   straightforward.

5. **Structural subtyping via Protocol.** `OllamaProvider` doesn't inherit from
   `BaseProvider` — it just satisfies the interface. Cleaner and more Pythonic.

---

## Next Steps After This

Per the design document:

- **Step 7:** Tool Registry (`core/tools.py`) — `@register_tool()` decorator,
  tag-based grouping, enable/disable
- **Step 8:** Skill System (`core/skills.py`) — SKILL.md discovery, 3-tier,
  XML catalog
- **Step 9:** Agent (`core/agent.py`) — system prompt builder, tool-calling loop

Then the database, leader registry, slash commands, bootstrap, and UI components.
