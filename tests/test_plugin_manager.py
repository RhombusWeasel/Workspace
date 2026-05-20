"""Tests for core/plugin_manager.py — PluginManager and PluginInfo."""

import json
import os
import subprocess
import tempfile

import pytest

from core.config import Config
from core.plugin_manager import PluginManager, PluginInfo, PluginError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_skill_md(directory: str, name: str = "test_plugin",
                    description: str = "A test plugin") -> str:
    """Write a SKILL.md in the given directory."""
    path = os.path.join(directory, "SKILL.md")
    with open(path, "w") as fh:
        fh.write(f"---\nname: {name}\ndescription: {description}\n---\n")
    return path


def _make_git_repo(directory: str, tag: str | None = None) -> str:
    """Initialize a git repo in the directory, optionally creating a tag."""
    subprocess.run(["git", "init"], cwd=directory, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=directory, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=directory, capture_output=True,
    )
    subprocess.run(["git", "add", "."], cwd=directory, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=directory, capture_output=True,
    )
    if tag:
        subprocess.run(
            ["git", "tag", tag],
            cwd=directory, capture_output=True,
        )
    return directory


def _create_plugin_repo(
    tmp_path,
    name: str = "test_plugin",
    description: str = "A test plugin",
    tag: str = "v0.1.0",
) -> str:
    """Create a minimal git repo with a SKILL.md and an __init__.py."""
    repo_dir = tmp_path / "repos" / name
    os.makedirs(repo_dir)
    _write_skill_md(str(repo_dir), name, description)

    # Create __init__.py so it's a valid plugin
    init_path = os.path.join(str(repo_dir), "__init__.py")
    with open(init_path, "w") as fh:
        fh.write(f'"""{name} plugin."""\nPLUGIN_SERVICES = {{}}\n')

    _make_git_repo(str(repo_dir), tag)
    return str(repo_dir)


def _make_config(tmp_path) -> Config:
    """Create a minimal Config for testing."""
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text("{}")
    return Config([str(cfg_path)])


# ---------------------------------------------------------------------------
# Test: PluginInfo
# ---------------------------------------------------------------------------


class TestPluginInfo:
    def test_defaults(self):
        info = PluginInfo(name="test", description="desc", location="/path")
        assert info.name == "test"
        assert info.version is None
        assert info.source is None
        assert info.managed is False
        assert info.tier == "unknown"
        assert info.enabled is True

    def test_managed_plugin(self):
        info = PluginInfo(
            name="postgres",
            description="PostgreSQL provider",
            location="/home/.agents/plugins/postgres",
            version="v0.3.1",
            source="https://github.com/user/plugin",
            managed=True,
            tier="global",
        )
        assert info.managed is True
        assert info.version == "v0.3.1"


# ---------------------------------------------------------------------------
# Test: SKILL.md parsing
# ---------------------------------------------------------------------------


