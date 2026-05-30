"""Tests for the prompt registry — PromptManager, render, CRUD, dynamic providers."""

import pytest
from core.database import DatabaseManager
from core.prompt_registry import (
    PromptManager,
    render_template,
    DEFAULT_CHAT_PROMPT,
    DEFAULT_INLINE_SUGGEST_PROMPT,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db(tmp_path):
    """Create an in-memory DatabaseManager with the prompts table."""
    db_path = str(tmp_path / "test.db")
    return DatabaseManager(db_path)


@pytest.fixture
def mgr(db):
    """Create a PromptManager with default prompts seeded."""
    return PromptManager(db)


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
# PromptManager — CRUD
# ---------------------------------------------------------------------------


class TestPromptManagerCRUD:
    def test_defaults_seeded(self, mgr):
        """Default prompts are seeded on creation."""
        default = mgr.get_prompt("default")
        assert default is not None
        assert default["name"] == "Default Assistant"
        assert "{{skills}}" in default["template"]

    def test_inline_suggest_seeded(self, mgr):
        inline = mgr.get_prompt("inline-suggest")
        assert inline is not None
        assert inline["name"] == "Inline Suggest"

    def test_idempotent_seeding(self, db):
        """Seeding defaults twice does not overwrite."""
        mgr1 = PromptManager(db)
        mgr1.update_prompt("default", template="MODIFIED")
        mgr2 = PromptManager(db)  # re-seed
        prompt = mgr2.get_prompt("default")
        assert prompt["template"] == "MODIFIED"  # not overwritten

    def test_create_prompt(self, mgr):
        pid = mgr.create_prompt(
            name="Code Reviewer",
            description="Reviews code for bugs",
            template="You are a code reviewer. Focus on {{focus}}.",
        )
        assert pid.startswith("custom:")
        row = mgr.get_prompt(pid)
        assert row is not None
        assert row["name"] == "Code Reviewer"
        assert row["scope"] == "global"

    def test_create_prompt_custom_id(self, mgr):
        pid = mgr.create_prompt(
            name="Test",
            template="Test prompt",
            prompt_id="my-custom-id",
        )
        assert pid == "my-custom-id"

    def test_get_prompt_not_found(self, mgr):
        assert mgr.get_prompt("nonexistent") is None

    def test_list_prompts(self, mgr):
        prompts = mgr.list_prompts()
        ids = [p["id"] for p in prompts]
        assert "default" in ids
        assert "inline-suggest" in ids

    def test_list_prompts_by_scope(self, mgr):
        mgr.create_prompt(name="Project", template="T", scope="project")
        global_prompts = mgr.list_prompts(scope="global")
        project_prompts = mgr.list_prompts(scope="project")
        assert all(p["scope"] == "global" for p in global_prompts)
        assert all(p["scope"] == "project" for p in project_prompts)

    def test_update_prompt(self, mgr):
        mgr.update_prompt("default", name="Renamed", description="New desc")
        row = mgr.get_prompt("default")
        assert row["name"] == "Renamed"
        assert row["description"] == "New desc"

    def test_update_prompt_ignores_unknown_keys(self, mgr):
        mgr.update_prompt("default", nonexistent_key="ignored")
        row = mgr.get_prompt("default")
        assert "nonexistent_key" not in row

    def test_delete_prompt(self, mgr):
        mgr.create_prompt(name="ToDelete", template="T", prompt_id="del-me")
        assert mgr.get_prompt("del-me") is not None
        mgr.delete_prompt("del-me")
        assert mgr.get_prompt("del-me") is None

    def test_model_field(self, mgr):
        pid = mgr.create_prompt(name="Specialist", template="T", model="llama3")
        row = mgr.get_prompt(pid)
        assert row["model"] == "llama3"


# ---------------------------------------------------------------------------
# PromptManager — Rendering
# ---------------------------------------------------------------------------


class TestPromptManagerRender:
    def test_render_default_template(self, mgr):
        """Rendering the default prompt resolves dynamic placeholders."""
        class FakeCtx:
            working_directory = "/home/user/project"
            config = None

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
        """Inline suggest prompt has no placeholders to resolve."""
        class FakeCtx:
            working_directory = "/tmp"
            config = None

        result = mgr.render("inline-suggest", FakeCtx())
        # This prompt has no {{key}} placeholders
        assert "{{" not in result

    def test_render_missing_prompt_raises(self, mgr):
        class FakeCtx:
            working_directory = "/tmp"
            config = None

        with pytest.raises(ValueError, match="not found"):
            mgr.render("nonexistent", FakeCtx())

    def test_render_with_extra_vars(self, mgr):
        """Extra vars take priority over dynamic providers."""
        mgr.create_prompt(
            name="Test",
            template="Hello {{project_name}}!",
            prompt_id="test-extra",
        )

        class FakeCtx:
            working_directory = "/home/user/myproject"
            config = None

        result = mgr.render("test-extra", FakeCtx(), extra_vars={"project_name": "Override"})
        assert result == "Hello Override!"

    def test_render_unresolved_key_left_unchanged(self, mgr):
        mgr.create_prompt(
            name="Test",
            template="Hello {{unknown_key}}!",
            prompt_id="test-unknown",
        )

        class FakeCtx:
            working_directory = "/tmp"
            config = None

        result = mgr.render("test-unknown", FakeCtx())
        assert result == "Hello {{unknown_key}}!"


# ---------------------------------------------------------------------------
# PromptManager — Dynamic providers
# ---------------------------------------------------------------------------


class TestDynamicProviders:
    def test_simple_string_provider(self, mgr):
        mgr.register_dynamic("env", lambda ctx: "production")

        mgr.create_prompt(
            name="Test",
            template="Running in {{env}}.",
            prompt_id="test-env",
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

        mgr.create_prompt(
            name="Test",
            template="Skills: {{skills}}",
            prompt_id="test-skills-default",
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

        mgr.create_prompt(
            name="Test",
            template="Names: {{skills.names}}",
            prompt_id="test-skills-names",
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

        mgr.create_prompt(
            name="Test",
            template="Value: {{data.level1.level2}}",
            prompt_id="test-deep",
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

        mgr.create_prompt(
            name="Test",
            template="{{skills.nonexistent}}",
            prompt_id="test-fallback",
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

        mgr.create_prompt(
            name="Test",
            template="Project: {{project_name}}",
            prompt_id="test-ctx",
        )

        result = mgr.render("test-ctx", FakeCtx())
        assert result == "Project: myproject"

    def test_multiple_providers_in_template(self, mgr):
        """Multiple different {{key}} placeholders resolved in order."""
        mgr.register_dynamic("date", lambda ctx: "2025-01-15")
        mgr.register_dynamic("env", lambda ctx: "production")

        mgr.create_prompt(
            name="Test",
            template="Date: {{date}}, Env: {{env}}",
            prompt_id="test-multi",
        )

        class FakeCtx:
            pass

        result = mgr.render("test-multi", FakeCtx())
        assert result == "Date: 2025-01-15, Env: production"

    def test_extra_vars_override_provider(self, mgr):
        """Extra vars override dynamic providers."""
        mgr.register_dynamic("env", lambda ctx: "staging")

        mgr.create_prompt(
            name="Test",
            template="Env: {{env}}",
            prompt_id="test-override",
        )

        class FakeCtx:
            pass

        result = mgr.render("test-override", FakeCtx(), extra_vars={"env": "production"})
        assert result == "Env: production"


# ---------------------------------------------------------------------------
# Built-in providers registered by bootstrap
# ---------------------------------------------------------------------------


class TestBuiltinProviders:
    def test_working_directory_provider(self, mgr):
        """The working_directory provider resolves correctly."""
        class FakeCtx:
            working_directory = "/home/user/myproject"
            config = None

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

        mgr.create_prompt(
            name="Test",
            template="Dir: {{working_directory}}, Name: {{project_name}}",
            prompt_id="test-wd",
        )

        result = mgr.render("test-wd", FakeCtx())
        assert result == "Dir: /home/user/myproject, Name: myproject"

    def test_date_provider(self, mgr):
        """The date provider returns a date string."""
        from datetime import datetime, timezone

        mgr.register_dynamic("date", lambda ctx: datetime.now(timezone.utc).strftime("%Y-%m-%d"))

        mgr.create_prompt(
            name="Test",
            template="Date: {{date}}",
            prompt_id="test-date",
        )

        class FakeCtx:
            pass

        result = mgr.render("test-date", FakeCtx())
        # Should contain a date in YYYY-MM-DD format
        import re
        assert re.match(r"Date: \d{4}-\d{2}-\d{2}", result)