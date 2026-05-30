---
name: prompts
description: Prompt management — view, create, edit, and delete system prompt templates
---

# Prompts Skill

Manages system prompt templates stored in the database.  Each prompt
is a `{{key}}` template that gets resolved at render time from dynamic
providers (working directory, date, skill catalog, etc).

## When to Activate

Activate this skill when the user asks about:
- Creating or editing prompt templates
- Changing the default chat agent behaviour
- Switching between different agent personas
- Understanding what `{{key}}` variables are available

## Available Variables

| Key | Description | Dynamic? |
|---|---|---|
| `{{working_directory}}` | Current project directory | Yes |
| `{{project_name}}` | Basename of the working directory | Yes |
| `{{date}}` | Current date (YYYY-MM-DD) | Yes |
| `{{model}}` | Configured model name | Yes |
| `{{skills}}` | Full skills catalog XML | Yes |
| `{{skills.catalog}}` | Same as `{{skills}}` | Yes |
| `{{skills.names}}` | Comma-separated skill names | Yes |

## Prompt IDs

- `default` — the main chat assistant prompt
- `inline-suggest` — the code completion prompt (used by inline suggestions)
- `custom:*` — user-created prompts (auto-generated prefix)

## Configuration

| Key | Description |
|---|---|
| `prompt.default_id` | Which prompt ID to use for the chat agent (default: `"default"`) |
| `prompt.inline_suggest_id` | Which prompt ID to use for inline suggestions (default: `"inline-suggest"`) |