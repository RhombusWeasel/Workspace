---
name: terminal
description: Embedded terminal emulator with scrollback, PTY lifecycle management, and workspace tab integration
---

# Terminal Plugin

Embedded terminal emulator for workspace panes, wrapping
`textual_terminal.Terminal` with lifecycle management, working
directory context, and integration with the `WorkspaceTabs` system.

## Components

| Component | Purpose |
|-----------|---------|
| TerminalView | Embedded terminal widget for workspace panes |
| TerminalState | Persistent state that survives workspace recomposition |
| terminal_handler | Opens terminals via the `terminal.open` event |
| leader chord | `Ctrl+Space t o` — open a new terminal |

## Events

- `terminal.open` — open a new terminal tab in the focused workspace pane

## Leader Chords

- `t` → Terminal submenu
  - `o` → Open a new terminal