"""Agents skill — database-backed agent definition management.

Provides a sidebar panel for viewing, creating, editing, and deleting
AI agent definitions with {{key}} variable substitution, per-agent
model/provider overrides, tool restrictions, and skill filters.

Component modules (sidebar panels, event handlers) are auto-imported
by bootstrap's ``_load_skill_components()`` phase — they register
themselves via decorators at import time.
"""