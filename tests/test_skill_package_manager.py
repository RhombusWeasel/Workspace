"""Tests for core.skill_package_manager — SkillPackageManager and SkillInfo."""

import json
import os
import subprocess
import tempfile

import pytest

from core.config import Config
from core.skill_package_manager import SkillPackageManager, SkillInfo, SkillInstallError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_skill_md(directory: str, name: str = "test_skill",
                    description: str = "A test skill") -> str:
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


def _create_skill_repo(
    tmp_path,
    name: str = "test_skill",
    description: str = "A test skill",
    tag: str = "v0.1.0",
) -> str:
    """Create a minimal git repo with a SKILL.md and an __init__.py."""
    repo_dir = tmp_path / "repos" / name
    os.makedirs(repo_dir)
    _write_skill_md(str(repo_dir), name, description)

    # Create __init__.py so it's a valid skill
    init_path = os.path.join(str(repo_dir), "__init__.py")
    with open(init_path, "w") as fh:
        fh.write(f'"""{name} skill."""\nSKILL_SERVICES = {{}}\n')

    _make_git_repo(str(repo_dir), tag)
    return str(repo_dir)


def _make_config(tmp_path) -> Config:
    """Create a minimal Config for testing."""
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text("{}")
    return Config([str(cfg_path)])


# ---------------------------------------------------------------------------
# Test: SkillInfo
# ---------------------------------------------------------------------------


