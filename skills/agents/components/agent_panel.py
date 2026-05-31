"""Agent panel — sidebar tab for viewing and managing agent definitions.

Displays all agents in a tree.  Each agent shows its name, model, and
scope, with an **Edit** button to modify the template and a **Delete**
button to remove it.  A **+ New** button at the top creates a new agent.

Uses the schema-driven :class:`FormModal` for creating agents.

Registered as a sidebar tab via ``@register_sidebar_tab``.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.widgets import Button, Static

from context import AppContext
from ui.sidebar.registry import register_sidebar_tab
from ui.tree.tree import Tree
from ui.tree.tree_row import TreeNode, TreeRow, RowButton
from ui.widgets.form_modal import FormControl, FormModal
from core.agent_registry import AgentManager
from utils.icons import EDIT, DELETE, PLAY


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_EDIT = "edit"
_DELETE = "delete"
_LAUNCH = "launch"

_SCOPE_ICONS = {
    "global": "󰌘",
    "project": "󰢷",
}


def _agent_buttons() -> list[RowButton]:
    return [
        RowButton(_LAUNCH, PLAY, "agent-launch"),
        RowButton(_EDIT, EDIT, "agent-edit"),
        RowButton(_DELETE, DELETE, "agent-delete"),
    ]


def _truncate(text: str, max_len: int = 60) -> str:
    preview = text.replace("\n", " ↵ ")[:max_len]
    if len(text) > max_len:
        preview += "…"
    return preview


def _provider_options(ctx: AppContext | None) -> list[str]:
    """Build list of available provider instance names for a select field."""
    if ctx is not None and ctx.providers is not None:
        instances = ctx.providers.list_instances()
        return instances if instances else []
    return []


# ---------------------------------------------------------------------------
# AgentPanel
# ---------------------------------------------------------------------------


@register_sidebar_tab(name="agents", icon="󱙺", side="left",
                       tooltip="Agents")
class AgentPanel(Container):
    """Sidebar panel showing agent definitions as an editable tree."""

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

            details: list[str] = []
            if a.get("model"):
                details.append(f"model={a['model']}")
            if a.get("provider"):
                details.append(f"provider={a['provider']}")
            detail_str = f"  · {'  · '.join(details)}" if details else ""

            template = a.get("template", "")
            preview = _truncate(template)

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

            if a.get("provider"):
                sub_nodes.append(TreeNode(
                    id=f"agent-{agent_id}-provider",
                    label=f"󰢷 Provider: {a['provider']}",
                    data={"type": "provider-info", "agent_id": agent_id},
                ))
            if a.get("tools"):
                sub_nodes.append(TreeNode(
                    id=f"agent-{agent_id}-tools",
                    label=f"🔧 Tools: {a['tools']}",
                    data={"type": "tools-info", "agent_id": agent_id},
                ))
            if a.get("skills"):
                sub_nodes.append(TreeNode(
                    id=f"agent-{agent_id}-skills",
                    label=f"󱙺 Skills: {a['skills']}",
                    data={"type": "skills-info", "agent_id": agent_id},
                ))
            if a.get("temperature"):
                sub_nodes.append(TreeNode(
                    id=f"agent-{agent_id}-temperature",
                    label=f"🌡 Temperature: {a['temperature']}",
                    data={"type": "temp-info", "agent_id": agent_id},
                ))
            if a.get("max_tool_iterations"):
                sub_nodes.append(TreeNode(
                    id=f"agent-{agent_id}-mti",
                    label=f"🔄 Max iterations: {a['max_tool_iterations']}",
                    data={"type": "mti-info", "agent_id": agent_id},
                ))

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
        event.stop()
        node = event.node
        data = node.data or {}
        agent_id = data.get("agent_id", "")
        node_type = data.get("type", "")

        if node_type != "agent":
            return

        if event.action_id == _LAUNCH:
            self._agent_launch(agent_id)
        elif event.action_id == _EDIT:
            self._agent_edit(agent_id)
        elif event.action_id == _DELETE:
            self._agent_delete(agent_id)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "agent-new-btn":
            self._agent_create()

    # ------------------------------------------------------------------
    # Launch — open a chat tab with this agent
    # ------------------------------------------------------------------

    def _agent_launch(self, agent_id: str) -> None:
        """Open a chat tab using the named agent definition."""
        if self._agents is None:
            return

        agent_def = self._agents.get_agent(agent_id)
        if agent_def is None:
            self.app.notify(f"Agent '{agent_id}' not found", severity="error")
            return

        from core.events import WorkspaceEvent
        self.post_message(WorkspaceEvent("chat.open", {"agent_id": agent_id}))

        # Notify the user which agent was launched.
        name = agent_def.get("name", agent_id)
        model_info = f" (model: {agent_def['model']})" if agent_def.get("model") else ""
        provider_info = f" (provider: {agent_def['provider']})" if agent_def.get("provider") else ""
        self.app.notify(f"Launched agent '{name}'{model_info}{provider_info}")

    # ------------------------------------------------------------------
    # CRUD dialogs
    # ------------------------------------------------------------------

    def _agent_edit(self, agent_id: str) -> None:
        """Open a form modal pre-filled with the agent's current values."""
        if self._agents is None:
            return

        agent = self._agents.get_agent(agent_id)
        if agent is None:
            return

        ctx = getattr(self.app, "context", None)
        provider_opts = _provider_options(ctx)

        controls = self._build_controls(
            provider_opts,
            defaults={
                "name": agent.get("name", ""),
                "provider": agent.get("provider", ""),
                "model": agent.get("model", ""),
                "template": agent.get("template", ""),
                "tools": agent.get("tools", ""),
                "skills": agent.get("skills", ""),
                "temperature": agent.get("temperature", ""),
                "max_tool_iterations": agent.get("max_tool_iterations", ""),
            },
        )

        async def do_edit() -> None:
            modal = FormModal(
                f"Edit Agent: {agent.get('name', agent_id)}",
                controls,
                confirm_label="Save",
            )
            result = await self.app.push_screen_wait(modal)
            if result is None:
                return
            self._agents.update_agent(agent_id, **result)
            self._rebuild()

        self.app.run_worker(do_edit())

    def _agent_delete(self, agent_id: str) -> None:
        from ui.widgets.confirm_modal import ConfirmModal

        if not agent_id.startswith("custom:"):
            self.app.notify("Built-in agents cannot be deleted", severity="warning")
            return

        if self._agents is None:
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
        """Create a new agent via the schema-driven FormModal."""
        if self._agents is None:
            return

        ctx = getattr(self.app, "context", None)
        provider_opts = _provider_options(ctx)
        controls = self._build_controls(provider_opts)

        async def do_create() -> None:
            modal = FormModal("New Agent", controls)
            result = await self.app.push_screen_wait(modal)
            if result is None:
                return

            agent_id = self._agents.create_agent(
                name=result.get("name", ""),
                description="",
                template=result.get("template", ""),
                model=result.get("model", ""),
                provider=result.get("provider", ""),
                scope="global",
                tools=result.get("tools", ""),
                skills=result.get("skills", ""),
                temperature=result.get("temperature", ""),
                max_tool_iterations=result.get("max_tool_iterations", ""),
            )
            self._rebuild()
            self.app.notify(f"Created agent '{result.get('name', agent_id)}'")

        self.app.run_worker(do_create())

    # ------------------------------------------------------------------
    # Form control builder
    # ------------------------------------------------------------------

    @staticmethod
    def _build_controls(
        provider_options: list[str],
        defaults: dict[str, str] | None = None,
    ) -> list[FormControl]:
        """Build the list of FormControl descriptors for the agent form.

        Uses current provider options from the registry and optional
        default values (for editing existing agents).
        """
        d = defaults or {}

        controls: list[FormControl] = [
            FormControl(
                name="name",
                label="Name",
                default=d.get("name", ""),
                required=True,
            ),
        ]

        # Provider — use select if instances are configured, else text.
        if provider_options:
            controls.append(FormControl(
                name="provider",
                label="Provider",
                type="select",
                options=provider_options,
                default=d.get("provider", ""),
                required=False,
                placeholder="Default provider",
            ))
        else:
            controls.append(FormControl(
                name="provider",
                label="Provider instance name",
                default=d.get("provider", ""),
                required=False,
                placeholder="Leave empty for default",
            ))

        controls.extend([
            FormControl(
                name="model",
                label="Model",
                default=d.get("model", ""),
                required=False,
                placeholder="Leave empty for default",
            ),
            FormControl(
                name="template",
                label="System Prompt",
                type="textarea",
                default=d.get("template", ""),
                required=True,
            ),
            FormControl(
                name="tools",
                label="Tools (JSON list)",
                type="taglist",
                default=d.get("tools", ""),
                required=False,
                placeholder='e.g. ["read_file", "run_command"]',
            ),
            FormControl(
                name="skills",
                label="Skills (JSON list)",
                type="taglist",
                default=d.get("skills", ""),
                required=False,
                placeholder='e.g. ["git", "chat"]',
            ),
            FormControl(
                name="temperature",
                label="Temperature",
                type="number",
                default=d.get("temperature", ""),
                required=False,
                min=0,
                max=2,
                placeholder="0.0 – 2.0",
            ),
            FormControl(
                name="max_tool_iterations",
                label="Max Tool Iterations",
                type="number",
                default=d.get("max_tool_iterations", ""),
                required=False,
                min=1,
                placeholder="Default: 10",
            ),
        ])

        return controls