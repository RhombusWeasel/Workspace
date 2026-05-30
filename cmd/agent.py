"""/agent slash command — switch the current chat's agent mid-conversation.

Usage:
    /agent              — show the current agent and list available agents
    /agent <id>         — switch to the named agent
"""

from __future__ import annotations

from core.commands import register_command


@register_command(name="agent", description="Switch or list AI agents")
async def agent_cmd(app, args: str = "") -> str:
    """Switch the current chat's agent definition.

    When called with no arguments, shows the current agent and a list
    of available agents.  When called with an agent ID, re-wires the
    current chat to use that agent's system prompt, model, provider,
    tools, and skill configuration.
    """
    ctx = getattr(app, "context", None)
    if ctx is None or ctx.agents is None:
        return "Agent registry not available."

    agent_id = args.strip()

    if not agent_id:
        # Show current default and list all agents.
        current_id = ctx.config.get("agent.default_id", "default")
        agents = ctx.agents.list_agents()
        lines = [f"Current agent: {current_id}", "", "Available agents:"]
        for a in agents:
            marker = " ←" if a["id"] == current_id else ""
            model_info = f" (model: {a['model']})" if a.get("model") else ""
            provider_info = f" (provider: {a['provider']})" if a.get("provider") else ""
            lines.append(f"  {a['id']}: {a['name']}{model_info}{provider_info}{marker}")
        return "\n".join(lines)

    # Validate the agent ID exists.
    agent_def = ctx.agents.get_agent(agent_id)
    if agent_def is None:
        agents = ctx.agents.list_agents()
        available = ", ".join(a["id"] for a in agents)
        return f"Agent '{agent_id}' not found. Available: {available}"

    # Try to switch the current chat's agent.
    switched = False
    try:
        from skills.chat.chat_manager import ChatManager
        chat_managers = app.query(ChatManager)
        if chat_managers:
            mgr = chat_managers.last()
            mgr._wire_agent(ctx)
            switched = True
    except Exception:
        pass

    if switched:
        model_info = f" (model: {agent_def['model']})" if agent_def.get("model") else ""
        provider_info = f" (provider: {agent_def['provider']})" if agent_def.get("provider") else ""
        return f"Switched to agent '{agent_id}': {agent_def['name']}{model_info}{provider_info}"
    else:
        return f"Agent '{agent_id}' found but no active chat to switch."