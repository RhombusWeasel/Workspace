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

Open a file from the sidebar to start editing.
"""


class WelcomeView(Widget):
    """Landing page shown when the workspace first launches.

    Rendered inside the initial ``WorkspaceTabs`` tab so the user
    immediately sees a tabbed interface rather than an empty pane.
    """

    DEFAULT_CSS = """
    WelcomeView {
        height: 1fr;
        width: 1fr;
        padding: 1 2;
        overflow-y: auto;
    }
    WelcomeView Markdown {
        height: auto;
        width: 1fr;
    }
    """

    def compose(self) -> ComposeResult:
        yield Markdown(_WELCOME_MARKDOWN)