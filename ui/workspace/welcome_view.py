"""Welcome view — landing page shown in the initial workspace tab.

Displays a helpful introduction to Cody with key bindings and tips
for getting started.  Rendered as Markdown inside a scrollable container.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Markdown


_WELCOME_MARKDOWN = """\
# Welcome to Cody

Your AI-powered coding assistant, right in your terminal.

---

## Getting Started

- **Open a file** — Browse files in the sidebar and press **Open**
- **Open a terminal** — `Ctrl+Space ` `t` `o`
- **Leader menu** — Press `Ctrl+Space` for all commands
- **Split workspace** — `Ctrl+Space` `w` `s` `v` (vertical) or `h` (horizontal)
- **Close pane** — `Ctrl+Space` `w` `c`
- **Quit** — Press `Ctrl+Q`

## Navigation

| Key | Action |
|-----|--------|
| `Ctrl+h` | Move to left pane |
| `Ctrl+l` | Move to right pane |
| `Ctrl+k` | Move to pane above |
| `Ctrl+j` | Move to pane below |
| `Ctrl+Space` | Open leader menu |

## Terminal

- **Open** — `Ctrl+Space` `t` `o`
- **Release focus** — Press `Ctrl+F1` inside the terminal to return to app navigation

Open a file from the sidebar or a terminal to get started.
"""


class WelcomeView(Widget):
    """Landing page shown when the workspace first launches.

    Rendered inside the initial ``WorkspaceTabs`` tab so the user
    immediately sees a tabbed interface rather than an empty pane.
    """

    def compose(self) -> ComposeResult:
        yield Markdown(_WELCOME_MARKDOWN)