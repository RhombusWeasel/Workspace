"""Tests for core.paths."""

import os

from core.paths import agents_dir, cody_dir, resolve


class TestCodyDir:
    def test_returns_string(self):
        assert isinstance(cody_dir(), str)

    def test_is_absolute(self):
        assert os.path.isabs(cody_dir())

    def test_is_not_empty(self):
        assert len(cody_dir()) > 0


class TestAgentsDir:
    def test_returns_string(self):
        assert isinstance(agents_dir(), str)

    def test_is_absolute(self):
        assert os.path.isabs(agents_dir())

    def test_ends_with_dot_agents(self):
        assert agents_dir().endswith(".agents")


class TestResolve:
    def test_returns_three_paths(self):
        paths = resolve("skills", "/some/project")
        assert len(paths) == 3

    def test_all_paths_are_absolute(self):
        paths = resolve("skills", "/some/project")
        for p in paths:
            assert os.path.isabs(p), f"Expected absolute path, got: {p}"

    def test_subpath_appended_to_each_tier(self):
        paths = resolve("skills", "/tmp/work")
        assert paths[0] == os.path.join(cody_dir(), "skills")
        assert paths[1] == os.path.join(agents_dir(), "skills")
        assert paths[2] == os.path.join("/tmp/work", ".agents", "skills")

    def test_subpath_with_nested_directories(self):
        paths = resolve("providers/keys", "/home/user/proj")
        assert paths[0] == os.path.join(cody_dir(), "providers", "keys")
        assert paths[1] == os.path.join(agents_dir(), "providers", "keys")
        assert paths[2] == os.path.join("/home/user/proj", ".agents", "providers", "keys")

    def test_empty_subpath(self):
        paths = resolve("", "/tmp")
        assert paths[0] == cody_dir()
        assert paths[1] == agents_dir()
        assert paths[2] == os.path.join("/tmp", ".agents")

    def test_working_dir_trailing_slash(self):
        paths = resolve("x", "/tmp/")
        assert paths[2] == os.path.join("/tmp", ".agents", "x")
