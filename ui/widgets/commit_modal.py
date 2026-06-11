"""Commit modal — dialog for entering a git commit message.

Shows an input field for the commit message and three buttons:

* **OK** — commits the staged changes with the entered message.
* **Fill with AI** — sends ``git diff --cached`` to the LLM agent and
  fills the input field with a generated conventional-commit message.
* **Cancel** — dismisses the modal without committing.

Returns the commit message string on OK, or ``None`` on cancel.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static

from utils.icons import REFRESH

if TYPE_CHECKING:
    from context import AppContext


# ---------------------------------------------------------------------------
# Commit modal
# ---------------------------------------------------------------------------


class CommitModal(ModalScreen[str | None]):
    """Modal dialog for entering a git commit message.

    Parameters
    ----------
    ctx:
        The :class:`AppContext` — used to access the LLM provider
        for the "Fill with AI" feature.
    working_directory:
        The repo working directory — used to run ``git diff --cached``.
    """

    def __init__(
        self,
        ctx: AppContext,
        working_directory: str,
    ) -> None:
        super().__init__()
        self._ctx = ctx
        self._wd = working_directory
        self._filling = False

    def compose(self) -> ComposeResult:
        with Vertical(id="commit-dialog"):
            yield Label("Commit staged changes")
            yield Input(
                value="",
                placeholder="Enter commit message…",
                id="commit-input",
            )
            with Horizontal(id="commit-buttons"):
                yield Button("OK", variant="primary", id="btn-commit-ok")
                yield Button(
                    f"{REFRESH} Fill with AI", variant="default", id="btn-commit-ai"
                )
                yield Button("Cancel", variant="default", id="btn-commit-cancel")

    def on_mount(self) -> None:
        self.query_one("#commit-input", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        btn_id = event.button.id

        if btn_id == "btn-commit-ok":
            value = self.query_one("#commit-input", Input).value.strip()
            if value:
                self.dismiss(value)
            # Empty message — don't dismiss, let the user fix it
        elif btn_id == "btn-commit-ai":
            self._fill_ai_message()
        elif btn_id == "btn-commit-cancel":
            self.dismiss(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        value = event.value.strip()
        if value:
            self.dismiss(value)

    # ------------------------------------------------------------------
    # AI fill
    # ------------------------------------------------------------------

    def _fill_ai_message(self) -> None:
        """Generate a commit message using the LLM agent and fill the input."""
        if self._filling:
            return
        self._filling = True

        # Disable the AI button while working
        try:
            ai_btn = self.query_one("#btn-commit-ai", Button)
            ai_btn.disabled = True
            ai_btn.label = "Generating…"
        except Exception:
            pass

        self.run_worker(self._do_fill_ai())

    async def _do_fill_ai(self) -> None:
        """Worker that calls the LLM and fills in the commit message."""
        import subprocess

        # 1. Get the staged diff
        try:
            result = subprocess.run(
                ["git", "diff", "--cached"],
                capture_output=True,
                text=True,
                timeout=10,
                cwd=self._wd,
            )
            diff = result.stdout.strip()
        except Exception as exc:
            self._set_status(f"Failed to get diff: {exc}")
            self._reset_ai_button()
            return

        if not diff:
            self._set_status("Nothing staged — stage files first.")
            self._reset_ai_button()
            return

        # Also get a diff stat for context
        try:
            stat_result = subprocess.run(
                ["git", "diff", "--cached", "--stat"],
                capture_output=True,
                text=True,
                timeout=10,
                cwd=self._wd,
            )
            stat = stat_result.stdout.strip()
        except Exception:
            stat = ""

        # Truncate diff if very large (keep first 3000 lines)
        diff_lines = diff.split("\n")
        if len(diff_lines) > 3000:
            diff = "\n".join(diff_lines[:3000]) + "\n... (truncated)"

        # 2. Build prompt
        prompt = (
            "Write a concise git commit message for the following staged changes. "
            "Use conventional commit format (type(scope): description). "
            "Reply with ONLY the commit message — no explanation, no markdown.\n\n"
        )
        if stat:
            prompt += f"Changed files:\n{stat}\n\n"
        prompt += f"Diff:\n{diff}"

        # 3. Call the LLM via the provider
        message = await self._call_llm(prompt)

        # 4. Fill the input
        try:
            inp = self.query_one("#commit-input", Input)
            inp.value = message.strip()
            inp.cursor_position = len(inp.value)
            inp.focus()
        except Exception:
            pass

        # Clear any status message
        self._set_status("")
        self._reset_ai_button()

    async def _call_llm(self, prompt: str) -> str:
        """Make a simple non-streaming LLM call and return the response text."""
        from core.agent import Agent
        from core.providers.base import Message

        ctx = self._ctx
        if ctx is None or ctx.providers is None:
            return "chore: update files"

        try:
            provider = ctx.providers.get_default()
        except (ValueError, KeyError):
            return "chore: update files"

        model = ""
        if ctx.config is not None:
            model = ctx.config.get("session.model", "")

        agent = Agent(
            provider=provider,
            template="You are an expert at writing concise, conventional git commit messages.",
            model=model,
            ctx=ctx,
        )

        # Use non-streaming chat
        messages = agent.build_messages([], prompt)
        try:
            response = await agent.chat([], prompt, tools=None)
            return response.content or "chore: update files"
        except Exception:
            return "chore: update files"

    def _reset_ai_button(self) -> None:
        """Re-enable the AI button after filling is done."""
        self._filling = False
        try:
            ai_btn = self.query_one("#btn-commit-ai", Button)
            ai_btn.disabled = False
            ai_btn.label = f"{REFRESH} Fill with AI"
        except Exception:
            pass

    def _set_status(self, text: str) -> None:
        """Show a status message below the buttons (optional helper)."""
        # We don't have a dedicated status label in this simple modal,
        # but we can update the main label as a fallback.
        try:
            label = self.query_one("#commit-dialog Label", Label)
            if text:
                label.update(text)
            else:
                label.update("Commit staged changes")
        except Exception:
            pass