"""Agent registry — database-backed agent definitions with ``{{key}}`` variable substitution.

Manages agent definitions stored in the ``agents`` table.  Each agent is
a system prompt template plus optional overrides for model, provider,
tool permissions, skill activation, and generation parameters.

Templates use ``{{key}}`` placeholders that are resolved at render time
from dynamic providers registered at bootstrap.  Nested keys are
supported: ``{{skills}}`` renders the full skills catalog,
``{{skills.catalog}}`` renders only the XML catalog, ``{{skills.names}}``
renders a comma-separated list of skill names.

The old ``prompts`` table (and the older deprecated ``agents`` table)
are migrated automatically on first run.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Callable

from core.database import DatabaseManager
from core.config import register_defaults

if TYPE_CHECKING:
    from context import AppContext

# ---------------------------------------------------------------------------
# Config defaults
# ---------------------------------------------------------------------------

register_defaults({
    "agent": {
        "default_id": "default",
        "inline_suggest_id": "inline-suggest",
    },
    "agents": {
        "name": "Cody",
    },
})

# ---------------------------------------------------------------------------
# Template rendering
# ---------------------------------------------------------------------------

_PLACEHOLDER = re.compile(r"\{\{(\w+(?:\.\w+)*)\}\}")
"""Matches ``{{key}}`` and ``{{key.sub}}`` placeholders in templates."""


def render_template(template: str, variables: dict[str, str]) -> str:
    """Replace ``{{key}}`` and ``{{key.sub}}`` placeholders in *template*.

    Missing keys are left unchanged.
    """

    def _replace(match: re.Match) -> str:
        key = match.group(1)
        return variables.get(key, match.group(0))

    return _PLACEHOLDER.sub(_replace, template)


# ---------------------------------------------------------------------------
# Default agents — seeded at first run
# ---------------------------------------------------------------------------

DEFAULT_CHAT_AGENT = {
    "id": "default",
    "name": "Default Assistant",
    "description": "General-purpose coding assistant",
    "template": (
        "You are {{agent_name}}, a helpful AI coding assistant working in {{project_name}}.  A Personalized Development Environment with agentic AI [You] at it's core.\n\n"
        "Current working directory: {{working_directory}}\n"
        "Date: {{date}}\n\n"
        "{{workspace_agents}}"
        "{{skills}}\n\n"
        "The users global settings are detailed below:"
        "{{global_agents}}\n\n"
        "Repo specific settings are detailed below, these settings take prescidence over all others as it involves interaction with the users codebase so must be followed."
        "{{local_agents}}\n"
    ),
    "model": "",
    "provider": "",
    "scope": "global",
    "tools": "",
    "skills": "",
    "temperature": "",
    "max_tool_iterations": "",
}

DEFAULT_INLINE_SUGGEST_AGENT = {
    "id": "inline-suggest",
    "name": "Inline Suggest",
    "description": "Fast code completion for inline suggestions",
    "template": (
        "You are a code completion assistant. Complete the code at the <CURSOR> "
        "marker.\n\n"
        "Output ONLY the raw completion text starting from the cursor position. "
        "This may span multiple lines if a natural completion requires it. "
        "Keep completions brief — typically 1–3 lines, maximum 10.\n\n"
        "Do not include:\n"
        "- Any text before the cursor\n"
        "- Explanations, comments, or reasoning\n"
        "- Markdown code fences or formatting\n\n"
        "If you cannot determine a meaningful completion, output nothing."
    ),
    "model": "",
    "provider": "",
    "scope": "global",
    "tools": "",
    "skills": "",
    "temperature": "",
    "max_tool_iterations": "",
}

_DEFAULTS = [DEFAULT_CHAT_AGENT, DEFAULT_INLINE_SUGGEST_AGENT]


# ---------------------------------------------------------------------------
# AgentManager
# ---------------------------------------------------------------------------


class AgentManager:
    """Database-backed agent definition registry.

    Stores agent definitions in the ``agents`` table and resolves
    ``{{key}}`` placeholders at render time from dynamic providers.

    An agent definition includes:
    - A system prompt **template** with ``{{key}}`` placeholders
    - Optional **model** override (e.g. ``"llama3"``)
    - Optional **provider** override (named instance from the provider registry)
    - Optional **tools** filter (JSON list of tool tags or names)
    - Optional **skills** filter (JSON list of skill names to activate)
    - Optional **temperature** and **max_tool_iterations** overrides

    Dynamic providers are callables registered via :meth:`register_dynamic`
    that receive an :class:`~context.AppContext` and return a ``str`` or
    ``dict``.  Dict returns support nested key lookup (e.g.
    ``{{skills.catalog}}``).
    """

    def __init__(self, db: DatabaseManager, working_directory: str = ""):
        self._db = db
        self._wd = working_directory
        self._providers: dict[str, Callable[[Any], str | dict]] = {}
        self._migrate_legacy_tables()
        self._seed_defaults()

    # ------------------------------------------------------------------
    # Dynamic provider registration
    # ------------------------------------------------------------------

    def register_dynamic(self, key: str, provider: Callable[[Any], str | dict]) -> None:
        """Register a dynamic variable provider for *key* (or key prefix).

        The provider receives an :class:`~context.AppContext` and returns
        either a ``str`` (for simple values) or a ``dict`` (for nested
        keys).
        """
        self._providers[key] = provider

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def create_agent(
        self,
        name: str,
        description: str = "",
        template: str = "",
        model: str = "",
        provider: str = "",
        scope: str = "global",
        tools: str = "",
        skills: str = "",
        temperature: str = "",
        max_tool_iterations: str = "",
        agent_id: str | None = None,
    ) -> str:
        """Create a new agent definition.  Returns the agent ID."""
        agent_id = agent_id or f"custom:{uuid.uuid4().hex[:8]}"
        now = _now()
        self._db._execute(
            "INSERT INTO agents "
            "(id, name, description, template, model, provider, scope, "
            "tools, skills, temperature, max_tool_iterations, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                agent_id, name, description, template, model, provider, scope,
                tools, skills, temperature, max_tool_iterations, now, now,
            ),
        )
        return agent_id

    def get_agent(self, agent_id: str) -> dict[str, Any] | None:
        """Return an agent dict by ID, or ``None`` if not found."""
        rows = self._db._execute(
            "SELECT id, name, description, template, model, provider, scope, "
            "tools, skills, temperature, max_tool_iterations, created_at, updated_at "
            "FROM agents WHERE id = ?",
            (agent_id,),
        )
        return dict(rows[0]) if rows else None

    def list_agents(self, scope: str | None = None) -> list[dict[str, Any]]:
        """Return all agents, optionally filtered by scope."""
        if scope:
            rows = self._db._execute(
                "SELECT id, name, description, template, model, provider, scope, "
                "tools, skills, temperature, max_tool_iterations, created_at, updated_at "
                "FROM agents WHERE scope = ? ORDER BY name ASC",
                (scope,),
            )
        else:
            rows = self._db._execute(
                "SELECT id, name, description, template, model, provider, scope, "
                "tools, skills, temperature, max_tool_iterations, created_at, updated_at "
                "FROM agents ORDER BY name ASC"
            )
        return [dict(r) for r in rows]

    def update_agent(self, agent_id: str, **kwargs: Any) -> None:
        """Update agent fields.

        Accepted keys: name, description, template, model, provider,
        scope, tools, skills, temperature, max_tool_iterations.
        """
        allowed = {
            "name", "description", "template", "model", "provider", "scope",
            "tools", "skills", "temperature", "max_tool_iterations",
        }
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            return
        updates["updated_at"] = _now()
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [agent_id]
        self._db._execute(
            f"UPDATE agents SET {set_clause} WHERE id = ?", tuple(values)
        )

    def delete_agent(self, agent_id: str) -> None:
        """Delete an agent by ID."""
        self._db._execute("DELETE FROM agents WHERE id = ?", (agent_id,))

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def render(
        self,
        agent_id: str,
        ctx: AppContext,
        extra_vars: dict[str, str] | None = None,
    ) -> str:
        """Render an agent's system prompt template, resolving all ``{{key}}`` placeholders.

        Resolution order for each placeholder:
        1. *extra_vars* (caller-supplied overrides, highest priority)
        2. Dynamic providers (context-aware)
        3. Left as ``{{key}}`` if unresolved

        Raises ``ValueError`` if *agent_id* is not found.
        """
        row = self.get_agent(agent_id)
        if row is None:
            raise ValueError(f"Agent '{agent_id}' not found")
        template = row["template"]
        overrides = extra_vars or {}

        def _replace(match: re.Match) -> str:
            key = match.group(1)
            # 1. Caller-supplied overrides (highest priority)
            if key in overrides:
                return overrides[key]
            # 2. Dynamic providers
            resolved = self._resolve_variable(key, ctx)
            if resolved is not None:
                return resolved
            # 3. Leave unchanged
            return match.group(0)

        return _PLACEHOLDER.sub(_replace, template)

    # ------------------------------------------------------------------
    # Resolved agent config helpers
    # ------------------------------------------------------------------

    def resolve_model(self, agent_def: dict[str, Any], ctx: AppContext) -> str:
        """Return the effective model for an agent definition.

        Resolution order:
        1. Agent's ``model`` field (if non-empty)
        2. The active provider's model from ``providers.<session.provider>.model``
        3. Empty string (provider default)
        """
        if agent_def.get("model"):
            return agent_def["model"]
        if ctx and ctx.config:
            # Look up the model from the active provider definition
            provider_name = ctx.config.get("session.provider", "ollama")
            return ctx.config.get(f"providers.{provider_name}.model", "")
        return ""

    def resolve_provider_name(self, agent_def: dict[str, Any], ctx: AppContext) -> str:
        """Return the effective provider instance name for an agent.

        Resolution order:
        1. Agent's ``provider`` field (if non-empty)
        2. ``session.provider`` from config
        3. ``"ollama"`` (fallback)
        """
        if agent_def.get("provider"):
            return agent_def["provider"]
        if ctx and ctx.config:
            return ctx.config.get("session.provider", "ollama")
        return "ollama"

    def resolve_tools(self, agent_def: dict[str, Any]) -> list[str] | None:
        """Return the tool filter for an agent, or ``None`` for all tools.

        Parses the agent's ``tools`` JSON field.  Returns ``None`` if
        the field is empty or invalid JSON — meaning "use all tools".
        """
        raw = agent_def.get("tools", "")
        if not raw or not raw.strip():
            return None
        try:
            result = json.loads(raw)
            if isinstance(result, list) and result:
                return result
        except (json.JSONDecodeError, TypeError):
            pass
        return None

    def resolve_skills(self, agent_def: dict[str, Any]) -> list[str] | None:
        """Return the skill filter for an agent, or ``None`` for all skills.

        Parses the agent's ``skills`` JSON field.  Returns ``None`` if
        the field is empty or invalid JSON — meaning "include all skills
        in the template".
        """
        raw = agent_def.get("skills", "")
        if not raw or not raw.strip():
            return None
        try:
            result = json.loads(raw)
            if isinstance(result, list) and result:
                return result
        except (json.JSONDecodeError, TypeError):
            pass
        return None

    def resolve_temperature(self, agent_def: dict[str, Any]) -> float | None:
        """Return the temperature override for an agent, or ``None``."""
        raw = agent_def.get("temperature", "")
        if not raw or not str(raw).strip():
            return None
        try:
            return float(raw)
        except (ValueError, TypeError):
            return None

    def resolve_max_tool_iterations(self, agent_def: dict[str, Any]) -> int | None:
        """Return the max_tool_iterations override, or ``None`` for the default."""
        raw = agent_def.get("max_tool_iterations", "")
        if not raw or not str(raw).strip():
            return None
        try:
            val = int(raw)
            return val if val > 0 else None
        except (ValueError, TypeError):
            return None

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _resolve_variable(self, key: str, ctx: AppContext) -> str | None:
        """Resolve a placeholder key against registered providers.

        Supports both simple keys (``date``) and dotted keys
        (``skills.catalog``).  For dotted keys, the longest matching
        prefix is found in providers, and the remaining path segments
        are walked through the returned dict.
        """
        # Exact match first
        if key in self._providers:
            result = self._providers[key](ctx)
            if isinstance(result, dict):
                return str(result.get("__default__", result))
            return str(result) if result is not None else None

        # Dotted key: walk providers by prefix
        # e.g. "skills.catalog" → find provider "skills", call it, walk dict
        parts = key.split(".")
        for i in range(len(parts), 0, -1):
            prefix = ".".join(parts[:i])
            if prefix in self._providers:
                result = self._providers[prefix](ctx)
                if isinstance(result, dict):
                    return self._walk_dict(result, parts[i:])
                return str(result) if result is not None else None

        return None

    @staticmethod
    def _walk_dict(d: dict, path: list[str]) -> str | None:
        """Walk a nested dict by path segments.

        Falls back to ``__default__`` if a path segment is not found.
        """
        current = d
        for segment in path:
            if isinstance(current, dict) and segment in current:
                current = current[segment]
            elif isinstance(current, dict) and "__default__" in current:
                return str(current["__default__"])
            else:
                return None
        if isinstance(current, dict) and "__default__" in current:
            return str(current["__default__"])
        return str(current) if current is not None else None

    def _migrate_legacy_tables(self) -> None:
        """Migrate data from legacy ``prompts`` and ``agents_legacy`` tables.

        On upgrade from the old schema:

        1. If ``prompts`` table exists, its rows are copied into the new
           ``agents`` table with default values for the new columns.
        2. If ``agents_legacy`` table exists (renamed from old ``agents``),
           its rows are copied similarly (``system_prompt`` → ``template``).
        3. Migrated tables are dropped after data is copied.

        The new ``agents`` table replaces both legacy tables.
        """
        # --- Migrate from `prompts` table ---
        try:
            old_prompts = self._db._execute(
                "SELECT id, name, description, template, model, scope, created_at, updated_at "
                "FROM prompts"
            )
        except Exception:
            old_prompts = []

        if old_prompts:
            for row in old_prompts:
                # Skip if already migrated (id exists in new agents table).
                existing = self._db._execute(
                    "SELECT 1 FROM agents WHERE id = ?", (row[0],)
                )
                if existing:
                    continue
                now = _now()
                self._db._execute(
                    "INSERT INTO agents "
                    "(id, name, description, template, model, provider, scope, "
                    "tools, skills, temperature, max_tool_iterations, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        row[0], row[1], row[2], row[3], row[4], "", row[5],
                        "", "", "", "", now, now,
                    ),
                )
            # Drop the old prompts table now that data is migrated.
            try:
                self._db._execute("DROP TABLE IF EXISTS prompts")
            except Exception:
                pass

        # --- Migrate from `agents_legacy` table ---
        try:
            old_agents = self._db._execute(
                "SELECT id, name, description, system_prompt, model, created_at "
                "FROM agents_legacy"
            )
        except Exception:
            old_agents = []

        if old_agents:
            for row in old_agents:
                # Skip if already migrated.
                existing = self._db._execute(
                    "SELECT 1 FROM agents WHERE id = ?", (row[0],)
                )
                if existing:
                    continue
                now = _now()
                # system_prompt → template, add defaults for new columns.
                self._db._execute(
                    "INSERT INTO agents "
                    "(id, name, description, template, model, provider, scope, "
                    "tools, skills, temperature, max_tool_iterations, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        row[0], row[1], row[2], row[3], row[4], "", "global",
                        "", "", "", "", now, now,
                    ),
                )
            # Drop the legacy agents table.
            try:
                self._db._execute("DROP TABLE IF EXISTS agents_legacy")
            except Exception:
                pass

    def _seed_defaults(self) -> None:
        """Insert default agent definitions if they don't already exist."""
        for default in _DEFAULTS:
            existing = self._db._execute(
                "SELECT 1 FROM agents WHERE id = ?", (default["id"],)
            )
            if not existing:
                now = _now()
                self._db._execute(
                    "INSERT INTO agents "
                    "(id, name, description, template, model, provider, scope, "
                    "tools, skills, temperature, max_tool_iterations, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        default["id"],
                        default["name"],
                        default["description"],
                        default["template"],
                        default.get("model", ""),
                        default.get("provider", ""),
                        default.get("scope", "global"),
                        default.get("tools", ""),
                        default.get("skills", ""),
                        default.get("temperature", ""),
                        default.get("max_tool_iterations", ""),
                        now,
                        now,
                    ),
                )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()