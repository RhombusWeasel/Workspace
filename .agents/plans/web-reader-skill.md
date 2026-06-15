# Plan: `web_reader` Skill

## Goal
Create a script-only bundled skill that reads a webpage URL and returns clean, extracted content (markdown or text) using `httpx` + `trafilatura`. Follows the brave_search pattern — no registered tool, invoked via `run_skill`.

## Rationale
- Agent tool set stays sparse (no new `@register_tool`)
- Progressive disclosure: agent discovers the skill via SKILL.md when needed, invokes via `run_skill`
- Studies show more available tools reduces agent performance; Anthropic skill spec encourages progressive revelation

## Skill Structure
```
skills/web_reader/
├── SKILL.md              # Manifest + agent knowledge (invocation instructions)
└── scripts/
    └── fetch.py           # Core fetch + extract logic
```

## SKILL.md Contents
- Name: `web_reader`
- Description: Reads a webpage URL and returns clean extracted content
- Requirements: `httpx`, `trafilatura`
- Invocation: `run_skill("web_reader", "scripts/fetch.py", args=["<url>", "--format", "markdown"])`
- CLI args supported: `--format` (markdown|text), `--no-links`, `--max-length` (int)

## scripts/fetch.py
- Accepts `args` list from `run_skill` (first arg = URL, rest = flags)
- Uses `httpx.get()` with redirects, 15s timeout, browser-like User-Agent
- Passes HTML to `trafilatura.extract()` with chosen format and link options
- Truncates output at `max_length` (default 50000 chars) with notice
- Lazy imports: `httpx` and `trafilatura` imported inside the function, not at module level
- Graceful error messages on missing deps, bad URLs, non-HTML, timeouts

## Parameters (via args)
| Arg | Position/Flag | Default | Description |
|-----|--------------|---------|-------------|
| URL | args[0] | (required) | URL to fetch |
| --format | flag | markdown | Output format: "markdown" or "text" |
| --no-links | flag | off | Strip hyperlinks from output |
| --max-length | flag | 50000 | Max characters before truncation |

## Output
- Clean markdown (or plain text) of the page's main content
- Boilerplate (nav, ads, footers) removed by trafilatura
- Truncation notice appended if content exceeds max_length

## Tests
- `tests/test_web_reader.py`
- Mock HTTP responses (no real network calls)
- Cases: successful extract, text format, no-links, truncation, non-HTML URL, timeout, missing deps, no URL arg

## Steps
1. Create `skills/web_reader/SKILL.md`
2. Create `skills/web_reader/scripts/fetch.py`
3. Create `tests/test_web_reader.py`
4. Run tests, verify pass
5. Update `design.md` and `tasks.md`