class TestParseSkillMd:
    def test_valid_skill_md(self, tmp_path):
        from core.plugin_manager import PluginManager as PM
        md_path = tmp_path / "SKILL.md"
        md_path.write_text("---\nname: my_plugin\ndescription: Hello\n---\nBody text")
        result = PM._parse_skill_md(str(md_path))
        assert result is not None
        assert result["name"] == "my_plugin"
        assert result["description"] == "Hello"

    def test_missing_name(self, tmp_path):
        from core.plugin_manager import PluginManager as PM
        md_path = tmp_path / "SKILL.md"
        md_path.write_text("---\ndescription: No name\n---\n")
        result = PM._parse_skill_md(str(md_path))
        assert result is None

    def test_missing_file(self, tmp_path):
        from core.plugin_manager import PluginManager as PM
        result = PM._parse_skill_md(str(tmp_path / "nonexistent.md"))
        assert result is None

    def test_extra_fields(self, tmp_path):
        from core.plugin_manager import PluginManager as PM
        md_path = tmp_path / "SKILL.md"
        md_path.write_text("---\nname: p\ndescription: d\nversion: 1.0.0\n---\n")
        result = PM._parse_skill_md(str(md_path))
        assert result is not None
        assert result["version"] == "1.0.0"

    def test_requirements_list(self, tmp_path):
        """SKILL.md with YAML list requirements."""
        from core.plugin_manager import PluginManager as PM
        md_path = tmp_path / "SKILL.md"
        md_path.write_text(
            "---\n"
            "name: my_plugin\n"
            "description: Needs deps\n"
            "requirements:\n"
            "  - requests>=2.28\n"
            "  - psycopg2-binary>=2.9\n"
            "---\n"
        )
        result = PM._parse_skill_md(str(md_path))
        assert result is not None
        assert result["name"] == "my_plugin"
        assert result["requirements"] == ["requests>=2.28", "psycopg2-binary>=2.9"]

    def test_requirements_comma_separated(self, tmp_path):
        """SKILL.md with comma-separated requirements string."""
        from core.plugin_manager import PluginManager as PM
        md_path = tmp_path / "SKILL.md"
        md_path.write_text(
            "---\n"
            "name: my_plugin\n"
            "description: Needs deps\n"
            "requirements: requests>=2.28, psycopg2-binary>=2.9\n"
            "---\n"
        )
        result = PM._parse_skill_md(str(md_path))
        assert result is not None
        assert result["requirements"] == ["requests>=2.28", "psycopg2-binary>=2.9"]

    def test_no_requirements(self, tmp_path):
        """SKILL.md without requirements returns empty list."""
        from core.plugin_manager import PluginManager as PM
        md_path = tmp_path / "SKILL.md"
        md_path.write_text("---\nname: p\ndescription: d\n---\n")
        result = PM._parse_skill_md(str(md_path))
        assert result is not None
        assert result["requirements"] == []

    def test_empty_requirements(self, tmp_path):
        """SKILL.md with empty requirements list returns empty list."""
        from core.plugin_manager import PluginManager as PM
        md_path = tmp_path / "SKILL.md"
        md_path.write_text(
            "---\n"
            "name: p\n"
            "description: d\n"
            "requirements:\n"
            "---\n"
        )
        result = PM._parse_skill_md(str(md_path))
        assert result is not None
        assert result["requirements"] == []


# ---------------------------------------------------------------------------
# Test: .plugin.json
# ---------------------------------------------------------------------------


class TestPluginJson:
    def test_write_and_read(self, tmp_path):
        from core.plugin_manager import PluginManager as PM
        PM._write_plugin_json(str(tmp_path), "https://example.com/repo", "v1.0.0")
        result = PM._read_plugin_json(str(tmp_path))
        assert result is not None
        assert result["source"] == "https://example.com/repo"
        assert result["version"] == "v1.0.0"
        assert "installed_at" in result

    def test_write_with_requirements(self, tmp_path):
        """_write_plugin_json stores requirements list."""
        from core.plugin_manager import PluginManager as PM
        PM._write_plugin_json(
            str(tmp_path),
            "https://example.com/repo",
            "v1.0.0",
            requirements=["requests>=2.28", "psycopg2-binary>=2.9"],
        )
        result = PM._read_plugin_json(str(tmp_path))
        assert result is not None
        assert result["requirements"] == ["requests>=2.28", "psycopg2-binary>=2.9"]

    def test_write_without_requirements(self, tmp_path):
        """_write_plugin_json without requirements omits the key."""
        from core.plugin_manager import PluginManager as PM
        PM._write_plugin_json(str(tmp_path), "https://example.com/repo", "v1.0.0")
        result = PM._read_plugin_json(str(tmp_path))
        assert result is not None
        assert "requirements" not in result

    def test_read_missing(self, tmp_path):
        from core.plugin_manager import PluginManager as PM
        result = PM._read_plugin_json(str(tmp_path))
        assert result is None

    def test_read_invalid_json(self, tmp_path):
        from core.plugin_manager import PluginManager as PM
        path = tmp_path / ".plugin.json"
        path.write_text("not json{{{")
        result = PM._read_plugin_json(str(tmp_path))
        assert result is None


