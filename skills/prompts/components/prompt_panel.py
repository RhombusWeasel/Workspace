"""Prompt panel — sidebar tab for viewing and managing prompt templates.

Displays all prompts in a tree.  Each prompt shows its name and scope,
with an **Edit** button to modify the template and a **Delete** button
to remove it.  A **+ New** button at the top creates a new prompt.

Leaf nodes show the prompt's template preview.  Branch nodes show
the prompt name and scope badge.

Registered as a sidebar tab via ``@register_sidebar_tab``.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Button, Static

from context import AppContext
from ui.sidebar.registry import register_sidebar_tab
from ui.tree.tree import Tree
from ui.tree.tree_row import TreeNode, TreeRow, RowButton
from core.prompt_registry import PromptManager
from utils.icons import EDIT, DELETE, ADD_FILE

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_EDIT = "edit"
_DELETE = "delete"
_NEW = "new"

_SCOPE_ICONS = {
    "global": "󰌘",   # globe
    "project": "󰢷",  # folder
}


def _prompt_buttons() -> list[RowButton]:
    return [
        RowButton(_EDIT, EDIT, "prompt-edit"),
        RowButton(_DELETE, DELETE, "prompt-delete"),
    ]


# ---------------------------------------------------------------------------
# PromptPanel
# ---------------------------------------------------------------------------


@register_sidebar_tab(name="prompts", icon="󰚩", side="left",
                       tooltip="Prompts")
class PromptPanel(Container):
    """Sidebar panel showing prompt templates as an editable tree.

    Each prompt is a branch node whose children show the template
    preview, scope, and model override.  Edit/Delete buttons on
    each prompt row.
    """

    def __init__(self):
        super().__init__()
        self._prompts: PromptManager | None = None

    # ------------------------------------------------------------------
    # Compose
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        with Horizontal(classes="prompt-panel-header"):
            yield Static("Prompts", classes="prompt-panel-title")
            yield Button("+", id="prompt-new-btn", variant="success",
                         classes="prompt-new-btn")
        self._tree = Tree(TreeNode("prompts-root", "Prompts"))
        yield self._tree

    # ------------------------------------------------------------------
    # Mount
    # ------------------------------------------------------------------

    def on_mount(self) -> None:
        app = self.app
        if hasattr(app, "context") and app.context is not None:
            self._prompts = app.context.prompts
        self._rebuild()

    # ------------------------------------------------------------------
    # Tree building
    # ------------------------------------------------------------------

    def _rebuild(self) -> None:
        """Rebuild the tree from the prompt registry."""
        if self._prompts is None:
            root = TreeNode("prompts-root", "Prompts (not available)")
            self._tree.set_root(root)
            return

        prompts = self._prompts.list_prompts()
        children: list[TreeNode] = []

        for p in prompts:
            prompt_id = p["id"]
            scope = p.get("scope", "global")
            scope_icon = _SCOPE_ICONS.get(scope, "󰌘")

            # Truncate template for preview
            template = p.get("template", "")
            preview = template.replace("\n", " ↵ ")[:60]
            if len(template) > 60:
                preview += "…"

            model_info = ""
            if p.get("model"):
                model_info = f"  · model={p['model']}"

            # Branch node for the prompt
            prompt_node = TreeNode(
                id=f"prompt-{prompt_id}",
                label=f"{scope_icon} {p['name']}{model_info}",
                label_expanded=f"{scope_icon} {p['name']}",
                data={
                    "type": "prompt",
                    "prompt_id": prompt_id,
                    "name": p["name"],
                    "scope": scope,
                    "model": p.get("model", ""),
                },
                buttons=_prompt_buttons(),
                children=[
                    # Template preview child
                    TreeNode(
                        id=f"prompt-{prompt_id}-template",
                        label=f"📋 {preview}",
                        data={"type": "template-preview", "prompt_id": prompt_id},
                    ),
                    # Scope child
                    TreeNode(
                        id=f"prompt-{prompt_id}-scope",
                        label=f"Scope: {scope}",
                        data={"type": "scope-info", "prompt_id": prompt_id, "scope": scope},
                    ),
                ],
            )
            children.append(prompt_node)

        root = TreeNode("prompts-root", "Prompts", children=children)
        self._tree.set_root(root)
        self._tree.expand_all()

    # ------------------------------------------------------------------
    # Button handlers
    # ------------------------------------------------------------------

    def on_tree_row_button_pressed(self, event: TreeRow.ButtonPressed) -> None:
        """Handle Edit / Delete button presses on prompt nodes."""
        event.stop()
        node = event.node
        data = node.data or {}
        prompt_id = data.get("prompt_id", "")
        prompt_type = data.get("type", "")

        if prompt_type != "prompt":
            return

        if event.action_id == _EDIT:
            self._prompt_edit(prompt_id)
        elif event.action_id == _DELETE:
            self._prompt_delete(prompt_id)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle the + New button."""
        event.stop()
        if event.button.id == "prompt-new-btn":
            self._prompt_create()

    # ------------------------------------------------------------------
    # CRUD dialogs
    # ------------------------------------------------------------------

    def _prompt_edit(self, prompt_id: str) -> None:
        """Open a multi-line text editor modal for editing a prompt template."""
        from ui.widgets.text_editor_modal import TextEditorModal

        if self._prompts is None:
            return

        prompt = self._prompts.get_prompt(prompt_id)
        if prompt is None:
            return

        template = prompt.get("template", "")

        async def do_edit() -> None:
            modal = TextEditorModal(
                f"Edit prompt: {prompt['name']}",
                text=template,
                language="markdown",
            )
            result = await self.app.push_screen_wait(modal)
            if result is None:
                return

            self._prompts.update_prompt(prompt_id, template=result)
            self._rebuild()

        self.app.run_worker(do_edit())

    def _prompt_delete(self, prompt_id: str) -> None:
        """Delete a prompt after confirmation."""
        from ui.widgets.confirm_modal import ConfirmModal

        # Don't allow deleting built-in prompts
        if not prompt_id.startswith("custom:"):
            self.app.notify("Built-in prompts cannot be deleted", severity="warning")
            return

        async def do_delete() -> None:
            modal = ConfirmModal(
                f"Delete prompt '{prompt_id}'?",
                body="This action cannot be undone.",
            )
            confirmed = await self.app.push_screen_wait(modal)
            if not confirmed:
                return

            self._prompts.delete_prompt(prompt_id)
            self._rebuild()
            self.app.notify(f"Deleted prompt '{prompt_id}'")

        self.app.run_worker(do_delete())

    def _prompt_create(self) -> None:
        """Create a new prompt via a multi-step modal flow.

        First asks for a name via a single-line InputModal,
        then opens a TextEditorModal for the template body.
        """
        from ui.widgets.input_modal import InputModal
        from ui.widgets.text_editor_modal import TextEditorModal

        if self._prompts is None:
            return

        async def do_create() -> None:
            # Step 1: Name (single-line)
            name_modal = InputModal(
                "New Prompt",
                label="Name",
                default="",
            )
            name = await self.app.push_screen_wait(name_modal)
            if not name or not name.strip():
                return

            # Step 2: Template (multi-line)
            template_modal = TextEditorModal(
                f"Template for: {name.strip()}",
                text="You are a helpful assistant. {{skills}}",
                language="markdown",
            )
            template = await self.app.push_screen_wait(template_modal)
            if template is None:
                return

            prompt_id = self._prompts.create_prompt(
                name=name.strip(),
                description="",
                template=template,
                scope="global",
            )
            self._rebuild()
            self.app.notify(f"Created prompt '{name.strip()}'")

        self.app.run_worker(do_create())