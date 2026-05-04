"""Activate skill tool — loads a SKILL.md file's content into the agent's context.

The agent calls this when it needs detailed instructions for a specific
skill.  The tool returns the skill's markdown body, which the agent then
incorporates into its system prompt / conversation context.

Registered at import time via ``@register_tool()``.
"""

from __future__ import annotations

from core.tools import register_tool
from core.skills import skill_manager


@register_tool(
    name="activate_skill",
    tags=["skills"],
    description=(
        "Load the full markdown content of a skill's SKILL.md file.  "
        "Use this when you need detailed instructions for a specific skill. "
        "The skill must be registered in the skill catalog."
    ),
    parameters={
        "type": "object",
        "properties": {
            "skill_name": {
                "type": "string",
                "description": "The name of the skill to activate (as shown in the catalog).",
            },
        },
        "required": ["skill_name"],
    },
)
def activate_skill(skill_name: str) -> str:
    """Return the full markdown body of *skill_name*'s SKILL.md.

    If the skill is not found in the catalog, returns an error string.
    The agent should feed this content back into its context so future
    turns can reference it.
    """
    skill = skill_manager.get_skill(skill_name)
    if skill is None:
        available = ", ".join(skill_manager.list_skills())
        return (
            f"Skill '{skill_name}' not found. "
            f"Available skills: {available}"
        )

    body = skill_manager.get_skill_body(skill_name)
    if not body:
        return f"Skill '{skill_name}' has no body content."

    return (
        f"# Skill: {skill.name}\n"
        f"Description: {skill.description}\n\n"
        f"{body}"
    )