# ---------------------------------------------------------------------------
# Test: Version resolution
# ---------------------------------------------------------------------------


class TestLatestSemver:
    def test_simple_semver(self):
        from core.plugin_manager import PluginManager as PM
        tags = ["v0.1.0", "v0.2.0", "v1.0.0"]
        assert PM._latest_semver(tags) == "v1.0.0"

    def test_semver_without_v(self):
        from core.plugin_manager import PluginManager as PM
        tags = ["0.1.0", "1.0.0", "0.9.0"]
        assert PM._latest_semver(tags) == "1.0.0"

    def test_mixed_v_prefix(self):
        from core.plugin_manager import PluginManager as PM
        tags = ["v0.1.0", "1.0.0"]
        assert PM._latest_semver(tags) == "1.0.0"

    def test_no_semver_tags(self):
        from core.plugin_manager import PluginManager as PM
        tags = ["beta", "release-candidate", "stable"]
        result = PM._latest_semver(tags)
        assert result == "stable"  # alphabetically last

    def test_single_tag(self):
        from core.plugin_manager import PluginManager as PM
        assert PM._latest_semver(["alpha"]) == "alpha"


# ---------------------------------------------------------------------------
# Test: Install (integration with real git)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not os.path.exists("/usr/bin/git"),
    reason="git not available"
)
class TestInstall:
    def test_install_global(self, tmp_path):
        """Install a plugin to the global tier."""
        config = _make_config(tmp_path)
        repo = _create_plugin_repo(tmp_path, name="my_plugin")

        agents_dir = str(tmp_path / "home" / ".agents")
        cody_dir = str(tmp_path / "cody")
        os.makedirs(os.path.join(agents_dir, "plugins"))
        os.makedirs(cody_dir)

        mgr = PluginManager(
            config,
            working_dir=str(tmp_path),
            agents_dir=agents_dir,
            cody_dir=cody_dir,
        )

        name = mgr.install(repo)
        assert name == "my_plugin"

        # Check plugin directory exists
        plugin_dir = os.path.join(agents_dir, "plugins", "my_plugin")
        assert os.path.isdir(plugin_dir)
        assert os.path.isfile(os.path.join(plugin_dir, "SKILL.md"))

        # Check no .git/ directory
        assert not os.path.isdir(os.path.join(plugin_dir, ".git"))

        # Check .plugin.json
        meta_file = os.path.join(plugin_dir, ".plugin.json")
        assert os.path.isfile(meta_file)
        meta = json.loads(open(meta_file).read())
        assert "source" in meta
        assert meta["version"] == "v0.1.0"

        # Check config was updated
        installed = config.get("plugins.installed", {})
        assert "my_plugin" in installed
        assert installed["my_plugin"]["version"] == "v0.1.0"

    def test_install_local(self, tmp_path):
        """Install a plugin to the project-local tier."""
        config = _make_config(tmp_path)
        repo = _create_plugin_repo(tmp_path, name="local_plugin")

        # Create working directory
        wd = str(tmp_path / "project")

        mgr = PluginManager(config, working_dir=wd)
        name = mgr.install(repo, local=True)
        assert name == "local_plugin"

        # Check plugin directory exists in project-local tier
        plugin_dir = os.path.join(wd, ".agents", "plugins", "local_plugin")
        assert os.path.isdir(plugin_dir)
        assert not os.path.isdir(os.path.join(plugin_dir, ".git"))

    def test_install_with_subdir(self, tmp_path):
        """Install a plugin from a monorepo subdirectory."""
        config = _make_config(tmp_path)

        # Create a monorepo with a plugin in a subdirectory
        repo_dir = tmp_path / "repos" / "monorepo"
        plugin_subdir = repo_dir / "plugins" / "my_sub_plugin"
        os.makedirs(plugin_subdir)
        _write_skill_md(str(plugin_subdir), "my_sub_plugin", "Subdir plugin")
        init_path = os.path.join(str(plugin_subdir), "__init__.py")
        with open(init_path, "w") as fh:
            fh.write('"""Subdir plugin."""\nPLUGIN_SERVICES = {}\n')

        # Also add a root file so git has something to commit
        (repo_dir / "README.md").write_text("# Monorepo\n")
        _make_git_repo(str(repo_dir), "v0.2.0")

        agents_dir = str(tmp_path / "home" / ".agents")
        cody_dir = str(tmp_path / "cody")
        os.makedirs(os.path.join(agents_dir, "plugins"))
        os.makedirs(cody_dir)

        wd = str(tmp_path / "project")
        os.makedirs(wd)

        mgr = PluginManager(
            config,
            working_dir=wd,
            agents_dir=agents_dir,
            cody_dir=cody_dir,
        )

        name = mgr.install(
            str(repo_dir),
            subdir="plugins/my_sub_plugin",
            version="v0.2.0",
        )
        assert name == "my_sub_plugin"

        plugin_dir = os.path.join(agents_dir, "plugins", "my_sub_plugin")
        assert os.path.isdir(plugin_dir)
        assert os.path.isfile(os.path.join(plugin_dir, "SKILL.md"))
        # The README should NOT be copied (only the subdir)
        assert not os.path.isfile(os.path.join(plugin_dir, "README.md"))

    def test_install_no_skill_md_fails(self, tmp_path):
        """Cloning a repo without SKILL.md raises PluginError."""
        config = _make_config(tmp_path)
        # Create a repo with no SKILL.md
        repo_dir = tmp_path / "repos" / "bad_repo"
        os.makedirs(repo_dir)
        (repo_dir / "README.md").write_text("# Not a plugin")
        _make_git_repo(str(repo_dir), "v0.1.0")

        wd = str(tmp_path / "project")
        os.makedirs(wd)

        mgr = PluginManager(config, working_dir=wd)
        with pytest.raises(PluginError, match="No SKILL.md"):
            mgr.install(str(repo_dir), version="v0.1.0")

    def test_install_invalid_name_fails(self, tmp_path):
        """Plugin with invalid name in SKILL.md raises PluginError."""
        config = _make_config(tmp_path)
        repo_dir = tmp_path / "repos" / "bad_name"
        os.makedirs(repo_dir)
        skill_md = os.path.join(str(repo_dir), "SKILL.md")
        with open(skill_md, "w") as fh:
            fh.write("---\nname: my plugin!\ndescription: Bad name\n---\n")
        init_path = os.path.join(str(repo_dir), "__init__.py")
        with open(init_path, "w") as fh:
            fh.write('"""Bad."""\n')
        _make_git_repo(str(repo_dir), "v0.1.0")

        wd = str(tmp_path / "project")
        os.makedirs(wd)

        mgr = PluginManager(config, working_dir=wd)
        with pytest.raises(PluginError, match="Invalid plugin name"):
            mgr.install(str(repo_dir), version="v0.1.0")


