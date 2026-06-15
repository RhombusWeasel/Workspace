---
name: web_reader
description: Read a webpage URL and return clean extracted content — ideal for following up on search results or researching a specific page
---

# Web Reader

Read the main content of a webpage, stripping away boilerplate (navigation,
ads, footers, sidebars). Powered by [trafilatura](https://trafilatura.readthedocs.io/)
for high-quality article extraction.

Use this skill when you need to **read the actual content** of a webpage — for
example, following up on a URL from `brave_search` results, or when the user
provides a specific link to read.

## Usage

```json
{
  "skill_name": "web_reader",
  "script": "scripts/fetch.py",
  "args": ["https://example.com/article"]
}
```

### Options

| Flag            | Description                              | Default   |
|-----------------|------------------------------------------|-----------|
| `--format`      | Output format: `markdown` or `text`     | markdown  |
| `--no-links`    | Strip hyperlinks from output             | off       |
| `--max-length`  | Max characters before truncation         | 50000     |

### Examples

```
# Read an article as markdown
run_skill(skill_name="web_reader", script="scripts/fetch.py", args=["https://example.com/article"])

# Read as plain text
run_skill(skill_name="web_reader", script="scripts/fetch.py", args=["--format", "text", "https://example.com/article"])

# Read without links and limit length
run_skill(skill_name="web_reader", script="scripts/fetch.py", args=["--no-links", "--max-length", "10000", "https://example.com/article"])
```

## Output

Clean markdown (or plain text) of the page's main content. If the content
exceeds `--max-length`, it is truncated with a notice appended:

```
[Truncated at 50000 chars — original length: 87234]
```

## Requirements

- `httpx` — HTTP client
- `trafilatura` — content extraction

Install with:

```
pip install httpx trafilatura
```

## Limitations

- Only works on publicly accessible URLs (no auth walls, paywalls, or CAPTCHAs)
- Best on article/blog-style pages; forums and highly dynamic pages may extract poorly
- JavaScript-rendered content will not be captured (server-side HTML only)