class TestSkillInfo:
    def test_defaults(self):
        info = SkillInfo(name="test", description="desc", location="/path")
        assert info.name == "test"
        assert info.version is None
        assert info.source is None
        assert info.managed is False
        assert info.tier == "unknown"
        assert info.enabled is True

    def test_managed_skill(self):
        info = SkillInfo(
            name="postgres",
            description="PostgreSQL provider",
            location="/home/.agents/skills/postgres",
            version="v0.3.1",
            source="https://github.com/user/skill",
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
        from core.skill_package_manager import SkillPackageManager, SkillInfo, SkillInstallError
        md_path = tmp_path / "SKILL.md"
        md_path.write_text("---\nname: my_skill\ndescription: Hello\n---\nBody text")
        result = SkillPackageManager._parse_skill_md(str(md_path))
        assert result is not None
        assert result["name"] == "my_skill"
        assert result["description"] == "Hello"

    def test_missing_name(self, tmp_path):
        from core.skill_package_manager import SkillPackageManager, SkillInfo, SkillInstallError
        md_path = tmp_path / "SKILL.md"
        md_path.write_text("---\ndescription: No name\n---\n")
        result = SkillPackageManager._parse_skill_md(str(md_path))
        assert result is None

    def test_missing_file(self, tmp_path):
        from core.skill_package_manager import SkillPackageManager, SkillInfo, SkillInstallError
        result = SkillPackageManager._parse_skill_md(str(tmp_path / "nonexistent.md"))
        assert result is None

    def test_extra_fields(self, tmp_path):
        from core.skill_package_manager import SkillPackageManager, SkillInfo, SkillInstallError
        md_path = tmp_path / "SKILL.md"
        md_path.write_text("---\nname: p\ndescription: d\nversion: 1.0.0\n---\n")
        result = SkillPackageManager._parse_skill_md(str(md_path))
        assert result is not None
        assert result["version"] == "1.0.0"

    def test_requirements_list(self, tmp_path):
        """SKILL.md with YAML list requirements."""
        from core.skill_package_manager import SkillPackageManager, SkillInfo, SkillInstallError
        md_path = tmp_path / "SKILL.md"
        md_path.write_text(
            "---\n"
            "name: my_skill\n"
            "description: Needs deps\n"
            "requirements:\n"
            "  - requests>=2.28\n"
            "  - psycopg2-binary>=2.9\n"
            "---\n"
        )
        result = SkillPackageManager._parse_skill_md(str(md_path))
        assert result is not None
        assert result["name"] == "my_skill"
        assert result["requirements"] == ["requests>=2.28", "psycopg2-binary>=2.9"]

    def test_requirements_comma_separated(self, tmp_path):
        """SKILL.md with comma-separated requirements string."""
        from core.skill_package_manager import SkillPackageManager, SkillInfo, SkillInstallError
        md_path = tmp_path / "SKILL.md"
        md_path.write_text(
            "---\n"
            "name: my_skill\n"
            "description: Needs deps\n"
            "requirements: requests>=2.28, psycopg2-binary>=2.9\n"
            "---\n"
        )
        result = SkillPackageManager._parse_skill_md(str(md_path))
        assert result is not None
        assert result["requirements"] == ["requests>=2.28", "psycopg2-binary>=2.9"]

    def test_no_requirements(self, tmp_path):
        """SKILL.md without requirements returns empty list."""
        from core.skill_package_manager import SkillPackageManager, SkillInfo, SkillInstallError
        md_path = tmp_path / "SKILL.md"
        md_path.write_text("---\nname: p\ndescription: d\n---\n")
        result = SkillPackageManager._parse_skill_md(str(md_path))
        assert result is not None
        assert result["requirements"] == []

    def test_empty_requirements(self, tmp_path):
        """SKILL.md with empty requirements list returns empty list."""
        from core.skill_package_manager import SkillPackageManager, SkillInfo, SkillInstallError
        md_path = tmp_path / "SKILL.md"
        md_path.write_text(
            "---\n"
            "name: p\n"
            "description: d\n"
            "requirements:\n"
            "---\n"
        )
        result = SkillPackageManager._parse_skill_md(str(md_path))
        assert result is not None
        assert result["requirements"] == []


# ---------------------------------------------------------------------------
# Test: .skill.json
# ---------------------------------------------------------------------------


class TestSkillJson:
    def test_write_and_read(self, tmp_path):
        from core.skill_package_manager import SkillPackageManager, SkillInfo, SkillInstallError
        SkillPackageManager._write_skill_json(str(tmp_path), "https://example.com/repo", "v1.0.0")
        result = SkillPackageManager._read_skill_json(str(tmp_path))
        assert result is not None
        assert result["source"] == "https://example.com/repo"
        assert result["version"] == "v1.0.0"
        assert "installed_at" in result

    def test_write_with_requirements(self, tmp_path):
        """_write_skill_json stores requirements list."""
        from core.skill_package_manager import SkillPackageManager, SkillInfo, SkillInstallError
        SkillPackageManager._write_skill_json(
            str(tmp_path),
            "https://example.com/repo",
            "v1.0.0",
            requirements=["requests>=2.28", "psycopg2-binary>=2.9"],
        )
        result = SkillPackageManager._read_skill_json(str(tmp_path))
        assert result is not None
        assert result["requirements"] == ["requests>=2.28", "psycopg2-binary>=2.9"]

    def test_write_without_requirements(self, tmp_path):
        """_write_skill_json without requirements omits the key."""
        from core.skill_package_manager import SkillPackageManager, SkillInfo, SkillInstallError
        SkillPackageManager._write_skill_json(str(tmp_path), "https://example.com/repo", "v1.0.0")
        result = SkillPackageManager._read_skill_json(str(tmp_path))
        assert result is not None
        assert "requirements" not in result

    def test_read_missing(self, tmp_path):
        from core.skill_package_manager import SkillPackageManager, SkillInfo, SkillInstallError
        result = SkillPackageManager._read_skill_json(str(tmp_path))
        assert result is None

    def test_read_invalid_json(self, tmp_path):
        from core.skill_package_manager import SkillPackageManager, SkillInfo, SkillInstallError
        path = tmp_path / ".skill.json"
        path.write_text("not json{{{")
        result = SkillPackageManager._read_skill_json(str(tmp_path))
        assert result is None


# ---------------------------------------------------------------------------
# Test: Version resolution
# ---------------------------------------------------------------------------


class TestLatestSemver:
    def test_simple_semver(self):
        from core.skill_package_manager import SkillPackageManager, SkillInfo, SkillInstallError
        tags = ["v0.1.0", "v0.2.0", "v1.0.0"]
        assert SkillPackageManager._latest_semver(tags) == "v1.0.0"

    def test_semver_without_v(self):
        from core.skill_package_manager import SkillPackageManager, SkillInfo, SkillInstallError
        tags = ["0.1.0", "1.0.0", "0.9.0"]
        assert SkillPackageManager._latest_semver(tags) == "1.0.0"

    def test_mixed_v_prefix(self):
        from core.skill_package_manager import SkillPackageManager, SkillInfo, SkillInstallError
        tags = ["v0.1.0", "1.0.0"]
        assert SkillPackageManager._latest_semver(tags) == "1.0.0"

    def test_no_semver_tags(self):
        from core.skill_package_manager import SkillPackageManager, SkillInfo, SkillInstallError
        tags = ["beta", "release-candidate", "stable"]
        result = SkillPackageManager._latest_semver(tags)
        assert result == "stable"  # alphabetically last

    def test_single_tag(self):
        from core.skill_package_manager import SkillPackageManager, SkillInfo, SkillInstallError
        assert SkillPackageManager._latest_semver(["alpha"]) == "alpha"


# ---------------------------------------------------------------------------
# Test: Install (integration with real git)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not os.path.exists("/usr/bin/git"),
    reason="git not available"
)
class TestInstall:
    def test_install_global(self, tmp_path):
        """Install a skill to the global tier."""
        config = _make_config(tmp_path)
        repo = _create_skill_repo(tmp_path, name="my_skill")

        agents_dir = str(tmp_path / "home" / ".agents")
        workspace_dir = str(tmp_path / "workspace")
        os.makedirs(os.path.join(agents_dir, "skills"))
        os.makedirs(workspace_dir)

        mgr = SkillPackageManager(
            config,
            working_dir=str(tmp_path),
            agents_dir=agents_dir,
            workspace_dir=workspace_dir,
        )

        name = mgr.install(repo)
        assert name == "my_skill"

        # Check skill directory exists
        skill_dir = os.path.join(agents_dir, "skills", "my_skill")
        assert os.path.isdir(skill_dir)
        assert os.path.isfile(os.path.join(skill_dir, "SKILL.md"))

        # Check no .git/ directory
        assert not os.path.isdir(os.path.join(skill_dir, ".git"))

        # Check .skill.json
        meta_file = os.path.join(skill_dir, ".skill.json")
        assert os.path.isfile(meta_file)
        meta = json.loads(open(meta_file).read())
        assert "source" in meta
        assert meta["version"] == "v0.1.0"

        # Check config was updated
        installed = config.get("skills.installed", {})
        assert "my_skill" in installed
        assert installed["my_skill"]["version"] == "v0.1.0"

    def test_install_local(self, tmp_path):
        """Install a skill to the project-local tier."""
        config = _make_config(tmp_path)
        repo = _create_skill_repo(tmp_path, name="local_skill")

        # Create working directory
        wd = str(tmp_path / "project")

        mgr = SkillPackageManager(config, working_dir=wd)
        name = mgr.install(repo, local=True)
        assert name == "local_skill"

        # Check skill directory exists in project-local tier
        skill_dir = os.path.join(wd, ".agents", "skills", "local_skill")
        assert os.path.isdir(skill_dir)
        assert not os.path.isdir(os.path.join(skill_dir, ".git"))

    def test_install_with_subdir(self, tmp_path):
        """Install a skill from a monorepo subdirectory."""
        config = _make_config(tmp_path)

        # Create a monorepo with a skill in a subdirectory
        repo_dir = tmp_path / "repos" / "monorepo"
        skill_subdir = repo_dir / "skills" / "my_sub_skill"
        os.makedirs(skill_subdir)
        _write_skill_md(str(skill_subdir), "my_sub_skill", "Subdir skill")
        init_path = os.path.join(str(skill_subdir), "__init__.py")
        with open(init_path, "w") as fh:
            fh.write('"""Subdir skill."""\nSKILL_SERVICES = {}\n')

        # Also add a root file so git has something to commit
        (repo_dir / "README.md").write_text("# Monorepo\n")
        _make_git_repo(str(repo_dir), "v0.2.0")

        agents_dir = str(tmp_path / "home" / ".agents")
        workspace_dir = str(tmp_path / "workspace")
        os.makedirs(os.path.join(agents_dir, "skills"))
        os.makedirs(workspace_dir)

        wd = str(tmp_path / "project")
        os.makedirs(wd)

        mgr = SkillPackageManager(
            config,
            working_dir=wd,
            agents_dir=agents_dir,
            workspace_dir=workspace_dir,
        )

        name = mgr.install(
            str(repo_dir),
            subdir="skills/my_sub_skill",
            version="v0.2.0",
        )
        assert name == "my_sub_skill"

        skill_dir = os.path.join(agents_dir, "skills", "my_sub_skill")
        assert os.path.isdir(skill_dir)
        assert os.path.isfile(os.path.join(skill_dir, "SKILL.md"))
        # The README should NOT be copied (only the subdir)
        assert not os.path.isfile(os.path.join(skill_dir, "README.md"))

    def test_install_no_skill_md_fails(self, tmp_path):
        """Cloning a repo without SKILL.md raises SkillInstallError."""
        config = _make_config(tmp_path)
        # Create a repo with no SKILL.md
        repo_dir = tmp_path / "repos" / "bad_repo"
        os.makedirs(repo_dir)
        (repo_dir / "README.md").write_text("# Not a skill")
        _make_git_repo(str(repo_dir), "v0.1.0")

        wd = str(tmp_path / "project")
        os.makedirs(wd)

        mgr = SkillPackageManager(config, working_dir=wd)
        with pytest.raises(SkillInstallError, match="No SKILL.md"):
            mgr.install(str(repo_dir), version="v0.1.0")

    def test_install_invalid_name_fails(self, tmp_path):
        """Skill with invalid name in SKILL.md raises SkillInstallError."""
        config = _make_config(tmp_path)
        repo_dir = tmp_path / "repos" / "bad_name"
        os.makedirs(repo_dir)
        skill_md = os.path.join(str(repo_dir), "SKILL.md")
        with open(skill_md, "w") as fh:
            fh.write("---\nname: my skill!\ndescription: Bad name\n---\n")
        init_path = os.path.join(str(repo_dir), "__init__.py")
        with open(init_path, "w") as fh:
            fh.write('"""Bad."""\n')
        _make_git_repo(str(repo_dir), "v0.1.0")

        wd = str(tmp_path / "project")
        os.makedirs(wd)

        mgr = SkillPackageManager(config, working_dir=wd)
        with pytest.raises(SkillInstallError, match="Invalid skill name"):
            mgr.install(str(repo_dir), version="v0.1.0")


