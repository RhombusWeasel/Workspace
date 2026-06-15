# Agent

**File:** `core/agent.py`
**Depends on:** `core.providers.base` (BaseProvider, Message, ChatResponse, StreamChunk, ToolCall), `core.tools` (execute_tool)

---

## Purpose

The `Agent` class wraps an LLM provider with a tool-calling loop.  It
handles the full cycle: build messages → send to provider → detect tool
calls → execute via `execute_tool()` → feed results back → continue until
the LLM produces a final text response.

The agent renders system prompt templates with `{{key}}` and `{{key.sub}}`
substitution and optionally injects the skills XML catalog.  Message
redaction (scrubbing secrets) is handled automatically by the
`BaseProvider` — every call to `provider.chat()` and
`provider.stream_chat()` redacts messages before they leave the process.
The Agent no longer needs its own redaction logic.

**Note:** In production use, `ChatManager` delegates streaming to
`StreamManager`, which owns the background `asyncio.Task` and persists
sections to the database.  `Agent.stream_chat()` is the low-level API;
`StreamManager.start()` is the recommended entry point.  See
[stream_manager.md](stream_manager.md) for details.

---

## Architecture

```
Agent.stream_chat(history, user_text, tools)
    │
    ▼
build_messages(history, user_text)
    │ → [system, ...history..., user]
    ▼
provider.stream_chat(messages, model, tools)
    │
    ├── Content chunks → yield to UI immediately
    │
    └── Tool calls detected → execute_tool(name, args, ctx)
         │ → append assistant + tool messages
         ▼
    provider.stream_chat(messages, model, tools)  ← loop
         │
         └── Final response (no tool calls) → done
```

---

## API

### Constructor

```python
agent = Agent(
    provider=ollama_provider,
    template="You are a helpful assistant. Project: {{project}}",
    variables={"project": "my-app"},
    model="deepseek-v4-pro:cloud",
    skills_xml=skill_manager.get_catalog_xml(),
    max_tool_iterations=10,
    ctx=app_context,
)
```

| Parameter | Type | Description |
|---|---|---|
| `provider` | `BaseProvider` | LLM backend |
| `template` | `str` | System prompt template with `{{key}}` placeholders |
| `variables` | `dict[str, str] \| None` | Values for template substitution |
| `model` | `str` | Model name passed to provider on every call |
| `skills_xml` | `str` | Optional `<available_skills>` XML appended to system prompt |
| `max_tool_iterations` | `int` | Tool-call rounds between progress checkpoints (default 10) |
| `ctx` | `AppContext \| None` | Context injected into tool calls |

### `system_prompt` (property)

The rendered system prompt — template with `{{key}}` substitution plus
optional skills XML appended.

### `build_messages(history, user_text) → list[Message]`

Build the full message list for a turn: `[system, ...history..., user]`.

History entries are dicts with keys `role`, `content`, and optionally
`tool_calls` and `name`.  Tool calls are reconstructed as `ToolCall`
objects.

### `chat(history, user_text, tools=None) → ChatResponse`

Non-streaming chat.  Handles the tool-calling loop internally and returns
the final response.  Raises `asyncio.CancelledError` if `abort()` was
called.

### `stream_chat(history, user_text, tools=None) → AsyncIterator[StreamChunk]`

Streaming chat.  Yields content chunks as they arrive for real-time UI
updates.  When tool calls are detected (on the final chunk of an
iteration), tools are executed and the loop continues.  The tool-call
chunk is yielded last so the UI can display it.

### `abort()`

Signal that any in-progress `chat()` or `stream_chat()` should be
cancelled.  The agent raises `asyncio.CancelledError` on the next check.

---

## Template Rendering

The `render_template()` function replaces `{{key}}` and `{{key.sub}}`
placeholders (dotted keys are supported):

