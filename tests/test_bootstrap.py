"""Tests for bootstrap (bootstrap.py)."""

import json
import os
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_file(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)


def _write_skill(tier_dir, name, description, body=""):
    skill_dir = os.path.join(tier_dir, name)
    os.makedirs(skill_dir, exist_ok=True)
    with open(os.path.join(skill_dir, "SKILL.md"), "w") as f:
        f.write(f"---\nname: {name}\ndescription: {description}\n---\n")
        if body:
            f.write(f"\n{body}\n")


def _write_tool_file(dir_path, filename, name, tags=None):
    """Write a Python file that uses @register_tool()."""
    tags_str = json.dumps(tags) if tags else "[]"
    with open(os.path.join(dir_path, filename), "w") as f:
        f.write(f"""
from core.tools import register_tool

@register_tool(
    name="{name}",
    tags={tags_str},
    description="A tool called {name}",
    parameters={{"type": "object", "properties": {{}}}}
)
def {name}():
    return "ok"
""")


# ---------------------------------------------------------------------------
# Bootstrap tests
# ---------------------------------------------------------------------------


class TestBootstrap:
    def test_returns_app_context(self, tmp_path):
        """Bootstrap.run() returns an AppContext with all services."""
        from bootstrap import Bootstrap
        from context import AppContext
        from core.tools import reset as reset_tools
        from core.commands import reset_commands

        reset_tools()
        reset_commands()

        # Set up tiers
        cody_dir = tmp_path / "cody"
        agents_dir = tmp_path / "agents"
        project_dir = tmp_path / "project"
        working_dir = tmp_path / "working"

        # Config file in cody tier
        cfg_dir = cody_dir / "config"
        os.makedirs(cfg_dir)
        _write_file(cfg_dir / "config.json", json.dumps({
            "session": {"provider": "ollama", "model": "test-model"},
            "database": {"path": str(working_dir / "data.db")},
            "skills": {"enabled": {}},
        }))

        # Skip agents tier (not needed)

        # Project tier config (overrides) — lives in working_dir/.agents/
        proj_cfg = working_dir / ".agents" / "config"
        os.makedirs(proj_cfg)
        _write_file(proj_cfg / "config.json", json.dumps({
            "session": {"model": "project-model"},
        }))

        # Skills in cody tier
        skills_dir = cody_dir / "skills"
        _write_skill(skills_dir, "coding", "A coding skill")

        # Tools in cody tier
        tools_dir = cody_dir / "tools"
        os.makedirs(tools_dir)
        _write_tool_file(tools_dir, "echo_tool.py", "echo", ["system"])

        # Skill tools
        skill_tools = os.path.join(skills_dir, "coding", "tools")
        os.makedirs(skill_tools)
        _write_tool_file(skill_tools, "code_tool.py", "code_review", ["skills"])

        # Bootstrap
        b = Bootstrap(
            working_directory=str(working_dir),
            cody_dir=str(cody_dir),
            agents_dir=str(agents_dir),
        )
        ctx = b.run()

        # Verify AppContext type
        assert isinstance(ctx, AppContext)

        # Verify config
        assert ctx.config is not None
        assert ctx.config.get("session.provider") == "ollama"
        assert ctx.config.get("session.model") == "project-model"  # project overrides cody

        # Verify skills
        assert ctx.skills is not None
        assert "coding" in ctx.skills.list_skills()
        skill = ctx.skills.get_skill("coding")
        assert skill.description == "A coding skill"

        # Verify tools were loaded
        from core.tools import get_tools, reset as reset_tools2
        all_tools = get_tools()
        tool_names = {t["function"]["name"] for t in all_tools}
        assert "echo" in tool_names
        assert "code_review" in tool_names

        # Verify database
        assert ctx.database is not None
        tables = ctx.database._execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        table_names = {r[0] for r in tables}
        assert "chats" in table_names
        assert "messages" in table_names

        # Verify leader
        assert ctx.leader is not None
        root = ctx.leader.get_root()
        assert "w" in root.children  # workspace chords registered

        # Verify working directory
        assert ctx.working_directory == str(working_dir)

        # Cleanup
        ctx.database.close()
        reset_tools2()


# ---------------------------------------------------------------------------
# Autouse — reset registries
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_registries():
    from core.tools import reset as reset_tools
    from core.commands import reset_commands
    from core.skills import skill_manager
    from core.leader import reset_leader

    reset_tools()
    reset_commands()
    skill_manager.reset()
    reset_leader()
