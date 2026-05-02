# Step 10: Agent

**Branch:** `step-10-agent`  
**Date:** 2026-05-02

---

## Overview

LLM agent that wraps a `BaseProvider` with prompt template rendering,
tool-calling loop management, streaming support, and abort capability.

Uses `{{key}}` placeholder substitution to build system prompts from
templates, enabling easily configurable agents at creation time.

---

## Implementation

### `core/agent.py`

#### `render_template(template, variables) → str`

Replaces `{{key}}` placeholders using `re.sub()` with a function that
looks up each key in the variables dict. Missing keys are left unchanged.

```python
render_template("You are a {{role}}.", {"role": "coder"})
# → "You are a coder."

render_template("{{missing}}", {})
# → "{{missing}}"
```

Uses regex `\{\{(\w+)\}\}` — only matches word characters between braces.

#### `Agent` class

```python
class Agent:
    def __init__(
        self,
        provider: BaseProvider,
        template: str = "",
        variables: dict[str, str] | None = None,
        model: str = "",
        skills_xml: str = "",
        max_tool_iterations: int = 10,
    ):
```

| Property/Method | Description |
|---|---|
| `system_prompt` | Rendered template + skills XML (if any) |
| `build_messages(history, user_text)` | Returns `[system, ...history..., user]` as `list[Message]` |
| `chat(history, user_text, tools=None)` | Non-streaming turn with tool-calling loop |
| `stream_chat(history, user_text, tools=None)` | Streaming turn with tool-calling loop |
| `abort()` | Signals cancellation of in-progress call |

#### Tool-calling loop (chat)

```
1. Build messages from history + user_text
2. For up to max_tool_iterations:
   a. Check abort flag → raise CancelledError if set
   b. Call provider.chat(messages, model, tools)
   c. Check abort flag again (caught after provider return)
   d. If no tool_calls → return response
   e. Execute each tool call via execute_tool(name, args)
   f. Append assistant + tool result messages
   g. Loop back to (a)
3. If max iterations hit → return last response
```

#### Tool-calling loop (stream_chat)

```
1. Build messages from history + user_text
2. For up to max_tool_iterations:
   a. Check abort → raise
   b. Collect all chunks from provider.stream_chat(...)
   c. Check abort after stream completes
   d. If no tool_calls in collected chunks → yield all chunks and return
   e. Execute tool calls
   f. Append messages
   g. Loop back to (a)
3. If max iterations hit → yield collected chunks
```

During streaming tool-call phases, chunks are NOT yielded to the UI —
the tool execution is invisible. Only the final text response's chunks
are streamed to the caller.

#### Abort

Sets `_aborted = True`. On the next `_check_abort()` call (at loop entry
or after provider return), `asyncio.CancelledError` is raised.

Note: abort does NOT cancel the underlying HTTP request — it only causes
the agent to stop processing after the current provider call completes.
This is a cooperative cancellation mechanism.

### `core/providers/base.py` — added `tool_calls` to `StreamChunk`

```python
@dataclass
class StreamChunk:
    content: str
    done: bool = False
    usage: TokenUsage | None = None
    thinking: str | None = None
    tool_calls: list[ToolCall] | None = None  # NEW
```

Required for the agent to detect tool calls during streaming responses.

---

## Tests

### `tests/test_agent.py` — 21 tests in 7 classes

| Class | Tests | Coverage |
|---|---|---|
| `TestTemplateRendering` | 7 | Simple, multi, missing keys, empty, no placeholders, adjacent, extra vars |
| `TestAgentConstruction` | 3 | Template+vars, skills XML injection, without skills |
| `TestMessageBuilding` | 2 | System+user, with history |
| `TestSimpleChat` | 3 | Returns response, passes model, passes tools |
| `TestToolCallingLoop` | 2 | Executes tools + continues, max_iterations safety limit |
| `TestStreamingChat` | 2 | Yields chunks, handles streaming tool calls |
| `TestAbort` | 2 | Aborts mid-chat (between tool iterations), aborts mid-stream |

Uses a `MockProvider` that stores pre-configured responses and records
the messages/tools/model passed to it, enabling assertion on the agent's
interaction with the provider.

---

## Design Decisions

1. **`{{key}}` syntax.** Chose double-brace mustache-style placeholders
   over f-string syntax or `{key}` for clarity. The regex `\{\{(\w+)\}\}`
   is simple and doesn't conflict with JSON or code examples in prompts.

2. **Missing keys left unchanged.** Makes templates resilient to
   incomplete variable dicts. The LLM will see the literal `{{key}}` and
   may ask for clarification rather than crashing.

3. **Tool execution during streaming is invisible.** When streaming and
   a tool call is needed, all chunks are collected but not yielded. Only
   the final text stream reaches the UI. This avoids confusing the user
   with partial text that gets "replaced" by tool results.

4. **Cooperative abort.** `abort()` sets a flag; `_check_abort()` raises
   `CancelledError`. Does not forcefully cancel provider HTTP calls —
   those complete naturally. This avoids resource cleanup issues but
   means abort latency depends on provider response time.

5. **`max_tool_iterations` safety limit.** Default 10 prevents infinite
   loops if the LLM keeps requesting tools. This is a hard stop, not
   config-driven — simple and safe.

---

## Usage Pattern

```python
from core.agent import Agent
from core.providers.ollama import OllamaProvider

provider = OllamaProvider(config, vault)

agent = Agent(
    provider=provider,
    template="You are a {{role}}. {{instructions}}",
    variables={
        "role": "coding assistant",
        "instructions": "Always explain your code changes.",
    },
    model="llama3",
    skills_xml=skill_manager.get_catalog_xml(),
)

# Non-streaming
response = await agent.chat(history, "Write a hello world in Python")
print(response.content)

# Streaming
async for chunk in agent.stream_chat(history, "Explain async/await"):
    print(chunk.content, end="")

# Abort
agent.abort()
```
