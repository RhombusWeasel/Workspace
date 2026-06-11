"""Git panel — sidebar tab showing repository status, changes, and recent commits.

Registered as a sidebar tab via ``@register_sidebar_tab``.  Leader chords
are registered for quick git actions.  Uses the Tree widget to display
branch info, staged/unstaged/untracked files, and recent commits.

Each file row includes inline action buttons:

- **Staged** files show a **−** (unstage) button → ``git reset HEAD -- <path>``
- **Unstaged** files show a **+** (stage) button → ``git add <path>``
- **Untracked** files show a **+** (track) button → ``git add <path>``

Section headers for Unstaged and Untracked groups include a **+All**
button to stage all files in that group.

The action bar at the bottom includes:

- **Refresh** — rescan the repository
- **Commit** — open a commit modal with AI-generated message support

Event handlers:
- ``git.refresh`` — refresh the git panel
- ``git.status`` — run detailed status script
- ``git.checkpoint`` — create a checkpoint
- ``git.log`` — view formatted log
- ``git.diff`` — view diff summary
"""

from __future__ import annotations

import os
import subprocess
from typing import Any

from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.widgets import Button, Static

from context import AppContext
from core.config import register_defaults
from core.events import WorkspaceEvent, register_handler
from core.leader import register_submenu, register_action
from ui.sidebar.registry import register_sidebar_tab
from ui.tree.tree import Tree, NodeSelected
from ui.tree.tree_row import TreeNode, RowButton
from utils.icons import PLUS, REFRESH

# ---------------------------------------------------------------------------
# Config defaults
# ---------------------------------------------------------------------------

register_defaults({
    "git": {
        "log_count": 5,
        "auto_refresh": True,
    }
})

# ---------------------------------------------------------------------------
# Leader chords
# ---------------------------------------------------------------------------

register_submenu(["g"], "Git")
register_action(["g", "s"], "Status", event_type="git.status", labels={"g": "Git"})
register_action(["g", "c"], "Checkpoint", event_type="git.checkpoint", labels={"g": "Git"})
register_action(["g", "l"], "Log", event_type="git.log", labels={"g": "Git"})
register_action(["g", "d"], "Diff", event_type="git.diff", labels={"g": "Git"})
register_action(["g", "r"], "Refresh", event_type="git.refresh", labels={"g": "Git"})

# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------

# Button action IDs
_STAGE = "git-stage"
_UNSTAGE = "git-unstage"
_STAGE_ALL_UNSTAGED = "git-stage-all-unstaged"
_STAGE_ALL_UNTRACKED = "git-stage-all-untracked"

# Button labels
STAGE_LABEL = PLUS          # ＋  stage/track
UNSTAGE_LABEL = "−"         # −  unstage
STAGE_ALL_LABEL = f"{PLUS}All"


def _run_git(*args: str) -> str:
    """Run a git command and return stdout."""
    try:
        result = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""


def _run_git_in_dir(wd: str, *args: str) -> str:
    """Run a git command in a specific directory and return stdout."""
    try:
        result = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=wd,
        )
        return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""


