# Step 8: Tool Registry

**Branch:** `step-8-tool-registry`  
**Date:** 2026-05-02

---

## Overview

Agent-callable tool registry using a `@register_tool()` decorator pattern.
Tools self-register at import time into module-level globals — no class wrapper.
This is the backbone of the skill extensibility model: skill authors drop a
`.py` file with `@register_tool(...)` in their skill's `tools/` directory and
it "just works."

The registry exposes tools as JSON Schema function-definition dicts suitable
for passing directly to `BaseProvider.chat()` / `stream_chat()`.

---

## Implementation

### `core/tools.py`

Zero internal dependencies — pure Python with `typing` hints only.

#### Module-level state (all private)

| Variable | Type | Purpose |
|---|---|---|
| `_tools` | `dict[str, tuple[callable, list[str], str, dict]]` | name → (fn, tags, description, parameters) |
| `_disabled_tools` | `set[str]` | individually-disabled tool names |
| `_disabled_groups` | `set[str]` | disabled tag groups |

#### Public API

```python
register_tool(*, name, tags=None, description, parameters)
    # Returns a decorator.  Raises ValueError on duplicate name.

get_tools(tags=None) -> list[dict[str, Any]]
    # Returns JSON Schema "function" definitions.
    # tags=None   → all enabled tools
    # tags="sys"  → tools tagged "sys"
    # tags=["a","b"] → tools tagged "a" OR "b" (union)

execute_tool(name, args) -> Any
    # Calls fn(**args).  Raises KeyError if not found.

disable_tool(name) / enable_tool(name)
    # Per-tool visibility toggles.  Raises KeyError if not registered.
    # Does NOT block execute_tool().

disable_group(tag) / enable_group(tag)
    # Per-group visibility toggles.  No-ops for unknown tags.

reset()
    # Clears _tools, _disabled_tools, _disabled_groups.  Test isolation.
```

#### Visibility rules (what get_tools() returns)

A tool must satisfy ALL of:
1. Exists in `_tools`
2. Not in `_disabled_tools`
3. None of its tags in `_disabled_groups`
4. Matches the tag filter (if one was provided)

Key precedence:
* **Group disable trumps individual enable** — if a tool's group is disabled, re-enabling the tool individually won't make it visible.
* **Individual disable survives group toggle** — if you disable a tool, then disable+enable its group, it stays hidden.

#### JSON Schema output shape

```python
{
    "type": "function",
    "function": {
        "name": "tool_name",
        "description": "...",
        "parameters": { ... }   # passed through verbatim
    }
}
```

This matches the format expected by Ollama's `/api/chat` and OpenAI's chat
completions API. The `parameters` dict is stored and returned as-is — no
generation or introspection of function signatures.

#### Decorator design

```python
def register_tool(*, name, tags=None, description, parameters):
    tags = list(tags) if tags else []
    def decorator(fn):
        if name in _tools:
            raise ValueError(...)
        _tools[name] = (fn, tags, description, parameters)
        return fn
    return decorator
```

The decorator registers at decoration time (import time), not at call time.
It returns the function unchanged — tools are plain Python functions.

---

## Tests

### `tests/test_tools.py` — 29 tests in 8 classes

| Class | Tests | Coverage |
|---|---|---|
| `TestRegistration` | 4 | Single + multi registration, duplicate rejection, default tags |
| `TestTagFiltering` | 5 | Single tag, union of tags, no filter, nonexistent tag → empty |
| `TestEnableDisable` | 5 | Hide/restore individual tools, unknown names raise, disabled still executable |
| `TestGroupEnableDisable` | 7 | Group hide/restore, cross-tag isolation, precedence rules, unknown groups no-op |
| `TestExecution` | 5 | Calls fn with **args, missing args raise TypeError, unknown raises KeyError, disabled/group-disabled still work |
| `TestOutputFormat` | 1 | Verifies exact JSON Schema shape |
| `TestReset` | 3 | Clears everything, allows re-registration |

All tests use the `_reset_registry` autouse fixture which calls `reset()` before
every test — guaranteeing complete isolation regardless of test order.

Helper functions (`_echo`, `_add`, `_noop`) and parameter schemas (`_SIMPLE_PARAMS`,
`_ADD_PARAMS`, `_NOOP_PARAMS`) are defined at module level, but the `reset()`
fixture ensures no stale registrations from previous tests leak in.

---

## Design Decisions

1. **No class wrapper.** Module globals only, per §6.1 of the design document.
   A class would require every tool author to pass a registry instance around —
   the module-level decorator pattern is frictionless for skill authors.

2. **execute_tool ignores enable/disable.** The LLM may call a tool that was
   disabled mid-conversation. Disable only controls visibility in `get_tools()`
   (what gets sent to the provider as available tools). If the LLM already
   knows about a tool and calls it, we execute it.

3. **Group disable is a set, not a counter.** No refcounting. `disable_group("x")`
   twice is the same as calling it once. `enable_group("x")` clears it completely.

4. **No function introspection.** The `parameters` dict is provided explicitly
   in the decorator call. No `inspect.signature()` or docstring parsing. This
   keeps the registry simple and gives tool authors full control over the schema
   the LLM sees.

5. **Stored tags are a copy.** `tags = list(tags) if tags else []` — prevents
   external mutation of a shared list from affecting the registry.

---

## Usage Pattern (for future agents building tools or skills)

```python
# In a tool file (e.g., tools/read_file.py):
from core.tools import register_tool

@register_tool(
    name="read_file",
    tags=["system"],
    description="Read the contents of a file from the filesystem.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Absolute or relative path."}
        },
        "required": ["path"],
    },
)
def read_file(path: str) -> str:
    with open(path) as f:
        return f.read()
```

```python
# In the agent, before calling the provider:
tools = get_tools(["system", "skills"])  # only system + skill tools
response = await provider.chat(messages, model, tools=tools)
```

```python
# Executing a tool call from the LLM:
result = execute_tool(tool_call.name, tool_call.arguments)
```

```python
# In tests (or when reloading skills):
from core.tools import reset
reset()  # clean slate
# re-import skill tool modules to re-register
```
