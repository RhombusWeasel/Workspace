# Step 1: Project Scaffolding

**Branch:** `step-1-scaffolding` (merged into subsequent branches)  
**Date:** 2026-04-30 (approximate)

---

## Overview

Initial project skeleton. Created the directory tree, dependency manifests,
and package-level `__init__.py` files so the project imports cleanly.

---

## Files Created

### `pyproject.toml`

```toml
[project]
name = "nu-cody"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "cryptography>=47.0.0",
    "ollama>=0.6.2",
    "textual>=8.2.5",
]

[dependency-groups]
dev = [
    "pytest>=9.0.3",
    "pytest-asyncio>=1.3.0",
]
```

Package manager: **uv**. Python >= 3.12 required.

### Directory Skeleton

```
cody/
├── main.py                  ← placeholder entry point
├── core/
│   ├── __init__.py
│   └── providers/
│       └── __init__.py
├── ui/
│   └── __init__.py
├── tools/
│   └── __init__.py
├── skills/
│   └── __init__.py
└── tests/
    └── __init__.py
```

### `conftest.py`

```python
@pytest.fixture
def sample_skill_frontmatter():
    return {
        "name": "test-skill",
        "description": "A skill used for testing",
    }
```

Shared fixture for skill system tests (Steps 7-8). Defined early so all test
modules can import it.

---

## Design Decisions

- **uv** over pip/poetry — faster, simpler lockfile, PEP 621 compliant.
- **Minimal initial deps** — cryptography (vault), ollama (provider), textual
  (TUI). Add more as needed.
- **Separate `core/`, `ui/`, `tools/`, `skills/`** directories from day one.
  Clear boundaries between systems, UI, and bundled content.
