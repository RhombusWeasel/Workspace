"""Tests for core.context_files — user, design, and tasks markdown loaders."""

import os
from unittest.mock import MagicMock

from core.context_files import (
    load_design_md,
    load_tasks_md,
    load_user_md,
    _read_file,
    _MISSING_DESIGN_INSTRUCTION,
    _MISSING_TASKS_INSTRUCTION,
    _MISSING_USER_INSTRUCTION,
)


# ---------------------------------------------------------------------------
# _read_file
# ---------------------------------------------------------------------------

def test_read_file_reads_existing_file(tmp_path):
    f = tmp_path / "test.md"
    f.write_text("Hello world")
    assert _read_file(str(f)) == "Hello world"


def test_read_file_strips_whitespace(tmp_path):
    f = tmp_path / "test.md"
    f.write_text("  Hello  \n\n")
    assert _read_file(str(f)) == "Hello"


def test_read_file_missing_file(tmp_path):
    assert _read_file(str(tmp_path / "nonexistent.md")) == ""


def test_read_file_unreadable_file():
    """Returns empty string on OSError."""
    assert _read_file("/proc/nonexistent/test.md") == ""


def test_read_file_empty_file(tmp_path):
    """A file with only whitespace returns empty string."""
    f = tmp_path / "empty.md"
    f.write_text("   \n  \n")
    assert _read_file(str(f)) == ""


def test_read_file_non_utf8(tmp_path):
    f = tmp_path / "test.md"
    f.write_bytes(b"\xff\xfe Bad encoding")
    # UnicodeDecodeError is caught, returns ""
    assert _read_file(str(f)) == ""


# ---------------------------------------------------------------------------
# load_user_md
# ---------------------------------------------------------------------------

def test_load_user_md_with_file(monkeypatch, tmp_path):
    """When ~/.agents/user.md exists, returns content wrapped with newlines."""
    agents_dir = tmp_path / ".agents"
    agents_dir.mkdir()
    (agents_dir / "user.md").write_text("Name: Pete\nPrefers: snake_case")

    monkeypatch.setattr(os.path, "expanduser", lambda _: str(tmp_path))

    ctx = MagicMock()
    ctx.working_directory = "/some/project"
    result = load_user_md(ctx)
    assert result == "\nName: Pete\nPrefers: snake_case\n"


def test_load_user_md_missing_file(monkeypatch, tmp_path):
    """When ~/.agents/user.md does not exist, returns missing-file instruction."""
    monkeypatch.setattr(os.path, "expanduser", lambda _: str(tmp_path))

    ctx = MagicMock()
    ctx.working_directory = "/some/project"
    result = load_user_md(ctx)
    assert result == f"\n{_MISSING_USER_INSTRUCTION}\n"


def test_load_user_md_returns_string_even_without_ctx(monkeypatch, tmp_path):
    """load_user_md returns a string regardless of filesystem state."""
    monkeypatch.setattr(os.path, "expanduser", lambda _: str(tmp_path))

    ctx = MagicMock()
    result = load_user_md(ctx)
    assert isinstance(result, str)
    # Since file doesn't exist, it should be the instruction
    assert _MISSING_USER_INSTRUCTION in result


# ---------------------------------------------------------------------------
# load_design_md
# ---------------------------------------------------------------------------

def test_load_design_md_with_file(tmp_path):
    """When {wd}/.agents/design.md exists, returns content wrapped with newlines."""
    agents_dir = tmp_path / ".agents"
    agents_dir.mkdir()
    (agents_dir / "design.md").write_text("# My Project\nA TUI app using Textual.")

    ctx = MagicMock()
    ctx.working_directory = str(tmp_path)
    result = load_design_md(ctx)
    assert result == "\n# My Project\nA TUI app using Textual.\n"


def test_load_design_md_missing_file(tmp_path):
    """When {wd}/.agents/design.md does not exist, returns missing-file instruction."""
    ctx = MagicMock()
    ctx.working_directory = str(tmp_path)
    result = load_design_md(ctx)
    assert result == f"\n{_MISSING_DESIGN_INSTRUCTION}\n"


def test_load_design_md_no_working_directory():
    """When ctx has no working_directory, returns missing-file instruction."""
    ctx = MagicMock()
    ctx.working_directory = ""
    result = load_design_md(ctx)
    assert result == f"\n{_MISSING_DESIGN_INSTRUCTION}\n"


def test_load_design_md_none_ctx():
    """When ctx is None, returns missing-file instruction."""
    result = load_design_md(None)
    assert result == f"\n{_MISSING_DESIGN_INSTRUCTION}\n"


# ---------------------------------------------------------------------------
# load_tasks_md
# ---------------------------------------------------------------------------

def test_load_tasks_md_with_file(tmp_path):
    """When {wd}/.agents/tasks.md exists, returns content wrapped with newlines."""
    agents_dir = tmp_path / ".agents"
    agents_dir.mkdir()
    (agents_dir / "tasks.md").write_text("# Tasks\n- [ ] Add feature X")

    ctx = MagicMock()
    ctx.working_directory = str(tmp_path)
    result = load_tasks_md(ctx)
    assert result == "\n# Tasks\n- [ ] Add feature X\n"


