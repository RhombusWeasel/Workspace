"""Tests for core.paths."""

import os

from core.paths import agents_dir, cody_dir, collect_tcss, resolve


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


class TestCollectTcss:
    def test_returns_list(self, tmp_path):
        result = collect_tcss(str(tmp_path))
        assert isinstance(result, list)

    def test_empty_when_no_tcss_files(self, tmp_path, monkeypatch):
        monkeypatch.setattr("core.paths.cody_dir", lambda: str(tmp_path / "nonexistent"))
        monkeypatch.setattr("core.paths.agents_dir", lambda: str(tmp_path / "nonexistent"))
        result = collect_tcss(str(tmp_path))
        assert result == []

    def test_collects_from_cody_tier(self, tmp_path, monkeypatch):
        """Only cody tier has .tcss files."""
        cody = tmp_path / "cody"
        os.makedirs(cody / "ui" / "workspace")
        (cody / "ui" / "workspace" / "styles.tcss").write_text("Button {}")
        (cody / "ui" / "other.tcss").write_text("Label {}")

        monkeypatch.setattr("core.paths.cody_dir", lambda: str(cody))
        # Use tmp_path as wd (it has no .agents/ subdir with tcss)
        result = collect_tcss(str(tmp_path))

        # Should only find cody tier files
        assert len(result) == 2
        assert result[0] == os.path.join(str(cody), "ui", "other.tcss")
        assert result[1] == os.path.join(str(cody), "ui", "workspace", "styles.tcss")

    def test_collects_from_all_three_tiers_in_order(self, tmp_path, monkeypatch):
        """Files from all three tiers, verify they're ordered cody → agents → wd."""
        cody = tmp_path / "cody"
        agents = tmp_path / "agents"
        wd = tmp_path / "working"
        os.makedirs(cody / "ui")
        os.makedirs(agents / "ui")
        os.makedirs(wd / ".agents" / "ui")

        (cody / "ui" / "base.tcss").write_text("/* cody */")
        (agents / "ui" / "user.tcss").write_text("/* agents */")
        (wd / ".agents" / "ui" / "project.tcss").write_text("/* project */")

        monkeypatch.setattr("core.paths.cody_dir", lambda: str(cody))
        monkeypatch.setattr("core.paths.agents_dir", lambda: str(agents))

        result = collect_tcss(str(wd))

        assert len(result) == 3
        assert "cody" in result[0]
        assert "agents" in result[1]
        assert "project" in result[2]
        # Verify order: cody < agents < wd
        cody_idx = next(i for i, p in enumerate(result) if "cody" in p)
        agents_idx = next(i for i, p in enumerate(result) if "agents" in p)
        wd_idx = next(i for i, p in enumerate(result) if "working" in p)
        assert cody_idx < agents_idx < wd_idx

    def test_skips_missing_tier_directories(self, tmp_path, monkeypatch):
        """Missing tier directories are silently skipped."""
        cody = tmp_path / "cody"
        os.makedirs(cody / "ui")
        (cody / "ui" / "exists.tcss").write_text("/* */")

        monkeypatch.setattr("core.paths.cody_dir", lambda: str(cody))
        # agents_dir still points to real ~/.agents but that's ok — it may
        # or may not exist; collect_tcss handles missing dirs gracefully

        result = collect_tcss(str(tmp_path))
        assert len(result) >= 1
        assert any("exists.tcss" in p for p in result)

    def test_only_finds_tcss_extension(self, tmp_path, monkeypatch):
        """Only .tcss files are collected; .css and others are ignored."""
        cody = tmp_path / "cody"
        os.makedirs(cody / "ui")
        (cody / "ui" / "styles.tcss").write_text("Button {}")
        (cody / "ui" / "styles.css").write_text("Button {}")
        (cody / "ui" / "readme.md").write_text("# README")
        (cody / "ui" / "__init__.py").write_text("")

        monkeypatch.setattr("core.paths.cody_dir", lambda: str(cody))

        result = collect_tcss(str(tmp_path))
        assert len(result) == 1
        assert result[0].endswith(".tcss")

    def test_collects_skill_tcss(self, tmp_path, monkeypatch):
        """CSS from skills/ directories is collected alongside core UI CSS."""
        cody = tmp_path / "cody"
        os.makedirs(cody / "ui")
        os.makedirs(cody / "skills" / "chat")
        (cody / "ui" / "core.tcss").write_text("/* core */")
        (cody / "skills" / "chat" / "chat.tcss").write_text("/* chat skill */")

        monkeypatch.setattr("core.paths.cody_dir", lambda: str(cody))

        result = collect_tcss(str(tmp_path))
        assert any("core.tcss" in p for p in result)
        assert any("chat.tcss" in p for p in result)

    def test_collects_skill_tcss_from_nested_subpackages(self, tmp_path, monkeypatch):
        """CSS from skills with nested sub-packages (e.g. database) is collected."""
        cody = tmp_path / "cody"
        os.makedirs(cody / "skills" / "database" / "core" / "providers")
        (cody / "skills" / "database" / "db.tcss").write_text("/* db */")
        (cody / "skills" / "database" / "core" / "providers" / "sqlite.tcss").write_text("/* sqlite */")

        monkeypatch.setattr("core.paths.cody_dir", lambda: str(cody))

        result = collect_tcss(str(tmp_path))
        db_tcss = [p for p in result if "db.tcss" in p]
        sqlite_tcss = [p for p in result if "sqlite.tcss" in p]
        assert len(db_tcss) == 1
        assert len(sqlite_tcss) == 1