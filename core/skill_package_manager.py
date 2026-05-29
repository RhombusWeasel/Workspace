"""Skill manager — install, update, remove, and list skills from git repos.

Manages skills installed from git repositories.  A skill is a directory
containing a ``SKILL.md`` manifest.  Installed skills live in the 3-tier
skill directories (bundled, global, project-local).

Git-installed skills are always installed from a tagged release (git tag).
The ``.git/`` directory is stripped after cloning, so installed skills are
just source files — no nested git repos, no submodule conflicts.

Install metadata (source URL, version, timestamp) is stored in a
``.skill.json`` file inside each installed skill directory.  User
preferences (enabled/disabled) are stored in the layered config under
``skills.enabled``.  Install metadata is also mirrored to
``skills.installed`` in config so it's visible in the ConfigPanel.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.config import Config

from core.paths import agents_dir as _default_agents_dir
from core.paths import cody_dir as _default_cody_dir


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class SkillInfo:
    """Rich information about a discovered or installed skill."""

    name: str
    """Skill name from SKILL.md frontmatter."""

    description: str
    """Short description from SKILL.md frontmatter."""

    location: str
    """Absolute path to the skill directory."""

    version: str | None = None
    """Installed version (from .skill.json), None if not git-managed."""

    source: str | None = None
    """Git source URL (from .skill.json), None if not git-managed."""

    installed_at: str | None = None
    """ISO-8601 timestamp of installation (from .skill.json)."""

    tier: str = "unknown"
    """Which tier the skill was discovered in: 'bundled', 'global', 'project'."""

    enabled: bool = True
    """Whether the skill is enabled (from config skills.enabled)."""

    managed: bool = False
    """Whether the skill has a .skill.json (installed via skill manager)."""

    requirements: list[str] = field(default_factory=list)
    """Python package requirements declared in SKILL.md frontmatter."""


class SkillInstallError(Exception):
    """Raised when a skill installation operation fails."""


# ---------------------------------------------------------------------------
# Skill manager
# ---------------------------------------------------------------------------


class SkillPackageManager:
    """Install, update, remove, and list skills from git repos.

    Parameters
    ----------
    config:
        The application config instance (for reading/writing skill preferences).
    working_dir:
        The current working directory (for project-local installs).
    agents_dir:
        The global ``~/.agents`` directory.  Defaults to
        :func:`core.paths.agents_dir` if not specified.
    cody_dir:
        The Cody installation directory.  Defaults to
        :func:`core.paths.cody_dir` if not specified.
    """

    def __init__(
        self,
        config: Config,
        working_dir: str,
        *,
        agents_dir: str | None = None,
        cody_dir: str | None = None,
    ) -> None:
        self._config = config
        self._working_dir = working_dir
        self._agents_dir = agents_dir or _default_agents_dir()
        self._cody_dir = cody_dir or _default_cody_dir()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def install(
        self,
        url: str,
        *,
        version: str | None = None,
        local: bool = False,
        subdir: str | None = None,
    ) -> str:
        """Install a skill from a git repository.

        Clones the repo (shallow, specific tag), reads the SKILL.md manifest
        for the skill name, strips the ``.git/`` directory, and moves the
        result to the appropriate tier directory.

        Parameters
        ----------
        url:
            Git repository URL (HTTPS or SSH).
        version:
            Specific tag to install.  If omitted, the latest semver tag
            is used.  If no tags exist, falls back to HEAD.
        local:
            Install to project-local tier (``{wd}/.agents/skills/``)
            instead of global tier (``~/.agents/skills/``).
        subdir:
            Subdirectory within the repo that contains the skill.

        Returns
        -------
        str
            The installed skill name (from SKILL.md).

        Raises
        ------
        SkillInstallError
            If the repo can't be cloned, SKILL.md is missing, or the
            skill directory already exists.
        """
        # 1. Resolve version
        if version is None:
            version = self._find_latest_tag(url)
            if version is None:
                # No tags — use HEAD
                version = "HEAD"

        # 2. Clone to temp
        temp_dir = self._clone_to_temp(url, version)

        try:
            # 3. If subdir specified, use that subdirectory
            if subdir:
                skill_source = os.path.join(temp_dir, subdir)
                if not os.path.isdir(skill_source):
                    raise SkillInstallError(
                        f"Subdirectory '{subdir}' not found in repository"
                    )
            else:
                skill_source = temp_dir

            # 4. Validate SKILL.md
            skill_md = os.path.join(skill_source, "SKILL.md")
            if not os.path.isfile(skill_md):
                raise SkillInstallError(
                    "No SKILL.md found in repository. "
                    "Is this a valid Cody skill?"
                )

            parsed = self._parse_skill_md(skill_md)
            if parsed is None:
                raise SkillInstallError(
                    "SKILL.md is missing required 'name' or 'description' fields."
                )

            name = parsed["name"]

            # Sanity check the name
            if not re.match(r'^[a-zA-Z0-9_-]+$', name):
                raise SkillInstallError(
                    f"Invalid skill name '{name}'. "
                    "Use only letters, numbers, hyphens, and underscores."
                )

            # 5. Determine destination
            dest_dir = self._skill_dir(name, local=local)

            # 6. Remove existing if present
            if os.path.isdir(dest_dir):
                shutil.rmtree(dest_dir)

            # 7. Ensure parent directory exists
            os.makedirs(os.path.dirname(dest_dir), exist_ok=True)

            # 8. Copy skill files (preserving subdir if specified)
            # When subdir is used, we copy the subdir contents, not the whole repo
            shutil.copytree(skill_source, dest_dir, dirs_exist_ok=True)

            # 9. Remove .git/ directory
            git_dir = os.path.join(dest_dir, ".git")
            if os.path.isdir(git_dir):
                shutil.rmtree(git_dir)

            # 10. Install Python requirements (if any)
            requirements = parsed.get("requirements", [])
            if requirements:
                self._install_requirements(requirements)

            # 11. Write .skill.json (includes requirements)
            self._write_skill_json(dest_dir, url, version, requirements)

            # 12. Update config
            self._config_set_installed(name, url, version)

            return name

        finally:
            # Clean up temp directory
            if os.path.isdir(temp_dir):
                shutil.rmtree(temp_dir, ignore_errors=True)

    def update(
        self,
        name: str,
        *,
        version: str | None = None,
        local: bool = False,
    ) -> str | None:
        """Update an installed skill to a newer version.

        Parameters
        ----------
        name:
            Skill name (as shown in SKILL.md).
        version:
            Specific tag to update to.  If omitted, checks for the
            latest tag newer than the installed version.
        local:
            Whether to look in the project-local tier.

        Returns
        -------
        str | None
            The new version string, or None if already up to date.

        Raises
        ------
        SkillInstallError
            If the skill is not installed or not git-managed.
        """
        skill_dir = self._find_skill_dir(name, local=local)
        if skill_dir is None:
            raise SkillInstallError(f"Skill '{name}' is not installed.")

        # Read existing metadata
        meta = self._read_skill_json(skill_dir)
        if meta is None:
            raise SkillInstallError(
                f"Skill '{name}' has no .skill.json. "
                "It may be a bundled or manually-created skill that "
                "cannot be updated via the skill manager."
            )

        source = meta.get("source", "")
        current_version = meta.get("version", "")

        # Resolve target version
        if version is None:
            version = self._find_latest_tag(source)
            if version is None:
                raise SkillInstallError(
                    f"No tags found in '{source}'. "
                    "Specify a version with --version."
                )

        # No update needed?
        if version == current_version:
            return None

        # Re-install from source
        new_version = self.install(source, version=version, local=local)
        return new_version

    def update_all(self) -> dict[str, str | None]:
        """Update all git-managed skills.

        Returns
        -------
        dict[str, str | None]
            Mapping of skill name → new version string, or None if
            already up to date.  Only includes git-managed skills.
        """
        results: dict[str, str | None] = {}
        all_skills = self.list_skills()

        for info in all_skills:
            if not info.managed:
                continue
            if info.source is None:
                continue
            try:
                new_version = self.update(info.name)
                results[info.name] = new_version
            except SkillInstallError:
                results[info.name] = None

        return results

    def remove(self, name: str, *, local: bool = False) -> bool:
        """Remove an installed skill.

        Deletes the skill directory and removes config entries.

        Parameters
        ----------
        name:
            Skill name to remove.
        local:
            Whether to remove from the project-local tier.

        Returns
        -------
        bool
            True if the skill was found and removed, False otherwise.
        """
        # Check global tier first (unless --local specified)
        if local:
            skill_dir = os.path.join(
                self._working_dir, ".agents", "skills", name
            )
        else:
            # Try global tier first, then project tier
            skill_dir = self._find_skill_dir(name)
            if skill_dir is None:
                return False

        if not os.path.isdir(skill_dir):
            return False

        shutil.rmtree(skill_dir)
        self._config_remove_installed(name)
        return True

    def list_skills(self) -> list[SkillInfo]:
        """List all discovered skills with version and source info.

        Reconciles skill directories discovered by scanning the three
        tiers with ``.skill.json`` metadata and config preferences.
        """
        # Scan all three tiers for skill directories with SKILL.md
        tier_dirs = [
            os.path.join(self._cody_dir, "skills"),
            os.path.join(self._agents_dir, "skills"),
            os.path.join(self._working_dir, ".agents", "skills"),
        ]
        tier_names = ["bundled", "global", "project"]

        enabled_map = self._config.get("skills.enabled", {}) or {}
        if isinstance(enabled_map, list):
            enabled_map = {}
        installed_map = self._config.get("skills.installed", {}) or {}
        if isinstance(installed_map, list):
            installed_map = {}

        # Discover skills across tiers (later tiers override earlier)
        discovered: dict[str, tuple[str, str]] = {}  # name → (path, tier)
        for tier_dir, tier_name in zip(tier_dirs, tier_names):
            if not os.path.isdir(tier_dir):
                continue
            try:
                entries = sorted(os.listdir(tier_dir))
            except OSError:
                continue
            for entry in entries:
                skill_dir = os.path.join(tier_dir, entry)
                md_path = os.path.join(skill_dir, "SKILL.md")
                if os.path.isfile(md_path):
                    discovered[entry] = (skill_dir, tier_name)

        result: list[SkillInfo] = []
        for name, (skill_dir, tier) in discovered.items():
            skill_md = os.path.join(skill_dir, "SKILL.md")
            parsed = self._parse_skill_md(skill_md)
            description = parsed.get("description", "") if parsed else ""

            # Read .skill.json for managed skills
            meta = self._read_skill_json(skill_dir)
            managed = meta is not None

            # Config state
            is_enabled = enabled_map.get(name, True)

            # Read SKILL.md for requirements
            requirements_list = parsed.get("requirements", []) if parsed else []

            result.append(SkillInfo(
                name=name,
                description=description,
                location=skill_dir,
                version=meta.get("version") if meta else None,
                source=meta.get("source") if meta else None,
                installed_at=meta.get("installed_at") if meta else None,
                tier=tier,
                enabled=is_enabled,
                managed=managed,
                requirements=requirements_list,
            ))

        # Also include "missing" skills — in config but not on disk
        for name, info in installed_map.items():
            if not any(p.name == name for p in result):
                result.append(SkillInfo(
                    name=name,
                    description="(missing from disk)",
                    location="",
                    version=info.get("version") if isinstance(info, dict) else None,
                    source=info.get("source") if isinstance(info, dict) else None,
                    installed_at=info.get("installed_at") if isinstance(info, dict) else None,
                    tier="missing",
                    enabled=enabled_map.get(name, True),
                    managed=True,
                ))

        return sorted(result, key=lambda p: p.name)

    # ------------------------------------------------------------------
    # Git helpers
    # ------------------------------------------------------------------

    def _clone_to_temp(self, url: str, version: str) -> str:
        """Clone a git repo to a temporary directory.

        Uses ``git clone --depth 1 --branch <version>`` for efficiency.
        Falls back to ``git clone --depth 1`` if the version is HEAD.

        Returns the temp directory path (caller must clean up).
        """
        self._check_git()

        temp_dir = tempfile.mkdtemp(prefix="cody_skill_")

        try:
            cmd = ["git", "clone", "--depth", "1"]
            if version and version != "HEAD":
                cmd.extend(["--branch", version])
            cmd.extend([url, temp_dir])

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
            )

            if result.returncode != 0:
                # Clean up on failure
                if os.path.isdir(temp_dir):
                    shutil.rmtree(temp_dir, ignore_errors=True)
                raise SkillInstallError(
                    f"Failed to clone '{url}'"
                    f" (version: {version}): {result.stderr.strip()}"
                )

            return temp_dir

        except subprocess.TimeoutExpired:
            if os.path.isdir(temp_dir):
                shutil.rmtree(temp_dir, ignore_errors=True)
            raise SkillInstallError(
                f"Clone of '{url}' timed out after 120 seconds."
            )

    def _find_latest_tag(self, url: str) -> str | None:
        """Find the latest semver tag in a git repository.

        Uses ``git ls-remote --tags`` to list tags, then picks the
        latest by semver comparison.  Returns None if no tags exist.
        """
        self._check_git()

        try:
            result = subprocess.run(
                ["git", "ls-remote", "--tags", url],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except subprocess.TimeoutExpired:
            raise SkillInstallError(f"Tag lookup for '{url}' timed out.")

        if result.returncode != 0:
            raise SkillInstallError(f"Failed to list tags for '{url}': {result.stderr.strip()}")

        # Parse tags from ls-remote output
        # Format: <hash>\trefs/tags/<tag>
        # Skip ^{} dereferenced tags
        tags: list[str] = []
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            parts = line.split("\t")
            if len(parts) < 2:
                continue
            ref = parts[1]
            if ref.endswith("^{}"):
                continue
            # Extract tag name from refs/tags/<tag>
            tag = ref.replace("refs/tags/", "")
            tags.append(tag)

        if not tags:
            return None

        # Sort by semver and return the latest
        return self._latest_semver(tags)

    @staticmethod
    def _latest_semver(tags: list[str]) -> str:
        """Return the latest semver tag from a list of tag strings.

        Handles tags like ``v1.2.3``, ``1.2.3``, ``v0.1.0``, etc.
        Falls back to the last tag alphabetically if no semver tags found.
        """
        semver_pattern = re.compile(
            r'^v?(\d+)\.(\d+)\.(\d+)$'
        )
        parsed: list[tuple[tuple[int, ...], str]] = []
        fallback: list[str] = []

        for tag in tags:
            m = semver_pattern.match(tag)
            if m:
                major, minor, patch = int(m.group(1)), int(m.group(2)), int(m.group(3))
                parsed.append(((major, minor, patch), tag))
            else:
                fallback.append(tag)

        if parsed:
            parsed.sort(key=lambda x: x[0])
            return parsed[-1][1]

        # No semver tags — return the last tag alphabetically
        return sorted(fallback)[-1] if fallback else tags[-1]

    @staticmethod
    def _check_git() -> None:
        """Verify that git is available on the system."""
        try:
            subprocess.run(
                ["git", "--version"],
                capture_output=True,
                timeout=10,
            )
        except FileNotFoundError:
            raise SkillInstallError(
                "git is not installed. "
                "Please install git to use the skill manager."
            )
        except subprocess.TimeoutExpired:
            raise SkillInstallError("git check timed out.")

    # ------------------------------------------------------------------
    # Requirement installation
    # ------------------------------------------------------------------

    @staticmethod
    def _find_pip_installer() -> list[str]:
        """Return the command prefix for installing packages.

        Prefers ``uv pip`` if available (fast, used by the project),
        falls back to the venv's ``pip`` module.

        Returns a list suitable for ``subprocess.run()`` — e.g.
        ``["uv", "pip"]`` or ``["/path/to/.venv/bin/python", "-m", "pip"]``.
        """
        # Try uv first — it's what this project uses (pyproject.toml)
        try:
            result = subprocess.run(
                ["uv", "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                return ["uv", "pip"]
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        # Fall back to the current interpreter's pip
        return [sys.executable, "-m", "pip"]

    def _install_requirements(self, requirements: list[str]) -> None:
        """Install Python packages into the project's virtual environment.

        Uses ``uv pip install`` if available (the project's preferred
        installer), falling back to ``pip install``.  Requirements are
        installed into the same venv that runs Cody, since skills are
        loaded in-process and need their dependencies on ``sys.path``.

        Raises :class:`SkillInstallError` if installation fails.
        """
        if not requirements:
            return

        installer = self._find_pip_installer()
        cmd = [*installer, "install", *requirements]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,  # 5 minutes for large packages
            )
        except subprocess.TimeoutExpired:
            raise SkillInstallError(
                f"Installing requirements timed out after 300 seconds: "
                f"{', '.join(requirements)}"
            )

        if result.returncode != 0:
            raise SkillInstallError(
                f"Failed to install requirements: {', '.join(requirements)}\n"
                f"{result.stderr.strip()}"
            )

    # ------------------------------------------------------------------
    # SKILL.md parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_skill_md(path: str) -> dict | None:
        """Parse a SKILL.md file, returning a dict with keys *name*,
        *description*, *body*, and optionally *requirements*.

        Returns ``None`` if the file is invalid or missing required
        frontmatter fields.

        The frontmatter supports simple YAML: key-value pairs and lists
        (lines starting with ``- ``).  Example::

            ---
            name: my_skill
            description: Does things
            requirements:
              - requests>=2.28
              - psycopg2-binary>=2.9
            ---
        """
        try:
            with open(path) as fh:
                text = fh.read()
        except OSError:
            return None

        lines = text.split("\n")

        # Find the first --- delimiter
        start = -1
        for i, line in enumerate(lines):
            if line.strip() == "---":
                start = i
                break
        if start == -1:
            return None

        # Find the next --- delimiter
        end = -1
        for i in range(start + 1, len(lines)):
            if lines[i].strip() == "---":
                end = i
                break
        if end == -1:
            return None

        fm_lines = lines[start + 1 : end]
        body = "\n".join(lines[end + 1 :]).strip()

        # Parse frontmatter: key: value pairs and key:\n  - item lists
        meta: dict[str, str | list[str]] = {}
        i = 0
        while i < len(fm_lines):
            line = fm_lines[i]
            stripped = line.strip()
            if not stripped:
                i += 1
                continue

            # Check if this is a list item (belongs to a previous key)
            if stripped.startswith("- "):
                i += 1
                continue  # handled below when the key is parsed

            if ":" not in stripped:
                i += 1
                continue

            key, _, value = stripped.partition(":")
            key = key.strip()
            value = value.strip()

            # Check if this key starts a list (value is empty, next lines
            # are "- item" entries)
            if value == "":
                # Look ahead for list items
                items: list[str] = []
                j = i + 1
                while j < len(fm_lines):
                    next_stripped = fm_lines[j].strip()
                    if next_stripped.startswith("- "):
                        items.append(next_stripped[2:].strip())
                        j += 1
                    elif next_stripped == "":
                        j += 1
                    else:
                        break
                if items:
                    meta[key] = items
                    i = j
                else:
                    meta[key] = value
                    i += 1
            else:
                meta[key] = value
                i += 1

        if "name" not in meta or "description" not in meta:
            return None

        # Build result — separate requirements into its own key
        result: dict = {
            "name": meta["name"],
            "description": meta["description"],
            "body": body,
        }

        # requirements is a special list field
        reqs = meta.get("requirements")
        if isinstance(reqs, list):
            result["requirements"] = reqs
        elif isinstance(reqs, str) and reqs:
            # Comma-separated fallback
            result["requirements"] = [r.strip() for r in reqs.split(",") if r.strip()]
        else:
            result["requirements"] = []

        # Preserve other arbitrary frontmatter keys
        for k, v in meta.items():
            if k not in ("name", "description", "requirements"):
                result[k] = v

        return result

    # ------------------------------------------------------------------
    # .skill.json management
    # ------------------------------------------------------------------

    @staticmethod
    def _write_skill_json(
        skill_dir: str,
        source: str,
        version: str,
        requirements: list[str] | None = None,
    ) -> None:
        """Write a .skill.json metadata file into the skill directory."""
        meta = {
            "source": source,
            "version": version,
            "installed_at": datetime.now(timezone.utc).isoformat(),
        }
        if requirements:
            meta["requirements"] = requirements
        path = os.path.join(skill_dir, ".skill.json")
        with open(path, "w") as fh:
            json.dump(meta, fh, indent=2)
            fh.write("\n")

    @staticmethod
    def _read_skill_json(skill_dir: str) -> dict | None:
        """Read .skill.json from a skill directory, or None if missing.

        Also checks for legacy ``.plugin.json`` files created before
        the plugins→skills merge.
        """
        path = os.path.join(skill_dir, ".skill.json")
        if os.path.isfile(path):
            try:
                with open(path) as fh:
                    return json.load(fh)
            except (json.JSONDecodeError, OSError):
                return None

        # Legacy: check for .plugin.json (pre-merge)
        legacy_path = os.path.join(skill_dir, ".plugin.json")
        if os.path.isfile(legacy_path):
            try:
                with open(legacy_path) as fh:
                    return json.load(fh)
            except (json.JSONDecodeError, OSError):
                return None

        return None

    # ------------------------------------------------------------------
    # Config helpers
    # ------------------------------------------------------------------

    def _config_set_installed(self, name: str, source: str, version: str) -> None:
        """Record an installed skill in config (skills.installed + skills.enabled)."""
        installed = dict(self._config.get("skills.installed", {}) or {})
        installed[name] = {
            "source": source,
            "version": version,
            "installed_at": datetime.now(timezone.utc).isoformat(),
        }
        self._config.set("skills.installed", installed)

        # Default to enabled
        enabled = dict(self._config.get("skills.enabled", {}) or {})
        if name not in enabled:
            enabled[name] = True
            self._config.set("skills.enabled", enabled)

        self._config.save()

    def _config_remove_installed(self, name: str) -> None:
        """Remove an installed skill from config."""
        installed = dict(self._config.get("skills.installed", {}) or {})
        installed.pop(name, None)
        self._config.set("skills.installed", installed)

        # Also remove from enabled map
        enabled = dict(self._config.get("skills.enabled", {}) or {})
        enabled.pop(name, None)
        self._config.set("skills.enabled", enabled)

        self._config.save()

    # ------------------------------------------------------------------
    # Path helpers
    # ------------------------------------------------------------------

    def _skill_dir(self, name: str, *, local: bool = False) -> str:
        """Return the target directory for a skill install."""
        if local:
            return os.path.join(self._working_dir, ".agents", "skills", name)
        return os.path.join(self._agents_dir, "skills", name)

    def _find_skill_dir(self, name: str, *, local: bool = False) -> str | None:
        """Find a skill directory by name, searching tiers in order.

        If *local* is True, only checks the project-local tier.
        Otherwise checks global then project-local.
        """
        if local:
            path = os.path.join(
                self._working_dir, ".agents", "skills", name
            )
            return path if os.path.isdir(path) else None

        # Check global tier
        global_path = os.path.join(self._agents_dir, "skills", name)
        if os.path.isdir(global_path):
            return global_path

        # Check project-local tier
        local_path = os.path.join(
            self._working_dir, ".agents", "skills", name
        )
        if os.path.isdir(local_path):
            return local_path

        return None


# ---------------------------------------------------------------------------
# Config defaults — registered at import time
# ---------------------------------------------------------------------------

from core.config import register_defaults  # noqa: E402

register_defaults(
    {
        "skills": {
            "enabled": {},
            "installed": {},
        }
    }
)