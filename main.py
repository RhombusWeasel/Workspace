"""Minimal test app for the Workspace widget."""

from textual.app import App, ComposeResult
from textual.widgets import Footer

from ui.workspace import Workspace


class TestApp(App):
    """Test app — mounts a Workspace. Keybindings live on Workspace itself."""

    CSS_PATH = "ui/workspace/workspace.css"

    BINDINGS = [
        ("ctrl+left", "focus_workspace", "Focus WS"),
    ]

    def compose(self) -> ComposeResult:
        self.ws = Workspace()
        yield self.ws
        yield Footer()

    async def on_mount(self) -> None:
        self.ws.focus()

    def action_focus_workspace(self) -> None:
        self.ws.focus()


def main():
    TestApp().run()


if __name__ == "__main__":
    main()
