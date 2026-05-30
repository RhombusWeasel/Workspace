"""Base pytest fixtures for the Workspace project."""

import pytest


@pytest.fixture
def sample_skill_frontmatter():
    """A minimal valid SKILL.md frontmatter for use across test modules."""
    return {
        "name": "test-skill",
        "description": "A skill used for testing",
    }
