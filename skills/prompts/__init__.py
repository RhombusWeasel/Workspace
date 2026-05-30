"""Prompts skill — database-backed prompt template management.

Provides a sidebar panel for viewing, creating, editing, and deleting
system prompt templates with {{key}} variable substitution.

Component modules (sidebar panels, event handlers) are auto-imported
by bootstrap's ``_load_skill_components()`` phase — they register
themselves via decorators at import time.
"""