---
name: brave_search
description: Web search via the Brave Search API — returns concise, structured results for research and fact-checking
---

# Brave Search

Search the web using the [Brave Search API](https://brave.com/search/api/).

## Setup

1. Obtain a Brave Search API key from <https://api.search.brave.com/>.
2. Store it in the vault as a credential named `brave_search`:
   - **Username**: any label (e.g. `default`)
   - **Password**: your Brave Search API key

The script runs in-process and accesses the vault directly via the
`context` global (provided by `run_skill`).  No environment variables
or key files are needed.

## Usage

```json
{
  "skill_name": "brave_search",
  "script": "scripts/search.py",
  "args": ["your search query here"]
}
```

### Options

| Flag          | Description                            | Default |
|---------------|----------------------------------------|---------|
| `--count N`   | Maximum number of results to return   | 10      |
| `--country C` | Country code for results (e.g. `us`)   | (none)  |

### Examples

```
# Basic search
run_skill(skill_name="brave_search", script="scripts/search.py", args=["Python async tutorial"])

# Fewer results
run_skill(skill_name="brave_search", script="scripts/search.py", args=["--count", "3", "Rust ownership"])

# News search (just add "news" to your query)
run_skill(skill_name="brave_search", script="scripts/search.py", args=["AI regulation news"])

# Country-specific results
run_skill(skill_name="brave_search", script="scripts/search.py", args=["--country", "uk", "BBC programming"])
```

## Output format

Results are returned as plain text, one result per block:

```
1. Title of the page
   URL: https://example.com/page
   A short snippet summarizing the page content.

2. Title of another page
   URL: https://example.com/other
   Another snippet with relevant context.
```

## Requirements

- A Brave Search API key stored in the vault as credential `brave_search`
- Network access to `api.search.brave.com`