# ---------------------------------------------------------------------------
# Test: Remove
# ---------------------------------------------------------------------------


class TestRemove:
    def test_remove_existing(self, tmp_path):
        """Remove a plugin directory and clean config."""
        config = _make_config(tmp_path)

        agents_dir = str(tmp_path / "home" / ".agents")
        cody_dir = str(tmp_path / "cody")
        plugin_dir = os.path.join(agents_dir, "plugins", "test_rm")
        os.makedirs(plugin_dir)
        with open(os.path.join(plugin_dir, "SKILL.md"), "w") as fh:
            fh.write("---\nname: test_rm\ndescription: test\n---\n")

        mgr = PluginManager(
            config,
            working_dir=str(tmp_path),
            agents_dir=agents_dir,
            cody_dir=cody_dir,
        )

        result = mgr.remove("test_rm")
        assert result is True
        assert not os.path.isdir(plugin_dir)

    def test_remove_nonexistent(self, tmp_path):
        """Removing a plugin that doesn't exist returns False."""
        config = _make_config(tmp_path)
        mgr = PluginManager(config, working_dir=str(tmp_path))
        result = mgr.remove("nonexistent_plugin")
        assert result is False


# ---------------------------------------------------------------------------
# Test: List
# ---------------------------------------------------------------------------