# ---------------------------------------------------------------------------
# Test: Remove
# ---------------------------------------------------------------------------


class TestRemove:
    def test_remove_existing(self, tmp_path):
        """Remove a skill directory and clean config."""
        config = _make_config(tmp_path)

        agents_dir = str(tmp_path / "home" / ".agents")
        workspace_dir = str(tmp_path / "workspace")
        skill_dir = os.path.join(agents_dir, "skills", "test_rm")
        os.makedirs(skill_dir)
        with open(os.path.join(skill_dir, "SKILL.md"), "w") as fh:
            fh.write("---\nname: test_rm\ndescription: test\n---\n")

        mgr = SkillPackageManager(
            config,
            working_dir=str(tmp_path),
            agents_dir=agents_dir,
            workspace_dir=workspace_dir,
        )

        result = mgr.remove("test_rm")
        assert result is True
        assert not os.path.isdir(skill_dir)

    def test_remove_nonexistent(self, tmp_path):
        """Removing a skill that doesn't exist returns False."""
        config = _make_config(tmp_path)
        mgr = SkillPackageManager(config, working_dir=str(tmp_path))
        result = mgr.remove("nonexistent_skill")
        assert result is False


# ---------------------------------------------------------------------------
# Test: List
# ---------------------------------------------------------------------------


