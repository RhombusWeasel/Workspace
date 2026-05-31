"""Skill system — discovers, catalogs, and exposes SKILL.md-based skills.

Skills are discovered by scanning directory trees for ``SKILL.md`` files
with YAML frontmatter (``name`` + ``description`` required).  Three-tier
search with later-tier override (§ 2.2.C) and a manual ``scan()`` method
(no implicit re-discovery — § 6.4).
"""

from __future__ import annotations

import os
import xml.sax.saxutils as saxutils
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------


@dataclass
class Skill:
    """A single discovered skill."""

    name: str
    description: str
    location: str  # path to SKILL.md
    base_dir: str  # directory containing SKILL.md
    body: str = ""  # markdown content after frontmatter


# ---------------------------------------------------------------------------
# Frontmatter parser
# ---------------------------------------------------------------------------


def _parse_skill_md(path: str) -> dict[str, str] | None:
    """Parse a SKILL.md file, returning a dict with keys *name*, *description*,
    and *body*, or ``None`` if the file is invalid / incomplete."""

    try:
        with open(path) as fh:
            text = fh.read()
    except OSError:
        return None

    lines = text.split("\n")

    # Find the first --- delimiter line (whitespace-tolerant).
    start = -1
    for i, line in enumerate(lines):
        if line.strip() == "---":
            start = i
            break
    if start == -1:
        return None  # no opening delimiter

    # Find the next --- delimiter line.
    end = -1
    for i in range(start + 1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end == -1:
        return None  # no closing delimiter

    # Frontmatter lines between the delimiters.
    fm_lines = lines[start + 1 : end]

    # Body is everything after the closing delimiter.
    body = "\n".join(lines[end + 1 :]).strip()

    # Parse key: value lines.
    meta: dict[str, str] = {}
    for line in fm_lines:
        line = line.strip()
        if not line:
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip()

    if "name" not in meta or "description" not in meta:
        return None

    return {
        "name": meta["name"],
        "description": meta["description"],
        "body": body,
    }


# ---------------------------------------------------------------------------
# SkillManager
# ---------------------------------------------------------------------------


class SkillManager:
    """Singleton-ish registry of discovered skills.

    Call ``scan()`` to rebuild the catalog (explicit — no implicit
    re-discovery).  Query methods return the current snapshot.
    """

    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}
        # Set of *enabled* skill names (computed during scan).
        self._enabled: set[str] = set()
        # Service factories collected by bootstrap during skill loading.
        self._services: dict = {}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def scan(
        self,
        tier_paths: list[str],
        enabled: dict[str, bool] | None = None,
    ) -> None:
        """Rebuild the skill catalog from *tier_paths* (ordered from lowest
        to highest priority).

        *enabled* is a ``skill_name → bool`` map.  Skills missing from the
        map default to enabled.
        """
        discovered: dict[str, Skill] = {}

        for tier_dir in tier_paths:
            if not os.path.isdir(tier_dir):
                continue
            try:
                entries = os.listdir(tier_dir)
            except OSError:
                continue
            for entry in sorted(entries):
                skill_dir = os.path.join(tier_dir, entry)
                md_path = os.path.join(skill_dir, "SKILL.md")
                if not os.path.isfile(md_path):
                    continue

                parsed = _parse_skill_md(md_path)
                if parsed is None:
                    continue

                skill = Skill(
                    name=parsed["name"],
                    description=parsed["description"],
                    location=md_path,
                    base_dir=skill_dir,
                    body=parsed["body"],
                )
                # Later tiers simply replace same-named skills.
                discovered[skill.name] = skill

        self._skills = discovered

        # Recompute enabled set.
        self._enabled = set()
        enabled = enabled or {}
        for name in self._skills:
            if enabled.get(name, True):
                self._enabled.add(name)

    def reset(self) -> None:
        """Clear all skills, enabled state, and services (for test isolation)."""
        self._skills.clear()
        self._enabled.clear()
        self._services.clear()

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def list_skills(self) -> list[str]:
        """Return sorted list of *enabled* skill names."""
        return sorted(self._enabled)

    def get_skill(self, name: str) -> Skill | None:
        """Return a skill by name (even if disabled), or ``None``."""
        return self._skills.get(name)

    def get_skill_body(self, name: str) -> str | None:
        """Return the markdown body for *name* (even if disabled), or ``None``."""
        skill = self._skills.get(name)
        return skill.body if skill else None

    def get_skill_dirs(self) -> list[tuple[str, str]]:
        """Return ``(name, base_dir)`` pairs for enabled skills."""
        return [
            (name, self._skills[name].base_dir)
            for name in sorted(self._enabled)
        ]

    def get_skill_cmd_dirs(self) -> list[str]:
        """Return paths to ``cmd/`` directories that exist inside enabled skills."""
        result: list[str] = []
        for name in sorted(self._enabled):
            cmd_dir = os.path.join(self._skills[name].base_dir, "cmd")
            if os.path.isdir(cmd_dir):
                result.append(cmd_dir)
        return result

    def get_skill_tools_dirs(self) -> list[str]:
        """Return paths to ``tools/`` directories that exist inside enabled skills."""
        result: list[str] = []
        for name in sorted(self._enabled):
            tools_dir = os.path.join(self._skills[name].base_dir, "tools")
            if os.path.isdir(tools_dir):
                result.append(tools_dir)
        return result

    def get_skill_init_dirs(self) -> list[str]:
        """Return base directories of enabled skills that contain ``__init__.py``.

        Skills with ``__init__.py`` are loaded at bootstrap with full
        ``importlib`` treatment (``__path__``/``__package__`` handling)
        so that nested sub-imports work.  Ecosystem skills (Anthropic spec)
        do not have ``__init__.py`` — they are discovered and their body is
        available for agent activation, but no Python code runs.
        """
        result: list[str] = []
        for name in sorted(self._enabled):
            init_path = os.path.join(self._skills[name].base_dir, "__init__.py")
            if os.path.isfile(init_path):
                result.append(self._skills[name].base_dir)
        return result

    def get_skill_services(self) -> dict:
        """Return collected ``SKILL_SERVICES`` from loaded skill modules.

        Services are populated by bootstrap's ``_load_skill_init_files()``
        phase, which sets them via :meth:`set_skill_services`.  Returns an
        empty dict before bootstrap has run the loading phase.
        """
        return dict(self._services)

    def set_skill_services(self, services: dict) -> None:
        """Store service factories collected during bootstrap loading.

        Called by :meth:`bootstrap.Bootstrap._load_skill_init_files` after
        each skill's ``__init__.py`` is loaded and its ``SKILL_SERVICES``
        dict is collected.
        """
        self._services = dict(services)

    def get_skill_components_dirs(self) -> list[str]:
        """Return paths to ``components/`` directories that exist inside enabled skills.

        Components directories contain Python modules that register
        UI elements (sidebar panels, event handlers, leader chords)
        via the usual decorator pattern.  They are auto-imported by
        the bootstrap loader, exactly like ``tools/`` and ``cmd/``
        directories.
        """
        result: list[str] = []
        for name in sorted(self._enabled):
            comp_dir = os.path.join(self._skills[name].base_dir, "components")
            if os.path.isdir(comp_dir):
                result.append(comp_dir)
        return result

    # ------------------------------------------------------------------
    # Catalog XML
    # ------------------------------------------------------------------

    def get_catalog_xml(self) -> str:
        """Return an XML string listing enabled skills for agent system prompts."""
        return self.render_selected(list(self._enabled))

    def render_selected(self, skill_names: list[str]) -> str:
        """Return an XML string listing only the named skills.

        Skills that are not enabled or not found are silently skipped.
        Used by agents that specify a restricted ``skills`` list.
        """
        parts = ["<available_skills>"]
        for name in sorted(skill_names):
            if name not in self._enabled:
                continue
            skill = self._skills[name]
            parts.append("  <skill>")
            parts.append(
                f"    <name>{saxutils.escape(skill.name)}</name>"
            )
            parts.append(
                f"    <description>{saxutils.escape(skill.description)}</description>"
            )
            parts.append(
                f"    <location>{saxutils.escape(skill.location)}</location>"
            )
            parts.append("  </skill>")
        parts.append("</available_skills>")
        return "\n".join(parts) + "\n"


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

skill_manager = SkillManager()