class TestListPlugins:
    def test_list_discovered_plugins(self, tmp_path):
        """list_plugins returns plugins discovered by discover_plugins."""
        config = _make_config(tmp_path)

        # Create a fake plugin in the global tier
        agents_dir = str(tmp_path / "home" / ".agents")
        plugin_dir = os.path.join(agents_dir, "plugins", "test_list")
        os.makedirs(plugin_dir)
        with open(os.path.join(plugin_dir, "SKILL.md"), "w") as fh:
            fh.write("---\nname: test_list\ndescription: A listing test\n---\n")

        cody_dir = str(tmp_path / "cody")
        os.makedirs(os.path.join(cody_dir, "plugins"), exist_ok=True)
        wd = str(tmp_path / "project")
        os.makedirs(os.path.join(wd, ".agents", "plugins"), exist_ok=True)

        mgr = PluginManager(
            config,
            working_dir=wd,
            agents_dir=agents_dir,
            cody_dir=cody_dir,
        )

        plugins = mgr.list_plugins()

        # Should find our test plugin
        names = [p.name for p in plugins]
        assert "test_list" in names

        # Find the specific plugin
        plugin = next(p for p in plugins if p.name == "test_list")
        assert plugin.description == "A listing test"
        assert plugin.tier == "global"
        assert plugin.managed is False

    def test_list_managed_plugin(self, tmp_path):
        """list_plugins shows .plugin.json metadata for managed plugins."""
        config = _make_config(tmp_path)

        agents_dir = str(tmp_path / "home" / ".agents")
        plugin_dir = os.path.join(agents_dir, "plugins", "managed_p")
        os.makedirs(plugin_dir)
        with open(os.path.join(plugin_dir, "SKILL.md"), "w") as fh:
            fh.write("---\nname: managed_p\ndescription: managed plugin\n---\n")
        # Write .plugin.json
        with open(os.path.join(plugin_dir, ".plugin.json"), "w") as fh:
            json.dump({
                "source": "https://github.com/test/managed-p",
                "version": "v0.5.0",
                "installed_at": "2025-05-21T10:00:00+00:00",
            }, fh)

        cody_dir = str(tmp_path / "cody")
        os.makedirs(os.path.join(cody_dir, "plugins"), exist_ok=True)
        wd = str(tmp_path / "project")
        os.makedirs(os.path.join(wd, ".agents", "plugins"), exist_ok=True)

        mgr = PluginManager(
            config,
            working_dir=wd,
            agents_dir=agents_dir,
            cody_dir=cody_dir,
        )

        plugins = mgr.list_plugins()
        plugin = next(p for p in plugins if p.name == "managed_p")

        assert plugin.managed is True
        assert plugin.version == "v0.5.0"
        assert plugin.source == "https://github.com/test/managed-p"


# ---------------------------------------------------------------------------
# Test: Config integration
# ---------------------------------------------------------------------------


class TestConfigIntegration:
    def test_config_set_installed(self, tmp_path):
        """_config_set_installed writes to config and saves."""
        config = _make_config(tmp_path)
        wd = str(tmp_path / "project")
        os.makedirs(wd)

        mgr = PluginManager(config, working_dir=wd)
        mgr._config_set_installed(
            "my_plugin",
            "https://github.com/test/my_plugin",
            "v1.0.0",
        )

        installed = config.get("plugins.installed", {})
        assert "my_plugin" in installed
        assert installed["my_plugin"]["version"] == "v1.0.0"
        assert installed["my_plugin"]["source"] == "https://github.com/test/my_plugin"

        # Should also default to enabled
        enabled = config.get("plugins.enabled", {})
        assert enabled.get("my_plugin") is True

    def test_config_remove_installed(self, tmp_path):
        """_config_remove_installed removes from config and saves."""
        config = _make_config(tmp_path)
        wd = str(tmp_path / "project")
        os.makedirs(wd)

        mgr = PluginManager(config, working_dir=wd)
        mgr._config_set_installed("to_remove", "https://example.com", "v1.0.0")
        assert "to_remove" in config.get("plugins.installed", {})

        mgr._config_remove_installed("to_remove")
        assert "to_remove" not in config.get("plugins.installed", {})
        assert "to_remove" not in config.get("plugins.enabled", {})


