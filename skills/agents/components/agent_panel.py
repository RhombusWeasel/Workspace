"""Agent panel — sidebar tab for viewing and managing agent definitions.

Displays all agents in a tree.  Each agent shows its name, model, and
scope, with an **Edit** button to modify the template and a **Delete**
button to remove it.  A **+ New** button at the top creates a new agent.

Leaf nodes show the agent's template preview, provider, tools,
skills, and generation parameters.

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
from core.agent_registry import AgentManager
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


def _agent_buttons() -> list[RowButton]:
    return [
        RowButton(_EDIT, EDIT, "agent-edit"),
        RowButton(_DELETE, DELETE, "agent-delete"),
    ]


def _truncate(text: str, max_len: int = 60) -> str:
    """Truncate text for preview, replacing newlines."""
    preview = text.replace("\n", " ↵ ")[:max_len]
    if len(text) > max_len:
        preview += "…"
    return preview


# ---------------------------------------------------------------------------
# AgentPanel
# ---------------------------------------------------------------------------


@register_sidebar_tab(name="agents", icon="󱙺", side="left",
                       tooltip="Agents")
class AgentPanel(Container):
    """Sidebar panel showing agent definitions as an editable tree.

    Each agent is a branch node whose children show the template
    preview, model, provider, scope, tools, and skills.  Edit/Delete
    buttons on each agent row.
    """

    def __init__(self):
        super().__init__()
        self._agents: AgentManager | None = None

    # ------------------------------------------------------------------
    # Compose
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        with Horizontal(classes="agent-panel-header"):
            yield Static("Agents", classes="agent-panel-title")
            yield Button("+", id="agent-new-btn", variant="success",
                         classes="agent-new-btn")
        self._tree = Tree(TreeNode("agents-root", "Agents"))
        yield self._tree

    # ------------------------------------------------------------------
    # Mount
    # ------------------------------------------------------------------

    def on_mount(self) -> None:
        app = self.app
        if hasattr(app, "context") and app.context is not None:
            self._agents = app.context.agents
        self._rebuild()

    # ------------------------------------------------------------------
    # Tree building
    # ------------------------------------------------------------------

    def _rebuild(self) -> None:
        """Rebuild the tree from the agent registry."""
        if self._agents is None:
            root = TreeNode("agents-root", "Agents (not available)")
            self._tree.set_root(root)
            return

        agent_list = self._agents.list_agents()
        children: list[TreeNode] = []

        for a in agent_list:
            agent_id = a["id"]
            scope = a.get("scope", "global")
            scope_icon = _SCOPE_ICONS.get(scope, "󰌘")

            # Build detail line for the label
            details: list[str] = []
            if a.get("model"):
                details.append(f"model={a['model']}")
            if a.get("provider"):
                details.append(f"provider={a['provider']}")
            detail_str = f"  · {'  · '.join(details)}" if details else ""

            # Truncate template for preview
            template = a.get("template", "")
            preview = _truncate(template)

            # Build sub-nodes for agent config details
            sub_nodes: list[TreeNode] = [
                TreeNode(
                    id=f"agent-{agent_id}-template",
                    label=f"📋 {preview}",
                    data={"type": "template-preview", "agent_id": agent_id},
                ),
                TreeNode(
                    id=f"agent-{agent_id}-scope",
                    label=f"Scope: {scope}",
                    data={"type": "scope-info", "agent_id": agent_id, "scope": scope},
                ),
            ]

            # Show provider if set
            if a.get("provider"):
                sub_nodes.append(TreeNode(
                    id=f"agent-{agent_id}-provider",
                    label=f"󰢷 Provider: {a['provider']}",
                    data={"type": "provider-info", "agent_id": agent_id},
                ))

            # Show tools if set
            if a.get("tools"):
                sub_nodes.append(TreeNode(
                    id=f"agent-{agent_id}-tools",
                    label=f"🔧 Tools: {a['tools']}",
                    data={"type": "tools-info", "agent_id": agent_id},
                ))

            # Show skills if set
            if a.get("skills"):
                sub_nodes.append(TreeNode(
                    id=f"agent-{agent_id}-skills",
                    label=f"󱙺 Skills: {a['skills']}",
                    data={"type": "skills-info", "agent_id": agent_id},
                ))

            # Show temperature if set
            if a.get("temperature"):
                sub_nodes.append(TreeNode(
                    id=f"agent-{agent_id}-temperature",
                    label=f"🌡 Temperature: {a['temperature']}",
                    data={"type": "temp-info", "agent_id": agent_id},
                ))

            # Show max_tool_iterations if set
            if a.get("max_tool_iterations"):
                sub_nodes.append(TreeNode(
                    id=f"agent-{agent_id}-mti",
                    label=f"🔄 Max iterations: {a['max_tool_iterations']}",
                    data={"type": "mti-info", "agent_id": agent_id},
                ))

            # Branch node for the agent
            agent_node = TreeNode(
                id=f"agent-{agent_id}",
                label=f"{scope_icon} {a['name']}{detail_str}",
                label_expanded=f"{scope_icon} {a['name']}",
                data={
                    "type": "agent",
                    "agent_id": agent_id,
                    "name": a["name"],
                    "scope": scope,
                    "model": a.get("model", ""),
                    "provider": a.get("provider", ""),
                },
                buttons=_agent_buttons(),
                children=sub_nodes,
            )
            children.append(agent_node)

        root = TreeNode("agents-root", "Agents", children=children)
        self._tree.set_root(root)
        self._tree.expand_all()

    # ------------------------------------------------------------------
    # Button handlers
    # ------------------------------------------------------------------

    def on_tree_row_button_pressed(self, event: TreeRow.ButtonPressed) -> None:
        """Handle Edit / Delete button presses on agent nodes."""
        event.stop()
        node = event.node
        data = node.data or {}
        agent_id = data.get("agent_id", "")
        node_type = data.get("type", "")

        if node_type != "agent":
            return

        if event.action_id == _EDIT:
            self._agent_edit(agent_id)
        elif event.action_id == _DELETE:
            self._agent_delete(agent_id)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle the + New button."""
        event.stop()
        if event.button.id == "agent-new-btn":
            self._agent_create()

    # ------------------------------------------------------------------
    # CRUD dialogs
    # ------------------------------------------------------------------

    def _agent_edit(self, agent_id: str) -> None:
        """Open a multi-line text editor modal for editing an agent template."""
        from ui.widgets.text_editor_modal import TextEditorModal

        if self._agents is None:
            return

        agent = self._agents.get_agent(agent_id)
        if agent is None:
            return

        template = agent.get("template", "")

        async def do_edit() -> None:
            modal = TextEditorModal(
                f"Edit agent: {agent['name']}",
                text=template,
                language="markdown",
            )
            result = await self.app.push_screen_wait(modal)
            if result is None:
                return

            self._agents.update_agent(agent_id, template=result)
            self._rebuild()

        self.app.run_worker(do_edit())

    def _agent_delete(self, agent_id: str) -> None:
        """Delete an agent after confirmation."""
        from ui.widgets.confirm_modal import ConfirmModal

        # Don't allow deleting built-in agents
        if not agent_id.startswith("custom:"):
            self.app.notify("Built-in agents cannot be deleted", severity="warning")
            return

        async def do_delete() -> None:
            modal = ConfirmModal(
                f"Delete agent '{agent_id}'?",
                body="This action cannot be undone.",
            )
            confirmed = await self.app.push_screen_wait(modal)
            if not confirmed:
                return

            self._agents.delete_agent(agent_id)
            self._rebuild()
            self.app.notify(f"Deleted agent '{agent_id}'")

        self.app.run_worker(do_delete())

    def _agent_create(self) -> None:
        """Create a new agent via a multi-step modal flow.

        First asks for a name via a single-line InputModal, then
        optional provider/model via InputModal, then opens a
        TextEditorModal for the template body.
        """
        from ui.widgets.input_modal import InputModal
        from ui.widgets.text_editor_modal import TextEditorModal

        if self._agents is None:
            return

        async def do_create() -> None:
            # Step 1: Name (single-line)
            name_modal = InputModal(
                "New Agent",
                label="Name",
                default="",
            )
            name = await self.app.push_screen_wait(name_modal)
            if not name or not name.strip():
                return

            # Step 2: Provider (optional)
            provider_modal = InputModal(
                f"Provider for: {name.strip()}",
                label="Provider instance name (leave empty for default)",
                default="",
            )
            provider = await self.app.push_screen_wait(provider_modal)
            if provider is None:
                return

            # Step 3: Model (optional)
            model_modal = InputModal(
                f"Model for: {name.strip()}",
                label="Model name (leave empty for default)",
                default="",
            )
            model = await self.app.push_screen_wait(model_modal)
            if model is None:
                return

            # Step 4: Template (multi-line)
            template_modal = TextEditorModal(
                f"Template for: {name.strip()}",
                text="You are a helpful assistant. {{skills}}",
                language="markdown",
            )
            template = await self.app.push_screen_wait(template_modal)
            if template is None:
                return

            agent_id = self._agents.create_agent(
                name=name.strip(),
                description="",
                template=template,
                model=model.strip() if model else "",
                provider=provider.strip() if provider else "",
                scope="global",
            )
            self._rebuild()
            self.app.notify(f"Created agent '{name.strip()}'")

        self.app.run_worker(do_create())