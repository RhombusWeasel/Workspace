"""Prompt registry — database-backed system prompt templates with {{key}} variable substitution.

Manages system prompt templates stored in the ``prompts`` table.  Templates
use ``{{key}}`` placeholders that are resolved at render time from dynamic
providers registered at bootstrap.

Nested keys are supported: ``{{skills}}`` renders the full skills catalog,
``{{skills.catalog}}`` renders only the XML catalog, ``{{skills.names}}``
renders a comma-separated list of skill names.

The ``agents`` table CRUD methods on :class:`~core.database.DatabaseManager`
are deprecated — the ``prompts`` table subsumes them.
"""

from __future__ import annotations

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
    "prompt": {
        "default_id": "default",
        "inline_suggest_id": "inline-suggest",
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
# Default prompts — seeded at first run
# ---------------------------------------------------------------------------

DEFAULT_CHAT_PROMPT = {
    "id": "default",
    "name": "Default Assistant",
    "description": "General-purpose coding assistant",
    "template": (
        "You are a helpful AI coding assistant working in {{project_name}}.\n\n"
        "Current working directory: {{working_directory}}\n"
        "Date: {{date}}\n"
        "\n"
        "{{skills}}\n"
        "\n"
        "Use the available tools when appropriate. "
        "The user can activate specific skills for detailed instructions "
        "by using the activate_skill tool.\n"
    ),
    "model": "",
    "scope": "global",
}

DEFAULT_INLINE_SUGGEST_PROMPT = {
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
    "scope": "global",
}

_DEFAULTS = [DEFAULT_CHAT_PROMPT, DEFAULT_INLINE_SUGGEST_PROMPT]


# ---------------------------------------------------------------------------
# PromptManager
# ---------------------------------------------------------------------------


class PromptManager:
    """Database-backed system prompt template registry.

    Stores templates in the ``prompts`` table and resolves ``{{key}}``
    placeholders at render time from dynamic providers.

    Dynamic providers are callables registered via :meth:`register_dynamic`
    that receive an :class:`~context.AppContext` and return a ``str`` or
    ``dict``.  Dict returns support nested key lookup (e.g.
    ``{{skills.catalog}}``).
    """

    def __init__(self, db: DatabaseManager, working_directory: str = ""):
        self._db = db
        self._wd = working_directory
        self._providers: dict[str, Callable[[Any], str | dict]] = {}
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

    def create_prompt(
        self,
        name: str,
        description: str = "",
        template: str = "",
        model: str = "",
        scope: str = "global",
        prompt_id: str | None = None,
    ) -> str:
        """Create a new prompt template.  Returns the prompt ID."""
        prompt_id = prompt_id or f"custom:{uuid.uuid4().hex[:8]}"
        now = _now()
        self._db._execute(
            "INSERT INTO prompts (id, name, description, template, model, scope, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (prompt_id, name, description, template, model, scope, now, now),
        )
        return prompt_id

    def get_prompt(self, prompt_id: str) -> dict[str, Any] | None:
        """Return a prompt dict by ID, or ``None`` if not found."""
        rows = self._db._execute(
            "SELECT id, name, description, template, model, scope, created_at, updated_at "
            "FROM prompts WHERE id = ?",
            (prompt_id,),
        )
        return dict(rows[0]) if rows else None

    def list_prompts(self, scope: str | None = None) -> list[dict[str, Any]]:
        """Return all prompts, optionally filtered by scope."""
        if scope:
            rows = self._db._execute(
                "SELECT id, name, description, template, model, scope, created_at, updated_at "
                "FROM prompts WHERE scope = ? ORDER BY name ASC",
                (scope,),
            )
        else:
            rows = self._db._execute(
                "SELECT id, name, description, template, model, scope, created_at, updated_at "
                "FROM prompts ORDER BY name ASC"
            )
        return [dict(r) for r in rows]

    def update_prompt(self, prompt_id: str, **kwargs: Any) -> None:
        """Update prompt fields.  Accepted keys: name, description, template, model, scope."""
        allowed = {"name", "description", "template", "model", "scope"}
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            return
        updates["updated_at"] = _now()
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [prompt_id]
        self._db._execute(
            f"UPDATE prompts SET {set_clause} WHERE id = ?", tuple(values)
        )

    def delete_prompt(self, prompt_id: str) -> None:
        """Delete a prompt by ID."""
        self._db._execute("DELETE FROM prompts WHERE id = ?", (prompt_id,))

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def render(
        self,
        prompt_id: str,
        ctx: AppContext,
        extra_vars: dict[str, str] | None = None,
    ) -> str:
        """Render a prompt template, resolving all ``{{key}}`` placeholders.

        Resolution order for each placeholder:
        1. *extra_vars* (caller-supplied overrides, highest priority)
        2. Dynamic providers (context-aware)
        3. Left as ``{{key}}`` if unresolved

        Raises ``ValueError`` if *prompt_id* is not found.
        """
        row = self.get_prompt(prompt_id)
        if row is None:
            raise ValueError(f"Prompt '{prompt_id}' not found")
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

    def _seed_defaults(self) -> None:
        """Insert default prompts if they don't already exist."""
        for default in _DEFAULTS:
            existing = self._db._execute(
                "SELECT 1 FROM prompts WHERE id = ?", (default["id"],)
            )
            if not existing:
                now = _now()
                self._db._execute(
                    "INSERT INTO prompts (id, name, description, template, model, scope, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        default["id"],
                        default["name"],
                        default["description"],
                        default["template"],
                        default.get("model", ""),
                        default.get("scope", "global"),
                        now,
                        now,
                    ),
                )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()