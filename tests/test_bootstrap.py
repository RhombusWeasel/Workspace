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
    def test_returns_app_context(self, tmp_path, monkeypatch):
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

        # Set up tcss files in mock cody tier
        ui_dir = cody_dir / "ui" / "workspace"
        os.makedirs(ui_dir)
        _write_file(ui_dir / "styles.tcss", "Button {}")

        # Monkeypatch paths so collect_tcss finds our mock tiers
        monkeypatch.setattr("core.paths.cody_dir", lambda: str(cody_dir))
        monkeypatch.setattr("core.paths.agents_dir", lambda: str(agents_dir))

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

        # Verify vault
        assert ctx.vault is not None
        assert not ctx.vault.is_locked()
        assert ctx.vault.working_dir == str(working_dir)

        # Verify working directory
        assert ctx.working_directory == str(working_dir)

        # Verify CSS paths
        assert isinstance(ctx.css_paths, list)
        # With monkeypatched paths, we should see cody tier tcss files
        assert len(ctx.css_paths) >= 1
        assert any("styles.tcss" in p for p in ctx.css_paths)

        # Cleanup
        ctx.database.close()
        reset_tools2()

    def test_defaults_applied_when_no_config_files(self, tmp_path, monkeypatch):
        """Bootstrap applies bundled and registered defaults when no JSON files exist."""
        from bootstrap import Bootstrap
        from core.tools import reset as reset_tools
        from core.commands import reset_commands
        from core.config import (
            register_defaults,
            reset_registered_defaults,
        )

        reset_tools()
        reset_commands()
        reset_registered_defaults()

        cody_dir = tmp_path / "cody"
        agents_dir = tmp_path / "agents"
        working_dir = tmp_path / "working"
        os.makedirs(working_dir)  # needed for SQLite db creation

        # Create a minimal bundled config.json with base defaults
        cfg_dir = cody_dir / "config"
        os.makedirs(cfg_dir)
        _write_file(cfg_dir / "config.json", json.dumps({
            "session": {"provider": "ollama", "model": "bundled-model"},
            "ollama": {"base_url": "http://localhost:11434"},
        }))

        # Also register some module-level defaults (simulating module registration)
        register_defaults({"skills": {"enabled": {"coding": True}}})
        register_defaults({"ui": {"sidebar_width": 40}})

        # Create a minimal tcss dir so collect_tcss doesn't fail
        ui_dir = cody_dir / "ui" / "workspace"
        os.makedirs(ui_dir)
        _write_file(ui_dir / "styles.tcss", "Button {}")

        monkeypatch.setattr("core.paths.cody_dir", lambda: str(cody_dir))
        monkeypatch.setattr("core.paths.agents_dir", lambda: str(agents_dir))

        b = Bootstrap(
            working_directory=str(working_dir),
            cody_dir=str(cody_dir),
            agents_dir=str(agents_dir),
        )
        ctx = b.run()

        # Bundled config provides these
        assert ctx.config.get("session.provider") == "ollama"
        assert ctx.config.get("session.model") == "bundled-model"
        assert ctx.config.get("ollama.base_url") == "http://localhost:11434"

        # Module-registered defaults fill these (not in bundled config)
        assert ctx.config.get("skills.enabled") == {"coding": True}
        assert ctx.config.get("ui.sidebar_width") == 40

        ctx.database.close()
        reset_tools()

    def test_project_config_overrides_defaults(self, tmp_path, monkeypatch):
        """Project-tier config overrides both bundled defaults and registered defaults."""
        from bootstrap import Bootstrap
        from core.tools import reset as reset_tools
        from core.commands import reset_commands
        from core.config import (
            register_defaults,
            reset_registered_defaults,
        )

        reset_tools()
        reset_commands()
        reset_registered_defaults()

        cody_dir = tmp_path / "cody"
        agents_dir = tmp_path / "agents"
        working_dir = tmp_path / "working"
        os.makedirs(working_dir)  # needed for SQLite db creation

        # Bundled config
        cfg_dir = cody_dir / "config"
        os.makedirs(cfg_dir)
        _write_file(cfg_dir / "config.json", json.dumps({
            "session": {"provider": "ollama", "model": "bundled-model"},
        }))

        # Project config overrides
        proj_cfg = working_dir / ".agents" / "config"
        os.makedirs(proj_cfg)
        _write_file(proj_cfg / "config.json", json.dumps({
            "session": {"model": "project-override"},
        }))

        # Module registers a default that project does NOT override
        register_defaults({"skills": {"enabled": {"coding": False}}})

        ui_dir = cody_dir / "ui" / "workspace"
        os.makedirs(ui_dir)
        _write_file(ui_dir / "styles.tcss", "Button {}")

        monkeypatch.setattr("core.paths.cody_dir", lambda: str(cody_dir))
        monkeypatch.setattr("core.paths.agents_dir", lambda: str(agents_dir))

        b = Bootstrap(
            working_directory=str(working_dir),
            cody_dir=str(cody_dir),
            agents_dir=str(agents_dir),
        )
        ctx = b.run()

        # Project overrides the bundled default for model
        assert ctx.config.get("session.provider") == "ollama"  # from bundled
        assert ctx.config.get("session.model") == "project-override"  # from project

        # Module default still applies (project didn't override it)
        assert ctx.config.get("skills.enabled") == {"coding": False}

        ctx.database.close()
        reset_tools()


# ---------------------------------------------------------------------------
# Autouse — reset registries
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_registries():
    from core.tools import reset as reset_tools
    from core.commands import reset_commands
    from core.skills import skill_manager
    from core.leader import reset_leader
    from core.config import reset_registered_defaults

    reset_tools()
    reset_commands()
    skill_manager.reset()
    reset_leader()
    reset_registered_defaults()