class TestListSkills:
    def test_list_discovered_skills(self, tmp_path):
        """list_skills returns skills discovered by scanning tiers."""
        config = _make_config(tmp_path)

        # Create a fake skill in the global tier
        agents_dir = str(tmp_path / "home" / ".agents")
        skill_dir = os.path.join(agents_dir, "skills", "test_list")
        os.makedirs(skill_dir)
        with open(os.path.join(skill_dir, "SKILL.md"), "w") as fh:
            fh.write("---\nname: test_list\ndescription: A listing test\n---\n")

        workspace_dir = str(tmp_path / "workspace")
        os.makedirs(os.path.join(workspace_dir, "skills"), exist_ok=True)
        wd = str(tmp_path / "project")
        os.makedirs(os.path.join(wd, ".agents", "skills"), exist_ok=True)

        mgr = SkillPackageManager(
            config,
            working_dir=wd,
            agents_dir=agents_dir,
            workspace_dir=workspace_dir,
        )

        mgr.list_skills()

        # Should find our test skill
        all_skills = mgr.list_skills()
        names = [p.name for p in all_skills]
        assert "test_list" in names

        # Find the specific skill
        skill_info = next(p for p in all_skills if p.name == "test_list")
        assert skill_info.description == "A listing test"
        assert skill_info.tier == "global"
        assert skill_info.managed is False

    def test_list_managed_skill(self, tmp_path):
        """list_skills shows .skill.json metadata for managed skills."""
        config = _make_config(tmp_path)

        agents_dir = str(tmp_path / "home" / ".agents")
        skill_dir = os.path.join(agents_dir, "skills", "managed_s")
        os.makedirs(skill_dir)
        with open(os.path.join(skill_dir, "SKILL.md"), "w") as fh:
            fh.write("---\nname: managed_s\ndescription: managed skill\n---\n")
        # Write .skill.json
        with open(os.path.join(skill_dir, ".skill.json"), "w") as fh:
            json.dump({
                "source": "https://github.com/test/managed-p",
                "version": "v0.5.0",
                "installed_at": "2025-05-21T10:00:00+00:00",
            }, fh)

        workspace_dir = str(tmp_path / "workspace")
        os.makedirs(os.path.join(workspace_dir, "skills"), exist_ok=True)
        wd = str(tmp_path / "project")
        os.makedirs(os.path.join(wd, ".agents", "skills"), exist_ok=True)

        mgr = SkillPackageManager(
            config,
            working_dir=wd,
            agents_dir=agents_dir,
            workspace_dir=workspace_dir,
        )

        all_skills = mgr.list_skills()
        skill_info = next(p for p in all_skills if p.name == "managed_s")

        assert skill_info.managed is True
        assert skill_info.version == "v0.5.0"
        assert skill_info.source == "https://github.com/test/managed-p"


