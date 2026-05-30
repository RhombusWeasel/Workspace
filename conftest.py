"""Base pytest fixtures for the Workspace project."""

import sys
import types
import pytest

# Mock the ollama library if not installed so most tests can import
# core.providers.ollama without requiring the real package.
# The actual provider tests (test_provider_ollama) require the real
# library and are skipped if it's not available.
try:
    import ollama  # noqa: F401
except ImportError:
    _mock_ollama = types.ModuleType("ollama")
    _mock_ollama.AsyncClient = type("AsyncClient", (), {})
    sys.modules["ollama"] = _mock_ollama


@pytest.fixture
def sample_skill_frontmatter():
    """A minimal valid SKILL.md frontmatter for use across test modules."""
    return {
        "name": "test-skill",
        "description": "A skill used for testing",
    }
