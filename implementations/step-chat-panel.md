# Chat Panel — Streaming Conversation in Tree Widget

**Branch:** `step-chat-panel`  
**Date:** 2026-05-02

---

## Overview

Chat panel registered as a right sidebar tab using the Tree widget for
collapsible message display. Integrates with the Agent for streaming
LLM conversations.

---

## Implementation

### `ui/sidebar/panels/chat_panel.py`

#### Registration

```python
@register_sidebar_tab(name="chat", icon="\uf4ad", side="right", tooltip="Chat")
class ChatPanel(Container):
```

#### Layout

```
┌──────────────────┐
│ Conversation     │  ← Tree widget (expand/collapse messages)
│ ├─ You: "Hi"    │
│ ├─ Assistant: … │  ← streams in realtime
│ │  ├─ Thinking  │  ← appears as agent thinks
│ │  └─ Tool: …   │  ← tool calls logged
│ └─ ...          │
├──────────────────┤
│ Type a message…  │  ← Input (dock: bottom)
└──────────────────┘
```

#### Public API

| Method | Purpose |
|---|---|
| `set_agent(agent)` | Bind an Agent for conversation |
| `set_tools(tools)` | Tool definitions to pass to agent |
| `add_message(role, content)` | Add top-level message node, returns node_id |
| `add_thought(thought)` | Add/update thinking child under last assistant |
| `add_tool_result(name, args, result)` | Add tool-call child under last assistant |
| `update_response_text(text)` | Update last assistant label in-place (streaming) |
| `get_input()` | Access the Input widget |

#### Streaming flow (`on_input_submitted`)

```
1. User types message → adds user node + history entry
2. Creates empty assistant placeholder ("…")
3. agent.stream_chat(history, user_text, tools) →
   For each chunk:
   ├─ chunk.thinking → add_thought() (updates if same thought)
   ├─ chunk.tool_calls → add_tool_result() for each
   └─ chunk.content → accumulated + update_response_text()
4. On completion → finalize history
5. Refocus input
```

Thinking nodes use `update_node_label` for streaming accumulation
(avoids creating a new node per chunk). Response text updates the
assistant node label in-place via the same mechanism.

### `ui/tree/tree.py` — added `update_node_label()`

```python
def update_node_label(self, node_id: str, label: str) -> None:
    """Update a node's display label without rebuilding the entire tree."""
    self._node_map[node_id].label = label
    for row in self.query("TreeRow"):
        if row.node.id == node_id:
            row.refresh(layout=True)
```

### `main.py` — agent wiring

In `CodyApp.on_mount()`, finds the ChatPanel in the right sidebar and:
- Creates an `OllamaProvider` from config
- Creates an `Agent` with template + skills XML
- Calls `chat_panel.set_agent(agent)` and `set_tools(get_tools())`

---

## Tests

### `tests/test_chat_panel.py` — 6 tests

| Test | Coverage |
|---|---|
| `test_has_input_and_tree` | Widgets rendered |
| `test_add_user_message` | User node appears in tree |
| `test_add_assistant_message` | Assistant node appears |
| `test_add_thought` | Thinking child under assistant |
| `test_add_tool_result` | Tool child under assistant |
| `test_message_tree_structure` | Full conversation with all node types |

Uses `ChatPanelTestApp` with Textual pilot.

---

## Design Decisions

1. **Thinking is streamed but not added to agent history.** The Agent
   passes `chunk.thinking` through to the UI but never appends it to
   the message list sent back to the LLM. This matches modern reasoning
   model behavior (DeepSeek-R1, Qwen) where thinking is ephemeral.

2. **Tree for message display.** Collapsible nodes let users hide/show
   thinking and tool calls. Unlike a flat chat log, the tree structure
   groups related content (response → thinking + tools).

3. **In-place label updates for streaming.** `update_node_label()` avoids
   full tree rebuilds during streaming, preventing flicker while text
   accumulates.

4. **Agent created in CodyApp, not ChatPanel.** Keeps the ChatPanel UI
   decoupled from provider instantiation. The app wires services together.

---

## Usage

```
Ctrl+Space w t r  → open right sidebar
Click Chat tab    → shows conversation
Type a message    → streams agent response with thinking and tools
```
