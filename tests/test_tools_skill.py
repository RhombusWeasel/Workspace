"""Tests for the activate_skill and run_skill tools."""

import importlib
import os
import pytest

from core.tools import reset
from core.skills import skill_manager


def _load_activate():
    mod = importlib.import_module("tools.activate_skill")
    if hasattr(mod, "activate_skill"):
        reset()
        importlib.reload(mod)


def _load_run():
    mod = importlib.import_module("tools.run_skill")
    if hasattr(mod, "run_skill"):
        reset()
        importlib.reload(mod)


@pytest.fixture(autouse=True)
def _reset():
    reset()
    skill_manager.reset()
    yield
    reset()
    skill_manager.reset()


class TestActivateSkill:
    def test_activates_existing_skill(self):
        """Activating a registered skill returns its body."""
        _load_activate()
        from core.tools import execute_tool

        wd = os.getcwd()
        tier_paths = [os.path.join(wd, "skills")]
        skill_manager.scan(tier_paths)

        result = execute_tool("activate_skill", {"skill_name": "workspace_docs"})
        assert "Workspace Documentation" in result
        assert "Internal documentation" in result

    def test_missing_skill_returns_error(self):
        """Activating a non-existent skill returns an error with available skills."""
        _load_activate()
        from core.tools import execute_tool

        wd = os.getcwd()
        tier_paths = [os.path.join(wd, "skills")]
        skill_manager.scan(tier_paths)

        result = execute_tool("activate_skill", {"skill_name": "nonexistent_skill"})
        assert "not found" in result.lower()
        assert "workspace_docs" in result


class TestRunSkill:
    def test_missing_skill_returns_error(self):
        """Running a script from a non-existent skill returns an error."""
        _load_run()
        from core.tools import execute_tool

        wd = os.getcwd()
        tier_paths = [os.path.join(wd, "skills")]
        skill_manager.scan(tier_paths)

        result = execute_tool("run_skill", {"skill_name": "nope", "script": "test.sh"})
        assert "not found" in result.lower()

    def test_missing_script_returns_error(self):
        """A missing script within a valid skill returns an error."""
        _load_run()
        from core.tools import execute_tool

        wd = os.getcwd()
        tier_paths = [os.path.join(wd, "skills")]
        skill_manager.scan(tier_paths)

        result = execute_tool("run_skill", {"skill_name": "workspace_docs", "script": "nope.sh"})
        assert "Script not found" in result