# ---------------------------------------------------------------------------
# Test: Config integration
# ---------------------------------------------------------------------------


class TestConfigIntegration:
    def test_config_set_installed(self, tmp_path):
        """_config_set_installed writes to config and saves."""
        config = _make_config(tmp_path)
        wd = str(tmp_path / "project")
        os.makedirs(wd)

        mgr = SkillPackageManager(config, working_dir=wd)
        mgr._config_set_installed(
            "my_skill",
            "https://github.com/test/my_skill",
            "v1.0.0",
        )

        installed = config.get("skills.installed", {})
        assert "my_skill" in installed
        assert installed["my_skill"]["version"] == "v1.0.0"
        assert installed["my_skill"]["source"] == "https://github.com/test/my_skill"

        # Should also default to enabled
        enabled = config.get("skills.enabled", {})
        assert enabled.get("my_skill") is True

    def test_config_remove_installed(self, tmp_path):
        """_config_remove_installed removes from config and saves."""
        config = _make_config(tmp_path)
        wd = str(tmp_path / "project")
        os.makedirs(wd)

        mgr = SkillPackageManager(config, working_dir=wd)
        mgr._config_set_installed("to_remove", "https://example.com", "v1.0.0")
        assert "to_remove" in config.get("skills.installed", {})

        mgr._config_remove_installed("to_remove")
        assert "to_remove" not in config.get("skills.installed", {})
        assert "to_remove" not in config.get("skills.enabled", {})


# ---------------------------------------------------------------------------
# Test: Requirement installation
# ---------------------------------------------------------------------------


class TestInstallRequirements:
    def test_install_requirements_calls_installer(self, tmp_path, monkeypatch):
        """_install_requirements invokes the package installer."""
        config = _make_config(tmp_path)
        mgr = SkillPackageManager(config, working_dir=str(tmp_path))

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
        mgr = SkillPackageManager(config, working_dir=str(tmp_path))

        calls = []

        def mock_run(cmd, **kwargs):
            calls.append(cmd)
            return subprocess.CompletedProcess(args=cmd, returncode=0)

        monkeypatch.setattr(subprocess, "run", mock_run)

        mgr._install_requirements([])
        assert calls == []

    def test_install_requirements_raises_on_failure(self, tmp_path, monkeypatch):
        """_install_requirements raises SkillInstallError on pip failure."""
        config = _make_config(tmp_path)
        mgr = SkillPackageManager(config, working_dir=str(tmp_path))

        def mock_run(cmd, **kwargs):
            result = subprocess.CompletedProcess(args=cmd, returncode=1)
            result.stdout = ""
            result.stderr = "ERROR: No matching distribution"
            return result

        monkeypatch.setattr(subprocess, "run", mock_run)

        with pytest.raises(SkillInstallError, match="Failed to install"):
            mgr._install_requirements(["nonexistent-package"])


class TestFindPipInstaller:
    def test_find_pip_installer_with_uv(self, tmp_path, monkeypatch):
        """_find_pip_installer prefers uv if available."""
        from core.skill_package_manager import SkillPackageManager, SkillInfo, SkillInstallError

        def mock_run(cmd, **kwargs):
            if cmd[0] == "uv":
                result = subprocess.CompletedProcess(args=cmd, returncode=0)
                result.stdout = "uv 0.10.7"
                return result
            return subprocess.CompletedProcess(args=cmd, returncode=1)

        monkeypatch.setattr(subprocess, "run", mock_run)
        result = SkillPackageManager._find_pip_installer()
        assert result == ["uv", "pip"]

    def test_find_pip_installer_fallback(self, tmp_path, monkeypatch):
        """_find_pip_installer falls back to pip if uv is unavailable."""
        import sys
        from core.skill_package_manager import SkillPackageManager, SkillInfo, SkillInstallError

        def mock_run(cmd, **kwargs):
            if cmd[0] == "uv":
                raise FileNotFoundError("uv not found")
            return subprocess.CompletedProcess(args=cmd, returncode=0)

        monkeypatch.setattr(subprocess, "run", mock_run)
        result = SkillPackageManager._find_pip_installer()
        assert result == [sys.executable, "-m", "pip"]