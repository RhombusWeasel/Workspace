"""Tests for the agent registry — AgentManager, render, CRUD, dynamic providers, resolve helpers."""

import json
import pytest
from core.database import DatabaseManager
from core.agent_registry import (
    AgentManager,
    render_template,
    DEFAULT_CHAT_AGENT,
    DEFAULT_INLINE_SUGGEST_AGENT,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db(tmp_path):
    """Create a DatabaseManager with a temp database."""
    db_path = str(tmp_path / "test.db")
    return DatabaseManager(db_path)


@pytest.fixture
def mgr(db):
    """Create an AgentManager with default agents seeded."""
    return AgentManager(db)


# ---------------------------------------------------------------------------
# render_template — unit tests
# ---------------------------------------------------------------------------


class TestRenderTemplate:
    def test_simple_substitution(self):
        assert render_template("Hello {{name}}!", {"name": "World"}) == "Hello World!"

    def test_multiple_keys(self):
        result = render_template(
            "{{greeting}} {{name}}.", {"greeting": "Hi", "name": "Alice"}
        )
        assert result == "Hi Alice."

    def test_missing_key_left_unchanged(self):
        assert render_template("Hello {{name}}!", {}) == "Hello {{name}}!"

    def test_dotted_key_substitution(self):
        result = render_template("{{skills.catalog}}", {"skills.catalog": "<xml/>"})
        assert result == "<xml/>"

    def test_dotted_key_missing_left_unchanged(self):
        assert render_template("{{skills.catalog}}", {}) == "{{skills.catalog}}"

    def test_no_placeholders(self):
        assert render_template("Plain text", {}) == "Plain text"

    def test_empty_template(self):
        assert render_template("", {}) == ""

    def test_key_present_but_empty_string(self):
        assert render_template("Hello {{name}}!", {"name": ""}) == "Hello !"


# ---------------------------------------------------------------------------
# AgentManager — CRUD
# ---------------------------------------------------------------------------


class TestAgentManagerCRUD:
    def test_defaults_seeded(self, mgr):
        """Default agents are seeded on creation."""
        default = mgr.get_agent("default")
        assert default is not None
        assert default["name"] == "Default Assistant"
        assert "{{skills}}" in default["template"]

    def test_inline_suggest_seeded(self, mgr):
        inline = mgr.get_agent("inline-suggest")
        assert inline is not None
        assert inline["name"] == "Inline Suggest"

    def test_idempotent_seeding(self, db):
        """Seeding defaults twice does not overwrite."""
        mgr1 = AgentManager(db)
        mgr1.update_agent("default", template="MODIFIED")
        mgr2 = AgentManager(db)  # re-seed
        agent = mgr2.get_agent("default")
        assert agent["template"] == "MODIFIED"  # not overwritten

    def test_create_agent(self, mgr):
        aid = mgr.create_agent(
            name="Code Reviewer",
            description="Reviews code for bugs",
            template="You are a code reviewer. Focus on {{focus}}.",
        )
        assert aid.startswith("custom:")
        row = mgr.get_agent(aid)
        assert row is not None
        assert row["name"] == "Code Reviewer"
        assert row["scope"] == "global"

    def test_create_agent_with_provider(self, mgr):
        aid = mgr.create_agent(
            name="Cloud Agent",
            template="You use the cloud model.",
            provider="ollama-cloud",
            model="deepseek-v4-pro:cloud",
        )
        row = mgr.get_agent(aid)
        assert row["provider"] == "ollama-cloud"
        assert row["model"] == "deepseek-v4-pro:cloud"

    def test_create_agent_with_tools(self, mgr):
        aid = mgr.create_agent(
            name="Restricted Agent",
            template="Limited tools.",
            tools='["read_file", "run_command"]',
        )
        row = mgr.get_agent(aid)
        assert row["tools"] == '["read_file", "run_command"]'

    def test_create_agent_with_skills(self, mgr):
        aid = mgr.create_agent(
            name="Git Specialist",
            template="Git expert.",
            skills='["git"]',
        )
        row = mgr.get_agent(aid)
        assert row["skills"] == '["git"]'

    def test_create_agent_custom_id(self, mgr):
        aid = mgr.create_agent(
            name="Test",
            template="Test agent",
            agent_id="my-custom-id",
        )
        assert aid == "my-custom-id"

    def test_get_agent_not_found(self, mgr):
        assert mgr.get_agent("nonexistent") is None

    def test_list_agents(self, mgr):
        agents = mgr.list_agents()
        ids = [a["id"] for a in agents]
        assert "default" in ids
        assert "inline-suggest" in ids

    def test_list_agents_by_scope(self, mgr):
        mgr.create_agent(name="Project", template="T", scope="project")
        global_agents = mgr.list_agents(scope="global")
        project_agents = mgr.list_agents(scope="project")
        assert all(a["scope"] == "global" for a in global_agents)
        assert all(a["scope"] == "project" for a in project_agents)

    def test_update_agent(self, mgr):
        mgr.update_agent("default", name="Renamed", description="New desc")
        row = mgr.get_agent("default")
        assert row["name"] == "Renamed"
        assert row["description"] == "New desc"

    def test_update_agent_provider(self, mgr):
        mgr.update_agent("default", provider="ollama-cloud", model="llama3")
        row = mgr.get_agent("default")
        assert row["provider"] == "ollama-cloud"
        assert row["model"] == "llama3"

    def test_update_agent_ignores_unknown_keys(self, mgr):
        mgr.update_agent("default", nonexistent_key="ignored")
        row = mgr.get_agent("default")
        assert "nonexistent_key" not in row

    def test_delete_agent(self, mgr):
        mgr.create_agent(name="ToDelete", template="T", agent_id="del-me")
        assert mgr.get_agent("del-me") is not None
        mgr.delete_agent("del-me")
        assert mgr.get_agent("del-me") is None

    def test_model_field(self, mgr):
        aid = mgr.create_agent(name="Specialist", template="T", model="llama3")
        row = mgr.get_agent(aid)
        assert row["model"] == "llama3"

    def test_new_schema_fields_default_empty(self, mgr):
        """New fields (provider, tools, skills, temperature, max_tool_iterations)
        default to empty string when not provided."""
        aid = mgr.create_agent(name="Test", template="T")
        row = mgr.get_agent(aid)
        assert row["provider"] == ""
        assert row["tools"] == ""
        assert row["skills"] == ""
        assert row["temperature"] == ""
        assert row["max_tool_iterations"] == ""


# ---------------------------------------------------------------------------
# AgentManager — Rendering
# ---------------------------------------------------------------------------


class TestAgentManagerRender:
    def test_render_default_template(self, mgr):
        """Rendering the default agent resolves dynamic placeholders."""
        class FakeCtx:
            working_directory = "/home/user/project"
            config = None
            agents = None
            providers = None

        # Register the same providers that bootstrap registers
        import os
        from datetime import datetime, timezone
        mgr.register_dynamic(
            "working_directory",
            lambda ctx: ctx.working_directory if ctx and ctx.working_directory else os.getcwd(),
        )
        mgr.register_dynamic(
            "project_name",
            lambda ctx: os.path.basename(ctx.working_directory) if ctx and ctx.working_directory else "unknown",
        )
        mgr.register_dynamic(
            "date",
            lambda ctx: datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        )
        # Skills provider returns a dict so {{skills}} resolves via __default__
        mgr.register_dynamic(
            "skills",
            lambda ctx: {
                "__default__": "<available_skills/>\n",
                "catalog": "<available_skills/>\n",
                "names": "git, chat",
            },
        )

        result = mgr.render("default", FakeCtx())
        # All placeholders should be resolved
        assert "{{date}}" not in result
        assert "{{working_directory}}" not in result
        assert "{{project_name}}" not in result
        # Working directory and project name should appear
        assert "/home/user/project" in result
        assert "project" in result

    def test_render_inline_suggest(self, mgr):
        """Inline suggest agent has no placeholders to resolve."""
        class FakeCtx:
            working_directory = "/tmp"
            config = None
            agents = None
            providers = None

        result = mgr.render("inline-suggest", FakeCtx())
        # This agent has no {{key}} placeholders
        assert "{{" not in result

    def test_render_missing_agent_raises(self, mgr):
        class FakeCtx:
            working_directory = "/tmp"
            config = None
            agents = None
            providers = None

        with pytest.raises(ValueError, match="not found"):
            mgr.render("nonexistent", FakeCtx())

    def test_render_with_extra_vars(self, mgr):
        """Extra vars take priority over dynamic providers."""
        mgr.create_agent(
            name="Test",
            template="Hello {{project_name}}!",
            agent_id="test-extra",
        )

        class FakeCtx:
            working_directory = "/home/user/myproject"
            config = None
            agents = None
            providers = None

        result = mgr.render("test-extra", FakeCtx(), extra_vars={"project_name": "Override"})
        assert result == "Hello Override!"

    def test_render_unresolved_key_left_unchanged(self, mgr):
        mgr.create_agent(
            name="Test",
            template="Hello {{unknown_key}}!",
            agent_id="test-unknown",
        )

        class FakeCtx:
            working_directory = "/tmp"
            config = None
            agents = None
            providers = None

        result = mgr.render("test-unknown", FakeCtx())
        assert result == "Hello {{unknown_key}}!"


# ---------------------------------------------------------------------------
# AgentManager — Dynamic providers
# ---------------------------------------------------------------------------


class TestDynamicProviders:
    def test_simple_string_provider(self, mgr):
        mgr.register_dynamic("env", lambda ctx: "production")

        mgr.create_agent(
            name="Test",
            template="Running in {{env}}.",
            agent_id="test-env",
        )

        class FakeCtx:
            pass

        result = mgr.render("test-env", FakeCtx())
        assert result == "Running in production."

    def test_dict_provider_default_key(self, mgr):
        """{{skills}} resolves to __default__ when the provider returns a dict."""
        mgr.register_dynamic("skills", lambda ctx: {
            "__default__": "<skills-xml/>",
            "catalog": "<skills-xml/>",
            "names": "git, chat",
        })

        mgr.create_agent(
            name="Test",
            template="Skills: {{skills}}",
            agent_id="test-skills-default",
        )

        class FakeCtx:
            pass

        result = mgr.render("test-skills-default", FakeCtx())
        assert result == "Skills: <skills-xml/>"

    def test_dict_provider_nested_key(self, mgr):
        """{{skills.names}} resolves by walking the dict."""
        mgr.register_dynamic("skills", lambda ctx: {
            "__default__": "<skills-xml/>",
            "names": "git, chat",
        })

        mgr.create_agent(
            name="Test",
            template="Names: {{skills.names}}",
            agent_id="test-skills-names",
        )

        class FakeCtx:
            pass

        result = mgr.render("test-skills-names", FakeCtx())
        assert result == "Names: git, chat"

    def test_dict_provider_deep_nested(self, mgr):
        """Dotted keys walk deeply into nested dicts."""
        mgr.register_dynamic("data", lambda ctx: {
            "level1": {
                "level2": "deep_value",
            },
        })

        mgr.create_agent(
            name="Test",
            template="Value: {{data.level1.level2}}",
            agent_id="test-deep",
        )

        class FakeCtx:
            pass

        result = mgr.render("test-deep", FakeCtx())
        assert result == "Value: deep_value"

    def test_dict_provider_missing_path_falls_back_to_default(self, mgr):
        """If a nested path doesn't exist, fall back to __default__."""
        mgr.register_dynamic("skills", lambda ctx: {
            "__default__": "fallback",
            "catalog": "<xml/>",
        })

        mgr.create_agent(
            name="Test",
            template="{{skills.nonexistent}}",
            agent_id="test-fallback",
        )

        class FakeCtx:
            pass

        result = mgr.render("test-fallback", FakeCtx())
        assert result == "fallback"

    def test_ctx_passed_to_provider(self, mgr):
        """Dynamic providers receive the AppContext."""
        class FakeCtx:
            working_directory = "/home/user/myproject"

        mgr.register_dynamic(
            "project_name",
            lambda ctx: ctx.working_directory.split("/")[-1],
        )

        mgr.create_agent(
            name="Test",
            template="Project: {{project_name}}",
            agent_id="test-ctx",
        )

        result = mgr.render("test-ctx", FakeCtx())
        assert result == "Project: myproject"

    def test_multiple_providers_in_template(self, mgr):
        """Multiple different {{key}} placeholders resolved in order."""
        mgr.register_dynamic("date", lambda ctx: "2025-01-15")
        mgr.register_dynamic("env", lambda ctx: "production")

        mgr.create_agent(
            name="Test",
            template="Date: {{date}}, Env: {{env}}",
            agent_id="test-multi",
        )

        class FakeCtx:
            pass

        result = mgr.render("test-multi", FakeCtx())
        assert result == "Date: 2025-01-15, Env: production"

    def test_extra_vars_override_provider(self, mgr):
        """Extra vars override dynamic providers."""
        mgr.register_dynamic("env", lambda ctx: "staging")

        mgr.create_agent(
            name="Test",
            template="Env: {{env}}",
            agent_id="test-override",
        )

        class FakeCtx:
            pass

        result = mgr.render("test-override", FakeCtx(), extra_vars={"env": "production"})
        assert result == "Env: production"


# ---------------------------------------------------------------------------
# AgentManager — Resolve helpers
# ---------------------------------------------------------------------------


class TestResolveHelpers:
    def test_resolve_model_from_agent(self, mgr):
        """Agent's model field takes priority."""
        class FakeCtx:
            config = None
        agent_def = {"model": "llama3"}
        assert mgr.resolve_model(agent_def, FakeCtx()) == "llama3"

    def test_resolve_model_from_config(self, mgr):
        """Falls back to session.model when agent has no model."""
        class FakeConfig:
            def get(self, key, default=""):
                if key == "session.model":
                    return "deepseek-r1"
                return default
        class FakeCtx:
            config = FakeConfig()
        agent_def = {"model": ""}
        assert mgr.resolve_model(agent_def, FakeCtx()) == "deepseek-r1"

    def test_resolve_model_empty(self, mgr):
        """Returns empty string when neither agent nor config specifies a model."""
        class FakeCtx:
            config = None
        agent_def = {"model": ""}
        assert mgr.resolve_model(agent_def, FakeCtx()) == ""

    def test_resolve_provider_name_from_agent(self, mgr):
        """Agent's provider field takes priority."""
        class FakeConfig:
            def get(self, key, default=""):
                return default
        class FakeCtx:
            config = FakeConfig()
        agent_def = {"provider": "ollama-cloud"}
        assert mgr.resolve_provider_name(agent_def, FakeCtx()) == "ollama-cloud"

    def test_resolve_provider_name_from_config(self, mgr):
        """Falls back to session.default_provider."""
        class FakeConfig:
            def get(self, key, default=""):
                if key == "session.default_provider":
                    return "my-ollama"
                return default
        class FakeCtx:
            config = FakeConfig()
        agent_def = {"provider": ""}
        assert mgr.resolve_provider_name(agent_def, FakeCtx()) == "my-ollama"

    def test_resolve_provider_name_default(self, mgr):
        """Falls back to 'ollama' when nothing specifies a provider."""
        class FakeCtx:
            config = None
        agent_def = {"provider": ""}
        assert mgr.resolve_provider_name(agent_def, FakeCtx()) == "ollama"

    def test_resolve_tools_empty(self, mgr):
        """Empty tools field returns None (all tools)."""
        assert mgr.resolve_tools({"tools": ""}) is None

    def test_resolve_tools_valid_json(self, mgr):
        """Valid JSON list of tools is parsed."""
        assert mgr.resolve_tools({"tools": '["read_file", "run_command"]'}) == ["read_file", "run_command"]

    def test_resolve_tools_invalid_json(self, mgr):
        """Invalid JSON returns None."""
        assert mgr.resolve_tools({"tools": "not json"}) is None

    def test_resolve_tools_empty_list(self, mgr):
        """Empty JSON list [] returns None (use all tools)."""
        assert mgr.resolve_tools({"tools": "[]"}) is None

    def test_resolve_skills_empty(self, mgr):
        """Empty skills field returns None (all skills)."""
        assert mgr.resolve_skills({"skills": ""}) is None

    def test_resolve_skills_valid_json(self, mgr):
        """Valid JSON list of skills is parsed."""
        assert mgr.resolve_skills({"skills": '["git", "chat"]'}) == ["git", "chat"]

    def test_resolve_temperature_valid(self, mgr):
        assert mgr.resolve_temperature({"temperature": "0.7"}) == 0.7

    def test_resolve_temperature_empty(self, mgr):
        assert mgr.resolve_temperature({"temperature": ""}) is None

    def test_resolve_temperature_invalid(self, mgr):
        assert mgr.resolve_temperature({"temperature": "hot"}) is None

    def test_resolve_max_tool_iterations_valid(self, mgr):
        assert mgr.resolve_max_tool_iterations({"max_tool_iterations": "5"}) == 5

    def test_resolve_max_tool_iterations_empty(self, mgr):
        assert mgr.resolve_max_tool_iterations({"max_tool_iterations": ""}) is None

    def test_resolve_max_tool_iterations_zero(self, mgr):
        assert mgr.resolve_max_tool_iterations({"max_tool_iterations": "0"}) is None


# ---------------------------------------------------------------------------
# Built-in providers registered by bootstrap
# ---------------------------------------------------------------------------


class TestBuiltinProviders:
    def test_working_directory_provider(self, mgr):
        """The working_directory provider resolves correctly."""
        class FakeCtx:
            working_directory = "/home/user/myproject"
            config = None
            agents = None
            providers = None

        # Simulate bootstrap provider registration
        import os
        mgr.register_dynamic(
            "working_directory",
            lambda ctx: ctx.working_directory if ctx and ctx.working_directory else os.getcwd(),
        )
        mgr.register_dynamic(
            "project_name",
            lambda ctx: os.path.basename(ctx.working_directory) if ctx and ctx.working_directory else "unknown",
        )

        mgr.create_agent(
            name="Test",
            template="Dir: {{working_directory}}, Name: {{project_name}}",
            agent_id="test-wd",
        )

        result = mgr.render("test-wd", FakeCtx())
        assert result == "Dir: /home/user/myproject, Name: myproject"

    def test_date_provider(self, mgr):
        """The date provider returns a date string."""
        from datetime import datetime, timezone

        mgr.register_dynamic("date", lambda ctx: datetime.now(timezone.utc).strftime("%Y-%m-%d"))

        mgr.create_agent(
            name="Test",
            template="Date: {{date}}",
            agent_id="test-date",
        )

        class FakeCtx:
            pass

        result = mgr.render("test-date", FakeCtx())
        # Should contain a date in YYYY-MM-DD format
        import re
        assert re.match(r"Date: \d{4}-\d{2}-\d{2}", result)


# ---------------------------------------------------------------------------
# Legacy migration
# ---------------------------------------------------------------------------


class TestLegacyMigration:
    def test_migrate_from_prompts_table(self, tmp_path):
        """Data from a legacy prompts table is migrated to the new agents table."""
        db_path = str(tmp_path / "legacy.db")
        db = DatabaseManager(db_path)

        # Simulate an old prompts table by creating one directly.
        try:
            db._execute(
                "CREATE TABLE IF NOT EXISTS prompts ("
                "id TEXT PRIMARY KEY, name TEXT, description TEXT, "
                "template TEXT, model TEXT, scope TEXT, "
                "created_at TEXT, updated_at TEXT)"
            )
            db._execute(
                "INSERT INTO prompts VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("my-prompt", "My Prompt", "A test", "Hello {{name}}", "", "global",
                 "2025-01-01", "2025-01-01"),
            )
        except Exception:
            pass

        # Creating AgentManager should trigger migration.
        mgr = AgentManager(db)

        # The migrated prompt should now be in the agents table.
        agent = mgr.get_agent("my-prompt")
        assert agent is not None
        assert agent["name"] == "My Prompt"
        assert agent["template"] == "Hello {{name}}"
        assert agent["provider"] == ""  # new field, empty default

        # The old prompts table should be dropped.
        tables = db._execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='prompts'"
        )
        assert not tables  # prompts table should no longer exist