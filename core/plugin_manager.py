"""Plugin manager — install, update, remove, and list plugins from git repos.

Manages plugins installed from git repositories.  A plugin is a directory
containing a ``SKILL.md`` manifest.  Installed plugins live in the 3-tier
plugin directories (bundled, global, project-local).

Git-installed plugins are always installed from a tagged release (git tag).
The ``.git/`` directory is stripped after cloning, so installed plugins are
just source files — no nested git repos, no submodule conflicts.

Install metadata (source URL, version, timestamp) is stored in a
``.plugin.json`` file inside each installed plugin directory.  User
preferences (enabled/disabled) are stored in the layered config under
``plugins.enabled``.  Install metadata is also mirrored to
``plugins.installed`` in config so it's visible in the ConfigPanel.
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
from core.paths import discover_plugins


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class PluginInfo:
    """Rich information about a discovered plugin."""

    name: str
    """Plugin name from SKILL.md frontmatter."""

    description: str
    """Short description from SKILL.md frontmatter."""

    location: str
    """Absolute path to the plugin directory."""

    version: str | None = None
    """Installed version (from .plugin.json), None if not git-managed."""

    source: str | None = None
    """Git source URL (from .plugin.json), None if not git-managed."""

    installed_at: str | None = None
    """ISO-8601 timestamp of installation (from .plugin.json)."""

    tier: str = "unknown"
    """Which tier the plugin was discovered in: 'bundled', 'global', 'project'."""

    enabled: bool = True
    """Whether the plugin is enabled (from config plugins.enabled)."""

    managed: bool = False
    """Whether the plugin has a .plugin.json (installed via plugin manager)."""

    requirements: list[str] = field(default_factory=list)
    """Python package requirements declared in SKILL.md frontmatter."""


class PluginError(Exception):
    """Raised when a plugin operation fails."""


# ---------------------------------------------------------------------------
# Plugin manager
# ---------------------------------------------------------------------------


class PluginManager:
    """Install, update, remove, and list plugins from git repos.

    Parameters
    ----------
    config:
        The application config instance (for reading/writing plugin preferences).
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
        """Install a plugin from a git repository.

        Clones the repo (shallow, specific tag), reads the SKILL.md manifest
        for the plugin name, strips the ``.git/`` directory, and moves the
        result to the appropriate tier directory.

        Parameters
        ----------
        url:
            Git repository URL (HTTPS or SSH).
        version:
            Specific tag to install.  If omitted, the latest semver tag
            is used.  If no tags exist, falls back to HEAD.
        local:
            Install to project-local tier (``{wd}/.agents/plugins/``)
            instead of global tier (``~/.agents/plugins/``).
        subdir:
            Subdirectory within the repo that contains the plugin.

        Returns
        -------
        str
            The installed plugin name (from SKILL.md).

        Raises
        ------
        PluginError
            If the repo can't be cloned, SKILL.md is missing, or the
            plugin directory already exists.
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
                plugin_source = os.path.join(temp_dir, subdir)
                if not os.path.isdir(plugin_source):
                    raise PluginError(
                        f"Subdirectory '{subdir}' not found in repository"
                    )
            else:
                plugin_source = temp_dir

            # 4. Validate SKILL.md
            skill_md = os.path.join(plugin_source, "SKILL.md")
            if not os.path.isfile(skill_md):
                raise PluginError(
                    "No SKILL.md found in repository. "
                    "Is this a valid Cody plugin?"
                )

            parsed = self._parse_skill_md(skill_md)
            if parsed is None:
                raise PluginError(
                    "SKILL.md is missing required 'name' or 'description' fields."
                )

            name = parsed["name"]

            # Sanity check the name
            if not re.match(r'^[a-zA-Z0-9_-]+$', name):
                raise PluginError(
                    f"Invalid plugin name '{name}'. "
                    "Use only letters, numbers, hyphens, and underscores."
                )

            # 5. Determine destination
            dest_dir = self._plugin_dir(name, local=local)

            # 6. Remove existing if present
            if os.path.isdir(dest_dir):
                shutil.rmtree(dest_dir)

            # 7. Ensure parent directory exists
            os.makedirs(os.path.dirname(dest_dir), exist_ok=True)

            # 8. Copy plugin files (preserving subdir if specified)
            # When subdir is used, we copy the subdir contents, not the whole repo
            shutil.copytree(plugin_source, dest_dir, dirs_exist_ok=True)

            # 9. Remove .git/ directory
            git_dir = os.path.join(dest_dir, ".git")
            if os.path.isdir(git_dir):
                shutil.rmtree(git_dir)

            # 10. Install Python requirements (if any)
            requirements = parsed.get("requirements", [])
            if requirements:
                self._install_requirements(requirements)

            # 11. Write .plugin.json (includes requirements)
            self._write_plugin_json(dest_dir, url, version, requirements)

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
        """Update an installed plugin to a newer version.

        Parameters
        ----------
        name:
            Plugin name (as shown in SKILL.md).
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
        PluginError
            If the plugin is not installed or not git-managed.
        """
        plugin_dir = self._find_plugin_dir(name, local=local)
        if plugin_dir is None:
            raise PluginError(f"Plugin '{name}' is not installed.")

        # Read existing metadata
        meta = self._read_plugin_json(plugin_dir)
        if meta is None:
            raise PluginError(
                f"Plugin '{name}' has no .plugin.json. "
                "It may be a bundled or manually-created plugin that "
                "cannot be updated via the plugin manager."
            )

        source = meta.get("source", "")
        current_version = meta.get("version", "")

        # Resolve target version
        if version is None:
            version = self._find_latest_tag(source)
            if version is None:
                raise PluginError(
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
        """Update all git-managed plugins.

        Returns
        -------
        dict[str, str | None]
            Mapping of plugin name → new version string, or None if
            already up to date.  Only includes git-managed plugins.
        """
        results: dict[str, str | None] = {}
        all_plugins = self.list_plugins()

        for info in all_plugins:
            if not info.managed:
                continue
            if info.source is None:
                continue
            try:
                new_version = self.update(info.name)
                results[info.name] = new_version
            except PluginError:
                results[info.name] = None

        return results

    def remove(self, name: str, *, local: bool = False) -> bool:
        """Remove an installed plugin.

        Deletes the plugin directory and removes config entries.

        Parameters
        ----------
        name:
            Plugin name to remove.
        local:
            Whether to remove from the project-local tier.

        Returns
        -------
        bool
            True if the plugin was found and removed, False otherwise.
        """
        # Check global tier first (unless --local specified)
        if local:
            plugin_dir = os.path.join(
                self._working_dir, ".agents", "plugins", name
            )
        else:
            # Try global tier first, then project tier
            plugin_dir = self._find_plugin_dir(name)
            if plugin_dir is None:
                return False

        if not os.path.isdir(plugin_dir):
            return False

        shutil.rmtree(plugin_dir)
        self._config_remove_installed(name)
        return True

    def list_plugins(self) -> list[PluginInfo]:
        """List all discovered plugins with version and source info.

        Reconciles plugin directories discovered by scanning the three
        tiers with ``.plugin.json`` metadata and config preferences.
        """
        # Scan all three tiers for plugin directories with SKILL.md
        tier_dirs = [
            os.path.join(self._cody_dir, "plugins"),
            os.path.join(self._agents_dir, "plugins"),
            os.path.join(self._working_dir, ".agents", "plugins"),
        ]
        tier_names = ["bundled", "global", "project"]

        enabled_map = self._config.get("plugins.enabled", {}) or {}
        if isinstance(enabled_map, list):
            enabled_map = {}
        installed_map = self._config.get("plugins.installed", {}) or {}
        if isinstance(installed_map, list):
            installed_map = {}

        # Discover plugins across tiers (later tiers override earlier)
        discovered: dict[str, tuple[str, str]] = {}  # name > (path, tier)
        for tier_dir, tier_name in zip(tier_dirs, tier_names):
            if not os.path.isdir(tier_dir):
                continue
            try:
                entries = sorted(os.listdir(tier_dir))
            except OSError:
                continue
            for entry in entries:
                plugin_dir = os.path.join(tier_dir, entry)
                md_path = os.path.join(plugin_dir, "SKILL.md")
                if os.path.isfile(md_path):
                    discovered[entry] = (plugin_dir, tier_name)

        result: list[PluginInfo] = []
        for name, (plugin_dir, tier) in discovered.items():
            skill_md = os.path.join(plugin_dir, "SKILL.md")
            parsed = self._parse_skill_md(skill_md)
            description = parsed.get("description", "") if parsed else ""

            # Read .plugin.json for managed plugins
            meta = self._read_plugin_json(plugin_dir)
            managed = meta is not None

            # Config state
            is_enabled = enabled_map.get(name, True)

            # Read SKILL.md for requirements
            requirements_list = parsed.get("requirements", []) if parsed else []

            result.append(PluginInfo(
                name=name,
                description=description,
                location=plugin_dir,
                version=meta.get("version") if meta else None,
                source=meta.get("source") if meta else None,
                installed_at=meta.get("installed_at") if meta else None,
                tier=tier,
                enabled=is_enabled,
                managed=managed,
                requirements=requirements_list,
            ))

        # Also include "missing" plugins — in config but not on disk
        for name, info in installed_map.items():
            if not any(p.name == name for p in result):
                result.append(PluginInfo(
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

        temp_dir = tempfile.mkdtemp(prefix="cody_plugin_")

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
                raise PluginError(
                    f"Failed to clone '{url}'"
                    f" (version: {version}): {result.stderr.strip()}"
                )

            return temp_dir

        except subprocess.TimeoutExpired:
            if os.path.isdir(temp_dir):
                shutil.rmtree(temp_dir, ignore_errors=True)
            raise PluginError(
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
            raise PluginError(f"Tag lookup for '{url}' timed out.")

        if result.returncode != 0:
            raise PluginError(f"Failed to list tags for '{url}': {result.stderr.strip()}")

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
            raise PluginError(
                "git is not installed. "
                "Please install git to use the plugin manager."
            )
        except subprocess.TimeoutExpired:
            raise PluginError("git check timed out.")

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
        installed into the same venv that runs Cody, since plugins are
        loaded in-process and need their dependencies on ``sys.path``.

        Raises :class:`PluginError` if installation fails.
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
            raise PluginError(
                f"Installing requirements timed out after 300 seconds: "
                f"{', '.join(requirements)}"
            )

        if result.returncode != 0:
            raise PluginError(
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
            name: my_plugin
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
    # .plugin.json management
    # ------------------------------------------------------------------

    @staticmethod
    def _write_plugin_json(
        plugin_dir: str,
        source: str,
        version: str,
        requirements: list[str] | None = None,
    ) -> None:
        """Write a .plugin.json metadata file into the plugin directory."""
        meta = {
            "source": source,
            "version": version,
            "installed_at": datetime.now(timezone.utc).isoformat(),
        }
        if requirements:
            meta["requirements"] = requirements
        path = os.path.join(plugin_dir, ".plugin.json")
        with open(path, "w") as fh:
            json.dump(meta, fh, indent=2)
            fh.write("\n")

    @staticmethod
    def _read_plugin_json(plugin_dir: str) -> dict | None:
        """Read .plugin.json from a plugin directory, or None if missing."""
        path = os.path.join(plugin_dir, ".plugin.json")
        if not os.path.isfile(path):
            return None
        try:
            with open(path) as fh:
                return json.load(fh)
        except (json.JSONDecodeError, OSError):
            return None

    # ------------------------------------------------------------------
    # Config helpers
    # ------------------------------------------------------------------

    def _config_set_installed(self, name: str, source: str, version: str) -> None:
        """Record an installed plugin in config (plugins.installed + plugins.enabled)."""
        installed = dict(self._config.get("plugins.installed", {}) or {})
        installed[name] = {
            "source": source,
            "version": version,
            "installed_at": datetime.now(timezone.utc).isoformat(),
        }
        self._config.set("plugins.installed", installed)

        # Default to enabled
        enabled = dict(self._config.get("plugins.enabled", {}) or {})
        if name not in enabled:
            enabled[name] = True
            self._config.set("plugins.enabled", enabled)

        self._config.save()

    def _config_remove_installed(self, name: str) -> None:
        """Remove an installed plugin from config."""
        installed = dict(self._config.get("plugins.installed", {}) or {})
        installed.pop(name, None)
        self._config.set("plugins.installed", installed)

        # Also remove from enabled map
        enabled = dict(self._config.get("plugins.enabled", {}) or {})
        enabled.pop(name, None)
        self._config.set("plugins.enabled", enabled)

        self._config.save()

    # ------------------------------------------------------------------
    # Path helpers
    # ------------------------------------------------------------------

    def _plugin_dir(self, name: str, *, local: bool = False) -> str:
        """Return the target directory for a plugin install."""
        if local:
            return os.path.join(self._working_dir, ".agents", "plugins", name)
        return os.path.join(self._agents_dir, "plugins", name)

    def _find_plugin_dir(self, name: str, *, local: bool = False) -> str | None:
        """Find a plugin directory by name, searching tiers in order.

        If *local* is True, only checks the project-local tier.
        Otherwise checks global then project-local.
        """
        if local:
            path = os.path.join(
                self._working_dir, ".agents", "plugins", name
            )
            return path if os.path.isdir(path) else None

        # Check global tier
        global_path = os.path.join(self._agents_dir, "plugins", name)
        if os.path.isdir(global_path):
            return global_path

        # Check project-local tier
        local_path = os.path.join(
            self._working_dir, ".agents", "plugins", name
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
        "plugins": {
            "enabled": {},
            "installed": {},
        }
    }
)