def test_load_tasks_md_missing_file(tmp_path):
    """When {wd}/.agents/tasks.md does not exist, returns missing-file instruction."""
    ctx = MagicMock()
    ctx.working_directory = str(tmp_path)
    result = load_tasks_md(ctx)
    assert result == f"\n{_MISSING_TASKS_INSTRUCTION}\n"


def test_load_tasks_md_no_working_directory():
    """When ctx has no working_directory, returns missing-file instruction."""
    ctx = MagicMock()
    ctx.working_directory = ""
    result = load_tasks_md(ctx)
    assert result == f"\n{_MISSING_TASKS_INSTRUCTION}\n"


def test_load_tasks_md_none_ctx():
    """When ctx is None, returns missing-file instruction."""
    result = load_tasks_md(None)
    assert result == f"\n{_MISSING_TASKS_INSTRUCTION}\n"


# ---------------------------------------------------------------------------
# Integration: template rendering with context file variables
# ---------------------------------------------------------------------------

def test_template_renders_with_all_context_files(monkeypatch, tmp_path):
    """All three context file variables should render correctly in a template."""
    from core.agent_registry import render_template

    # Set up user file
    global_home = tmp_path / "home"
    global_home.mkdir()
    (global_home / ".agents").mkdir()
    (global_home / ".agents" / "user.md").write_text("Name: Pete\nPrefers: snake_case")
    monkeypatch.setattr(os.path, "expanduser", lambda _: str(global_home))

    # Set up project with design and tasks
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / ".agents").mkdir()
    (project_dir / ".agents" / "design.md").write_text("# Project X\nA TUI app.")
    (project_dir / ".agents" / "tasks.md").write_text("# Tasks\n- [ ] Fix bug")

    ctx = MagicMock()
    ctx.working_directory = str(project_dir)

    variables = {
        "agent_name": "Cody",
        "user": load_user_md(ctx),
        "design": load_design_md(ctx),
        "tasks": load_tasks_md(ctx),
    }

    template = "You are {{agent_name}}.\n{{user}}\n\n{{design}}\n\n{{tasks}}\n\n"
    result = render_template(template, variables)

    assert result == (
        "You are Cody.\n"
        "\nName: Pete\nPrefers: snake_case\n"  # {{user}} resolved
        "\n\n"                       # template's \n\n after {{user}}
        "\n# Project X\nA TUI app.\n"    # {{design}} resolved
        "\n\n"                       # template's \n\n after {{design}}
        "\n# Tasks\n- [ ] Fix bug\n"     # {{tasks}} resolved
        "\n\n"                       # template's \n\n after {{tasks}}
    )


def test_template_renders_with_missing_context_files(monkeypatch, tmp_path):
    """When context files are missing, instructions are injected into template."""
    from core.agent_registry import render_template

    # No user file
    global_home = tmp_path / "home"
    global_home.mkdir()
    monkeypatch.setattr(os.path, "expanduser", lambda _: str(global_home))

    # Project exists but no .agents/ dir
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    ctx = MagicMock()
    ctx.working_directory = str(project_dir)

    variables = {
        "agent_name": "Cody",
        "user": load_user_md(ctx),
        "design": load_design_md(ctx),
        "tasks": load_tasks_md(ctx),
    }

    template = "You are {{agent_name}}.\n{{user}}\n\n{{design}}\n\n{{tasks}}\n\n"
    result = render_template(template, variables)

    assert _MISSING_USER_INSTRUCTION in result
    assert _MISSING_DESIGN_INSTRUCTION in result
    assert _MISSING_TASKS_INSTRUCTION in result


def test_template_renders_mixed_present_and_missing(monkeypatch, tmp_path):
    """When some context files exist and others don't, renders correctly."""
    from core.agent_registry import render_template

    # User file exists
    global_home = tmp_path / "home"
    global_home.mkdir()
    (global_home / ".agents").mkdir()
    (global_home / ".agents" / "user.md").write_text("Name: Pete")
    monkeypatch.setattr(os.path, "expanduser", lambda _: str(global_home))

    # Project has design but no tasks
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / ".agents").mkdir()
    (project_dir / ".agents" / "design.md").write_text("# Design doc")

    ctx = MagicMock()
    ctx.working_directory = str(project_dir)

    variables = {
        "agent_name": "Cody",
        "user": load_user_md(ctx),
        "design": load_design_md(ctx),
        "tasks": load_tasks_md(ctx),
    }

    template = "You are {{agent_name}}.\n{{user}}\n\n{{design}}\n\n{{tasks}}\n\n"
    result = render_template(template, variables)

    # User and design content present
    assert "Name: Pete" in result
    assert "# Design doc" in result
    # Tasks instruction present
    assert _MISSING_TASKS_INSTRUCTION in result