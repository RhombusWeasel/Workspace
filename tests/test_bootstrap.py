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
        workspace_dir = tmp_path / "workspace"
        agents_dir = tmp_path / "agents"
        project_dir = tmp_path / "project"
        working_dir = tmp_path / "working"

        # Config file in bundled tier
        cfg_dir = workspace_dir / "config"
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

        # Skills in bundled tier
        skills_dir = workspace_dir / "skills"
        _write_skill(skills_dir, "coding", "A coding skill")

        # Tools in bundled tier
        tools_dir = workspace_dir / "tools"
        os.makedirs(tools_dir)
        _write_tool_file(tools_dir, "echo_tool.py", "echo", ["system"])

        # Skill tools
        skill_tools = os.path.join(skills_dir, "coding", "tools")
        os.makedirs(skill_tools)
        _write_tool_file(skill_tools, "code_tool.py", "code_review", ["skills"])

        # Skill commands
        skill_cmds = os.path.join(skills_dir, "coding", "cmd")
        os.makedirs(skill_cmds)
        _write_file(
            os.path.join(skill_cmds, "test_cmd.py"),
            'from core.commands import register_command\n'
            '\n'
            '@register_command(name="test_cmd", description="A test skill command")\n'
            'async def test_cmd(app, args: str) -> str:\n'
            '    return "test_cmd result"\n',
        )

        # Set up tcss files in mock bundled tier
        ui_dir = workspace_dir / "ui" / "workspace"
        os.makedirs(ui_dir)
        _write_file(ui_dir / "styles.tcss", "Button {}")

        # Monkeypatch paths so collect_tcss finds our mock tiers
        monkeypatch.setattr("core.paths.workspace_dir", lambda: str(workspace_dir))
        monkeypatch.setattr("core.paths.agents_dir", lambda: str(agents_dir))

        # Bootstrap
        b = Bootstrap(
            working_directory=str(working_dir),
            workspace_dir=str(workspace_dir),
            agents_dir=str(agents_dir),
        )
        ctx = b.run()

        # Verify AppContext type
        assert isinstance(ctx, AppContext)

        # Verify config
        assert ctx.config is not None
        assert ctx.config.get("session.provider") == "ollama"
        assert ctx.config.get("session.model") == "project-model"  # project overrides bundled

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

        # Verify commands were loaded from core cmd/ and skill cmd/ dirs
        from core.commands import get_commands
        cmds = get_commands()
        cmd_names = set(cmds.keys())
        assert "test_cmd" in cmd_names  # loaded from skill cmd/ dir

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
        # With monkeypatched paths, we should see bundled tier tcss files
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

        workspace_dir = tmp_path / "workspace"
        agents_dir = tmp_path / "agents"
        working_dir = tmp_path / "working"
        os.makedirs(working_dir)  # needed for SQLite db creation

        # Create a minimal bundled config.json with base defaults
        cfg_dir = workspace_dir / "config"
        os.makedirs(cfg_dir)
        _write_file(cfg_dir / "config.json", json.dumps({
            "session": {"provider": "ollama", "model": "bundled-model"},
            "ollama": {"base_url": "http://localhost:11434"},
        }))

        # Also register some module-level defaults (simulating module registration)
        register_defaults({"skills": {"enabled": {"coding": True}}})
        register_defaults({"ui": {"sidebar_width": 40}})

        # Create a minimal tcss dir so collect_tcss doesn't fail
        ui_dir = workspace_dir / "ui" / "workspace"
        os.makedirs(ui_dir)
        _write_file(ui_dir / "styles.tcss", "Button {}")

        monkeypatch.setattr("core.paths.workspace_dir", lambda: str(workspace_dir))
        monkeypatch.setattr("core.paths.agents_dir", lambda: str(agents_dir))

        b = Bootstrap(
            working_directory=str(working_dir),
            workspace_dir=str(workspace_dir),
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

        workspace_dir = tmp_path / "workspace"
        agents_dir = tmp_path / "agents"
        working_dir = tmp_path / "working"
        os.makedirs(working_dir)  # needed for SQLite db creation

        # Bundled config
        cfg_dir = workspace_dir / "config"
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

        ui_dir = workspace_dir / "ui" / "workspace"
        os.makedirs(ui_dir)
        _write_file(ui_dir / "styles.tcss", "Button {}")

        monkeypatch.setattr("core.paths.workspace_dir", lambda: str(workspace_dir))
        monkeypatch.setattr("core.paths.agents_dir", lambda: str(agents_dir))

        b = Bootstrap(
            working_directory=str(working_dir),
            workspace_dir=str(workspace_dir),
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


class TestSkillLoadErrorIsolation:
    """A skill with __init__.py that fails to import should be skipped, not crash the app."""

    def test_broken_skill_init_skipped_gracefully(self, tmp_path, monkeypatch, capsys):
        """A skill whose __init__.py raises ImportError is skipped."""
        from bootstrap import Bootstrap
        from core.tools import reset as reset_tools
        from core.commands import reset_commands
        from core.config import reset_registered_defaults

        reset_tools()
        reset_commands()
        reset_registered_defaults()

        workspace_dir = tmp_path / "workspace"
        agents_dir = tmp_path / "agents"
        working_dir = tmp_path / "working"
        os.makedirs(working_dir)

        # Bundled config
        cfg_dir = workspace_dir / "config"
        os.makedirs(cfg_dir)
        _write_file(cfg_dir / "config.json", json.dumps({
            "session": {"provider": "ollama"},
        }))

        # Create a broken skill with __init__.py in the bundled tier
        broken_skill_dir = workspace_dir / "skills" / "broken_skill"
        os.makedirs(broken_skill_dir)
        _write_file(
            broken_skill_dir / "SKILL.md",
            "---\nname: broken_skill\ndescription: A broken skill\n---",
        )
        _write_file(
            broken_skill_dir / "__init__.py",
            "import nonexistent_package\n",  # will raise ModuleNotFoundError
        )

        # Need tcss
        ui_dir = workspace_dir / "ui" / "workspace"
        os.makedirs(ui_dir)
        _write_file(ui_dir / "styles.tcss", "Button {}")

        monkeypatch.setattr("core.paths.workspace_dir", lambda: str(workspace_dir))
        monkeypatch.setattr("core.paths.agents_dir", lambda: str(agents_dir))

        b = Bootstrap(
            working_directory=str(working_dir),
            workspace_dir=str(workspace_dir),
            agents_dir=str(agents_dir),
        )

        # Should NOT raise — broken skill is skipped
        ctx = b.run()
        assert ctx is not None

        # Should print a warning to stderr
        captured = capsys.readouterr()
        assert "broken_skill" in captured.err
        assert "skipping" in captured.err.lower() or "Skipping" in captured.err

        ctx.database.close()
        reset_tools()

    def test_skill_services_wired_into_context(self, tmp_path, monkeypatch):
        """A skill declaring SKILL_SERVICES has those services wired into AppContext."""
        from bootstrap import Bootstrap
        from core.tools import reset as reset_tools
        from core.commands import reset_commands
        from core.config import reset_registered_defaults

        reset_tools()
        reset_commands()
        reset_registered_defaults()

        workspace_dir = tmp_path / "workspace"
        agents_dir = tmp_path / "agents"
        working_dir = tmp_path / "working"
        os.makedirs(working_dir)

        # Bundled config
        cfg_dir = workspace_dir / "config"
        os.makedirs(cfg_dir)
        _write_file(cfg_dir / "config.json", json.dumps({
            "session": {"provider": "ollama"},
        }))

        # Create a skill with SKILL_SERVICES
        svc_skill_dir = workspace_dir / "skills" / "svc_skill"
        os.makedirs(svc_skill_dir)
        _write_file(
            svc_skill_dir / "SKILL.md",
            "---\nname: svc_skill\ndescription: A skill with services\n---",
        )
        _write_file(
            svc_skill_dir / "__init__.py",
            'SKILL_SERVICES = {"test_service": lambda cfg, vault: "wired_value"}\n',
        )

        # Need tcss
        ui_dir = workspace_dir / "ui" / "workspace"
        os.makedirs(ui_dir)
        _write_file(ui_dir / "styles.tcss", "Button {}")

        monkeypatch.setattr("core.paths.workspace_dir", lambda: str(workspace_dir))
        monkeypatch.setattr("core.paths.agents_dir", lambda: str(agents_dir))

        b = Bootstrap(
            working_directory=str(working_dir),
            workspace_dir=str(workspace_dir),
            agents_dir=str(agents_dir),
        )

        ctx = b.run()
        assert ctx is not None
        assert ctx.services.get("test_service") == "wired_value"

        ctx.database.close()
        reset_tools()