```python
from core.agent import render_template

prompt = render_template(
    "You are {{role}}. Project: {{project}}.",
    {"role": "coding assistant", "project": "my-app"},
)
# → "You are coding assistant. Project: my-app."

prompt = render_template(
    "Skills: {{skills.catalog}}",
    {"skills.catalog": "chat, git, terminal"},
)
# → "Skills: chat, git, terminal"
```

Missing keys are left unchanged (the `{{key}}` string persists).
Dotted keys like `{{skills.catalog}}` are matched as a single key name,
not as nested object access — the variables dict must contain the exact
dotted key.

---

## Tool-Calling Loop

The loop continues until the LLM naturally produces a final text response
with no tool calls.  There is **no hard stop** — instead, the agent uses
**progress checkpoints**:

1. Send messages to the provider
2. If the response has no `tool_calls` → return (or yield final chunk)
3. If the response has `tool_calls`:
   - Append an assistant message with the tool calls
   - Execute each tool via `execute_tool(name, arguments, ctx=self._ctx)`
   - Append a `role="tool"` message with the result for each tool call
4. Go back to step 1 with the extended message list
5. **Progress checkpoint**: When `max_tool_iterations` tool-call rounds
   have been completed, the agent:
   - Injects a system message asking the LLM to summarize progress
   - Calls the provider **without tools** (forcing a text-only response)
   - Records the summary in the conversation history
   - Resets the counter and continues the loop

The `max_tool_iterations` parameter (default: from `session.max_tool_calls`
config, typically 10) controls **how many tool-call rounds happen between
checkpoints**, not the total number of tool calls allowed.  The loop only
ends when the LLM produces a final text response with no tool calls.

---

## Message Redaction

The `BaseProvider` automatically redacts secrets from messages before
sending them to the LLM.  This happens transparently — the Agent never
needs to handle redaction itself.  See [providers.md](providers.md) for
details on the redaction system.

## Tool Execution

`Agent._execute_tool_call()` handles each `ToolCall`:

1. Shows a notification in the UI: `🔧 tool_name(brief_args)`
2. Calls `execute_tool(tc.name, tc.arguments, ctx=self._ctx)`
3. If the tool is async, awaits the result
4. Returns the result as a string (or error message on exception)

The `execute_tool()` function from `core.tools` handles context injection
(based on the tool function's signature) and async dispatch.

---

## Using the Agent in a Plugin

The chat skill demonstrates creating and using an Agent:

```python
from core.agent import Agent
from core.providers.ollama import OllamaProvider

# Create the provider (config + vault from AppContext)
provider = OllamaProvider(config=ctx.config, vault=ctx.vault)

# Create the agent
agent = Agent(
    provider=provider,
    template=system_prompt_text,
    variables={"project": project_name},
    model=ctx.config.get("session.model"),
    skills_xml=ctx.skills.get_catalog_xml(),
    ctx=ctx,
)

# Stream a response
async for chunk in agent.stream_chat(history, user_message, tools=tool_list):
    if chunk.content:
        # Update the UI with the new content
        display.update(chunk.content)
    if chunk.done and chunk.usage:
        # Show token usage
        ...
```

---

## Design Decisions

1. **Agent owns the tool loop, providers don't** — Providers return tool
  calls as part of their response; the Agent handles the loop.  This
  keeps providers thin and the loop logic in one place.

2. **Streaming first** — `stream_chat()` is the primary path.  Non-streaming
  `chat()` exists for completeness but the UI is built around streaming.

3. **Template + skills XML in system prompt** — The system prompt is
  rendered once and sent as the first message.  Skills XML is appended
  so the LLM knows what skills it can activate.

4. **Progress checkpoints, not hard stops** — `max_tool_iterations` controls
  how many tool-call rounds happen between progress summaries, not a hard
  limit.  The loop only ends when the LLM produces a final text response
  with no tool calls.  This prevents infinite loops while allowing the
  agent to work through complex tasks that require many tool calls.

5. **Abort support** — `abort()` sets a flag checked at each iteration.
  Raises `asyncio.CancelledError` rather than silently stopping, so
  the caller (chat manager) can distinguish cancellation from completion.