# ---------------------------------------------------------------------------
# Test: Requirement installation
# ---------------------------------------------------------------------------


class TestInstallRequirements:
    def test_install_requirements_calls_installer(self, tmp_path, monkeypatch):
        """_install_requirements invokes the package installer."""
        config = _make_config(tmp_path)
        mgr = PluginManager(config, working_dir=str(tmp_path))

        calls = []

        def mock_run(cmd, **kwargs):
            calls.append(cmd)
            result = subprocess.CompletedProcess(args=cmd, returncode=0)
            result.stdout = ""
            result.stderr = ""
            return result

        monkeypatch.setattr(subprocess, "run", mock_run)

        mgr._install_requirements(["requests>=2.28", "psycopg2-binary>=2.9"])

        # Should have called the installer — the exact command depends on
        # whether uv or pip is used, but the install call must include our deps.
        install_calls = [c for c in calls if "install" in c]
        assert len(install_calls) == 1
        assert "requests>=2.28" in install_calls[0]
        assert "psycopg2-binary>=2.9" in install_calls[0]

    def test_install_requirements_empty_list_is_noop(self, tmp_path, monkeypatch):
        """_install_requirements with empty list does nothing."""
        config = _make_config(tmp_path)
        mgr = PluginManager(config, working_dir=str(tmp_path))

        calls = []

        def mock_run(cmd, **kwargs):
            calls.append(cmd)
            return subprocess.CompletedProcess(args=cmd, returncode=0)

        monkeypatch.setattr(subprocess, "run", mock_run)

        mgr._install_requirements([])
        assert calls == []

    def test_install_requirements_raises_on_failure(self, tmp_path, monkeypatch):
        """_install_requirements raises PluginError on pip failure."""
        config = _make_config(tmp_path)
        mgr = PluginManager(config, working_dir=str(tmp_path))

        def mock_run(cmd, **kwargs):
            result = subprocess.CompletedProcess(args=cmd, returncode=1)
            result.stdout = ""
            result.stderr = "ERROR: No matching distribution"
            return result

        monkeypatch.setattr(subprocess, "run", mock_run)

        with pytest.raises(PluginError, match="Failed to install"):
            mgr._install_requirements(["nonexistent-package"])


class TestFindPipInstaller:
    def test_find_pip_installer_with_uv(self, tmp_path, monkeypatch):
        """_find_pip_installer prefers uv if available."""
        from core.plugin_manager import PluginManager as PM

        def mock_run(cmd, **kwargs):
            if cmd[0] == "uv":
                result = subprocess.CompletedProcess(args=cmd, returncode=0)
                result.stdout = "uv 0.10.7"
                return result
            return subprocess.CompletedProcess(args=cmd, returncode=1)

        monkeypatch.setattr(subprocess, "run", mock_run)
        result = PM._find_pip_installer()
        assert result == ["uv", "pip"]

    def test_find_pip_installer_fallback(self, tmp_path, monkeypatch):
        """_find_pip_installer falls back to pip if uv is unavailable."""
        import sys
        from core.plugin_manager import PluginManager as PM

        def mock_run(cmd, **kwargs):
            if cmd[0] == "uv":
                raise FileNotFoundError("uv not found")
            return subprocess.CompletedProcess(args=cmd, returncode=0)

        monkeypatch.setattr(subprocess, "run", mock_run)
        result = PM._find_pip_installer()
        assert result == [sys.executable, "-m", "pip"]