def _is_git_repo() -> bool:
    """Check if the current directory is inside a git repo."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def _build_status_tree(wd: str, log_count: int = 5) -> TreeNode:
    """Build a tree of git status information for the sidebar panel.

    Each file node includes inline action buttons for staging/unstaging.
    Section headers for Unstaged and Untracked include a "stage all" button.
    """
    old_cwd = os.getcwd()
    try:
        os.chdir(wd)

        if not _is_git_repo():
            return TreeNode("git-root", "Not a git repository")

        root_label_parts: list[str] = []
        branch = _run_git("rev-parse", "--abbrev-ref", "HEAD")

        if branch and branch != "(detached HEAD)":
            root_label_parts.append(f"\ue725 {branch}")
        else:
            commit = _run_git("rev-parse", "--short", "HEAD")
            root_label_parts.append(f"\ue725 detached:{commit}")

        # Tracking / ahead/behind
        tracking = _run_git(
            "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"
        )
        if tracking:
            ab = _run_git("rev-list", "--left-right", "--count", "@{u}...HEAD")
            if ab:
                l_r = ab.split()
                if len(l_r) == 2:
                    ahead, behind = l_r
                    if ahead != "0" or behind != "0":
                        root_label_parts.append(f"\u2191{ahead}\u2193{behind}")

        root = TreeNode(
            "git-root",
            "  ".join(root_label_parts),
            children=[],
        )

        # Parse porcelain status
        porcelain = _run_git("status", "--porcelain=v1")
        staged_files: list[tuple[str, str]] = []
        unstaged_files: list[tuple[str, str]] = []
        untracked_files: list[str] = []

        if porcelain:
            for line in porcelain.split("\n"):
                if not line:
                    continue
                idx = line[0] if len(line) > 0 else " "
                wrk = line[1] if len(line) > 1 else " "
                filepath = line[3:] if len(line) > 3 else line.strip()

                if idx in "MADRC":
                    label_map = {"M": "modified", "A": "added", "D": "deleted", "R": "renamed", "C": "copied"}
                    staged_files.append((filepath, label_map.get(idx, idx)))

                if wrk in "MD":
                    wrk_map = {"M": "modified", "D": "deleted"}
                    unstaged_files.append((filepath, wrk_map.get(wrk, wrk)))

                if idx == "?" and wrk == "?":
                    untracked_files.append(filepath)

        # Staged section — each file gets an unstage button
        staged_children = [
            TreeNode(
                f"staged-{i}",
                f"  {path}",
                data={"path": path, "type": "staged"},
                buttons=[RowButton(_UNSTAGE, UNSTAGE_LABEL, "git-unstage")],
            )
            for i, (path, _) in enumerate(staged_files)
        ]
        staged_node = TreeNode(
            "git-staged",
            f"\uf067 Staged ({len(staged_files)})",
            children=staged_children if staged_files else [],
        )
        if not staged_files:
            staged_node.children = [TreeNode("staged-empty", "  (clean)", data={"type": "empty"})]

        # Unstaged section — each file gets a stage button; header gets "stage all"
        unstaged_buttons = [RowButton(_STAGE_ALL_UNSTAGED, STAGE_ALL_LABEL, "git-stage-all")] if unstaged_files else []
        unstaged_children = [
            TreeNode(
                f"unstaged-{i}",
                f"  {path}",
                data={"path": path, "type": "unstaged"},
                buttons=[RowButton(_STAGE, STAGE_LABEL, "git-stage")],
            )
            for i, (path, _) in enumerate(unstaged_files)
        ]
        unstaged_node = TreeNode(
            "git-unstaged",
            f"\uf068 Unstaged ({len(unstaged_files)})",
            children=unstaged_children if unstaged_files else [],
            buttons=unstaged_buttons,
        )
        if not unstaged_files:
            unstaged_node.children = [TreeNode("unstaged-empty", "  (clean)", data={"type": "empty"})]

        # Untracked section — each file gets a track button; header gets "track all"
        untracked_buttons = [RowButton(_STAGE_ALL_UNTRACKED, STAGE_ALL_LABEL, "git-stage-all")] if untracked_files else []
        untracked_children = [
            TreeNode(
                f"untracked-{i}",
                f"  {path}",
                data={"path": path, "type": "untracked"},
                buttons=[RowButton(_STAGE, STAGE_LABEL, "git-track")],
            )
            for i, path in enumerate(untracked_files)
        ]
        untracked_node = TreeNode(
            "git-untracked",
            f"\uf128 Untracked ({len(untracked_files)})",
            children=untracked_children if untracked_files else [],
            buttons=untracked_buttons,
        )
        if not untracked_files:
            untracked_node.children = [TreeNode("untracked-empty", "  (none)", data={"type": "empty"})]

        # Recent commits section
        log_count = max(1, min(log_count, 20))
        log_fmt = "%h|%ad|%s"
        log_output = _run_git(
            "log", f"-{log_count}",
            f"--format={log_fmt}",
            "--date=short",
        )
        commit_children: list[TreeNode] = []
        if log_output:
            for i, line in enumerate(log_output.split("\n")):
                if not line.strip():
                    continue
                segments = line.split("|", 2)
                if len(segments) >= 3:
                    short_hash, date, subject = segments
                    commit_children.append(TreeNode(
                        f"commit-{i}",
                        f"  {short_hash} {date} {subject}",
                        data={"hash": short_hash, "type": "commit"},
                    ))

        commits_node = TreeNode(
            "git-commits",
            f"\uf417 Recent",
            children=commit_children if commit_children else [
                TreeNode("commits-empty", "  (no commits)", data={"type": "empty"})
            ],
        )

        # Stash section
        stash_list = _run_git("stash", "list")
        stash_children: list[TreeNode] = []
        if stash_list:
            for i, line in enumerate(stash_list.split("\n")):
                if not line.strip():
                    continue
                stash_children.append(TreeNode(
                    f"stash-{i}",
                    f"  {line.strip()}",
                    data={"type": "stash"},
                ))

        stash_node = TreeNode(
            "git-stash",
            f"\uf01c Stash ({len(stash_children)})",
            children=stash_children if stash_children else [
                TreeNode("stash-empty", "  (none)", data={"type": "empty"})
            ],
        )

        root.children = [staged_node, unstaged_node, untracked_node, commits_node, stash_node]
        return root

    finally:
        os.chdir(old_cwd)


# ---------------------------------------------------------------------------
# Panel widget
# ---------------------------------------------------------------------------


@register_sidebar_tab(name="git", icon="\ue702", side="left", tooltip="Git")
class GitPanel(Container):
    """Sidebar panel showing git repository status.

    Displays current branch, tracking info, staged/unstaged/untracked
    files, recent commits, and stashes in a tree structure.

    Inline action buttons allow staging and unstaging individual files
    or all files in a group.  The Commit button opens a
    :class:`~ui.widgets.commit_modal.CommitModal` that supports
    AI-generated commit messages.

    Actions:
    - **Refresh**: Rescan the repository and rebuild the tree.
    - **Commit**: Open a commit dialog (with AI message generation).
    - **Status**: Run the detailed status script (via event).
    - **Checkpoint**: Create a safety checkpoint (via event).
    """

    def __init__(self, working_directory: str | None = None):
        super().__init__()
        self._wd = working_directory or os.getcwd()

    def compose(self) -> ComposeResult:
        yield Static("\ue702  Git", classes="section-header")
        self._tree = Tree(TreeNode("git-root", "Loading..."))
        yield self._tree
        with Horizontal(classes="git-panel-actions"):
            yield Button(REFRESH, id="git-refresh", variant="default")
            yield Button("\uf417 Commit", id="git-commit", variant="primary")

    def on_mount(self) -> None:
        app = self.app
        if hasattr(app, "context") and app.context is not None:
            self._wd = app.context.working_directory or self._wd
        self._rebuild()

    # ------------------------------------------------------------------
    # Tree building
    # ------------------------------------------------------------------

    def _rebuild(self) -> None:
        """Rebuild the git status tree."""
        log_count = 5
        app = self.app
        if hasattr(app, "context") and app.context is not None:
            log_count = app.context.config.get("git.log_count", 5)

        root = _build_status_tree(self._wd, log_count=log_count)
        self._tree.set_root(root)

        # Expand the root and the first-level children
        self._tree.expand_node("git-root")
        for child in root.children:
            if child.id:
                self._tree.expand_node(child.id)

    def refresh_tree(self) -> None:
        """Public refresh — same as _rebuild."""
        self._rebuild()

    # ------------------------------------------------------------------
    # Button handlers
    # ------------------------------------------------------------------

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "git-refresh":
            self._rebuild()
        elif event.button.id == "git-commit":
            self._open_commit_modal()

    # ------------------------------------------------------------------
    # Tree row button handlers
    # ------------------------------------------------------------------

    def on_tree_row_button_pressed(self, msg) -> None:
        """Handle inline action button presses on tree rows."""
        msg.stop()
        action_id = msg.action_id
        node = msg.node
        data = node.data or {}

        if action_id == _STAGE:
            filepath = data.get("path", "")
            if filepath:
                self._stage_file(filepath)
        elif action_id == _UNSTAGE:
            filepath = data.get("path", "")
            if filepath:
                self._unstage_file(filepath)
        elif action_id == _STAGE_ALL_UNSTAGED:
            self._stage_all_unstaged()
        elif action_id == _STAGE_ALL_UNTRACKED:
            self._stage_all_untracked()

    # ------------------------------------------------------------------
    # Git actions
    # ------------------------------------------------------------------

    def _stage_file(self, filepath: str) -> None:
        """Stage a single file."""
        subprocess.run(
            ["git", "add", filepath],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=self._wd,
        )
        self.app.notify(f"Staged {filepath}", title="Git", timeout=3, markup=False)
        self._rebuild()

    def _unstage_file(self, filepath: str) -> None:
        """Unstage a single file."""
        subprocess.run(
            ["git", "reset", "HEAD", "--", filepath],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=self._wd,
        )
        self.app.notify(f"Unstaged {filepath}", title="Git", timeout=3, markup=False)
        self._rebuild()

    def _stage_all_unstaged(self) -> None:
        """Stage all unstaged (modified/deleted tracked) files."""
        subprocess.run(
            ["git", "add", "-u"],
            capture_output=True,
            text=True,
            timeout=15,
            cwd=self._wd,
        )
        self.app.notify("Staged all unstaged changes", title="Git", timeout=3, markup=False)
        self._rebuild()

    def _stage_all_untracked(self) -> None:
        """Stage all untracked files."""
        subprocess.run(
            ["git", "add", "."],
            capture_output=True,
            text=True,
            timeout=15,
            cwd=self._wd,
        )
        self.app.notify("Staged all untracked files", title="Git", timeout=3, markup=False)
        self._rebuild()

    # ------------------------------------------------------------------
    # Commit modal
    # ------------------------------------------------------------------

    def _open_commit_modal(self) -> None:
        """Open the commit modal dialog."""
        # Check if there are staged changes
        result = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=self._wd,
        )
        if result.returncode == 0:
            # No staged changes (diff is empty)
            self.app.notify("Nothing staged — stage files first", title="Git", timeout=3, markup=False)
            return

        from ui.widgets.commit_modal import CommitModal

        ctx = None
        if hasattr(self.app, "context") and self.app.context is not None:
            ctx = self.app.context

        async def do_commit() -> None:
            modal = CommitModal(ctx, self._wd)
            result = await self.app.push_screen_wait(modal)
            if result is None:
                return

            # Perform the commit
            proc = subprocess.run(
                ["git", "commit", "-m", result],
                capture_output=True,
                text=True,
                timeout=30,
                cwd=self._wd,
            )
            if proc.returncode == 0:
                output = proc.stdout.strip() or "Committed"
                self.app.notify(output, title="Git Commit", timeout=5, markup=False)
            else:
                error = proc.stderr.strip() or proc.stdout.strip() or "Commit failed"
                self.app.notify(error, title="Git Error", timeout=5, markup=False)

            self._rebuild()

        self.app.run_worker(do_commit())

    # ------------------------------------------------------------------
    # Selection handler
    # ------------------------------------------------------------------

    def on_node_selected(self, msg: NodeSelected) -> None:
        """Handle tree node selection — open files or view commits."""
        msg.stop()
        node = msg.node
        data = node.data or {}

        # Open file for editing if it's a staged/unstaged/untracked file
        if data.get("type") in ("staged", "unstaged", "untracked"):
            filepath = data.get("path", "")
            if filepath and os.path.isfile(os.path.join(self._wd, filepath)):
                full_path = os.path.join(self._wd, filepath)
                self.post_message(WorkspaceEvent("files.edit", {"path": full_path}))


# ---------------------------------------------------------------------------
# Event handlers
# ---------------------------------------------------------------------------


@register_handler("git.refresh")
def _on_git_refresh(data: dict, ctx: AppContext) -> None:
    """Handle git.refresh — refresh the git sidebar panel."""
    _refresh_panel(ctx)


@register_handler("git.status")
def _on_git_status(data: dict, ctx: AppContext) -> None:
    """Handle git.status — refresh the git panel to show current status."""
    _refresh_panel(ctx)


@register_handler("git.checkpoint")
def _on_git_checkpoint(data: dict, ctx: AppContext) -> None:
    """Handle git.checkpoint — prompts for a checkpoint message and creates one."""
    app = ctx.app
    if app is None:
        return

    async def do_checkpoint() -> None:
        from ui.widgets.input_modal import InputModal
        result = await app.push_screen_wait(
            InputModal("Checkpoint message:", "Checkpoint", default="checkpoint")
        )
        if not result:
            return
        import subprocess
        import os
        import sys
        script_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "scripts", "checkpoint.py"
        )
        try:
            proc = subprocess.run(
                [sys.executable, script_path, "create", result],
                capture_output=True,
                text=True,
                timeout=15,
                cwd=ctx.working_directory,
            )
            output = proc.stdout.strip() if proc.stdout else ""
            if proc.stderr and proc.stderr.strip():
                output += f"\n{proc.stderr.strip()}"
            app.notify(output or "Checkpoint created", title="Git Checkpoint", timeout=5)
        except Exception as exc:
            app.notify(f"Checkpoint failed: {exc}", title="Git Error")

    app.run_worker(do_checkpoint())


@register_handler("git.log")
def _on_git_log(data: dict, ctx: AppContext) -> None:
    """Handle git.log — refresh the git panel to show recent commits."""
    _refresh_panel(ctx)


@register_handler("git.diff")
def _on_git_diff(data: dict, ctx: AppContext) -> None:
    """Handle git.diff — refresh the git panel."""
    _refresh_panel(ctx)


def _refresh_panel(ctx: AppContext) -> None:
    """Refresh the git sidebar panel if it's mounted."""
    app = ctx.app
    if app is None:
        return
    try:
        panel = app.query_one("#tab-git GitPanel", GitPanel)
        panel.refresh_tree()
    except Exception:
        pass


# Required for the lazy import in on_git_checkpoint
import sys  # noqa: E402