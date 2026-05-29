"""Tests for the skill system (core/skills.py)."""

import pytest

from core.skills import SkillManager


# ---------------------------------------------------------------------------
# Fixture helpers — build temp directory trees with SKILL.md files
# ---------------------------------------------------------------------------

def _write_skill_md(path, name, description, body="", extra_frontmatter=None):
    """Write a SKILL.md file with YAML frontmatter."""
    lines = ["---", f"name: {name}", f"description: {description}"]
    if extra_frontmatter:
        for k, v in extra_frontmatter.items():
            lines.append(f"{k}: {v}")
    lines.append("---")
    if body:
        lines.append("")
        lines.append(body)
    path.write_text("\n".join(lines))


# ---------------------------------------------------------------------------
# Frontmatter parsing
# ---------------------------------------------------------------------------

class TestFrontmatterParsing:
    def test_parses_name_and_description(self, tmp_path):
        """Basic SKILL.md with only name and description."""
        skill_dir = tmp_path / "myskill"
        skill_dir.mkdir()
        _write_skill_md(skill_dir / "SKILL.md", "myskill", "A test skill")

        mgr = SkillManager()
        mgr.scan([str(tmp_path)])
        skill = mgr.get_skill("myskill")
        assert skill is not None
        assert skill.name == "myskill"
        assert skill.description == "A test skill"

    def test_body_after_frontmatter(self, tmp_path):
        """Content after the closing --- is captured as the body."""
        skill_dir = tmp_path / "myskill"
        skill_dir.mkdir()
        body = "# Heading\n\nSome markdown content."
        _write_skill_md(skill_dir / "SKILL.md", "myskill", "Test", body=body)

        mgr = SkillManager()
        mgr.scan([str(tmp_path)])
        skill = mgr.get_skill("myskill")
        assert skill.body == body

    def test_empty_body(self, tmp_path):
        """No content after frontmatter means empty body."""
        skill_dir = tmp_path / "myskill"
        skill_dir.mkdir()
        _write_skill_md(skill_dir / "SKILL.md", "myskill", "Test", body="")

        mgr = SkillManager()
        mgr.scan([str(tmp_path)])
        assert mgr.get_skill("myskill").body == ""

    def test_extra_frontmatter_fields_ignored(self, tmp_path):
        """Unknown frontmatter keys are silently ignored."""
        skill_dir = tmp_path / "myskill"
        skill_dir.mkdir()
        _write_skill_md(
            skill_dir / "SKILL.md",
            "myskill",
            "Test",
            extra_frontmatter={"version": "1.0", "author": "me"},
        )

        mgr = SkillManager()
        mgr.scan([str(tmp_path)])
        skill = mgr.get_skill("myskill")
        assert skill.name == "myskill"

    def test_missing_name_skipped(self, tmp_path):
        """SKILL.md without a 'name' field is silently skipped."""
        skill_dir = tmp_path / "noskill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\ndescription: No name here\n---\n"
        )

        mgr = SkillManager()
        mgr.scan([str(skill_dir)])
        assert mgr.list_skills() == []

    def test_missing_description_skipped(self, tmp_path):
        """SKILL.md without a 'description' field is silently skipped."""
        skill_dir = tmp_path / "noskill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: nodesc\n---\n"
        )

        mgr = SkillManager()
        mgr.scan([str(skill_dir)])
        assert mgr.list_skills() == []

    def test_missing_both_skipped(self, tmp_path):
        """SKILL.md with neither name nor description is skipped."""
        skill_dir = tmp_path / "noskill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            '---\nversion: "1"\n---\n'
        )

        mgr = SkillManager()
        mgr.scan([str(skill_dir)])
        assert mgr.list_skills() == []

    def test_no_frontmatter_skipped(self, tmp_path):
        """File without --- delimiters is silently skipped."""
        skill_dir = tmp_path / "noskill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("Just some markdown, no frontmatter.")

        mgr = SkillManager()
        mgr.scan([str(skill_dir)])
        assert mgr.list_skills() == []

    def test_unclosed_frontmatter_skipped(self, tmp_path):
        """Frontmatter with opening --- but no closing --- is skipped."""
        skill_dir = tmp_path / "noskill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: broken\ndescription: No closing delimiter\n"
        )

        mgr = SkillManager()
        mgr.scan([str(skill_dir)])
        assert mgr.list_skills() == []

    def test_frontmatter_without_opening_delimiter_skipped(self, tmp_path):
        """File with closing --- but no opening --- is skipped."""
        skill_dir = tmp_path / "noskill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "name: bad\ndescription: Bad\n---\n"
        )

        mgr = SkillManager()
        mgr.scan([str(skill_dir)])
        assert mgr.list_skills() == []

    def test_markdown_content_in_frontmatter_is_preserved(self, tmp_path):
        """Frontmatter values may contain colons (e.g., markdown). Value is everything after ': '."""
        skill_dir = tmp_path / "myskill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\n"
            "name: myskill\n"
            "description: A skill with: colons and stuff\n"
            "---\n"
        )

        mgr = SkillManager()
        mgr.scan([str(tmp_path)])
        skill = mgr.get_skill("myskill")
        assert skill.description == "A skill with: colons and stuff"

    def test_whitespace_around_frontmatter_is_flexible(self, tmp_path):
        """Leading/trailing whitespace around frontmatter delimiters is handled."""
        skill_dir = tmp_path / "myskill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "  ---  \n"
            "  name: myskill  \n"
            "  description: Test  \n"
            "  ---  \n"
        )

        mgr = SkillManager()
        mgr.scan([str(tmp_path)])
        skill = mgr.get_skill("myskill")
        assert skill.name == "myskill"
        assert skill.description == "Test"

    def test_multiple_frontmatter_blocks_uses_first(self, tmp_path):
        """Only the first --- delimited block is parsed as frontmatter."""
        skill_dir = tmp_path / "myskill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\n"
            "name: myskill\n"
            "description: First\n"
            "---\n"
            "\n"
            "Body content.\n"
            "\n"
            "---\n"
            "name: ignored\n"
            "description: This should be part of body\n"
            "---\n"
        )

        mgr = SkillManager()
        mgr.scan([str(tmp_path)])
        skill = mgr.get_skill("myskill")
        assert skill.name == "myskill"
        assert skill.description == "First"
        # Second --- block should be in the body
        assert "ignored" in skill.body


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

class TestDiscovery:
    def test_discovers_skill_from_directory(self, tmp_path):
        """A directory containing SKILL.md produces one skill."""
        skill_dir = tmp_path / "myskill"
        skill_dir.mkdir()
        _write_skill_md(skill_dir / "SKILL.md", "myskill", "A skill")

        mgr = SkillManager()
        mgr.scan([str(tmp_path)])
        assert mgr.list_skills() == ["myskill"]

    def test_discovers_multiple_skills(self, tmp_path):
        """Multiple skill directories in a tier each produce a skill."""
        for name in ["alpha", "beta", "gamma"]:
            d = tmp_path / name
            d.mkdir()
            _write_skill_md(d / "SKILL.md", name, f"Skill {name}")

        mgr = SkillManager()
        mgr.scan([str(tmp_path)])
        assert sorted(mgr.list_skills()) == ["alpha", "beta", "gamma"]

    def test_ignores_files_without_skill_md(self, tmp_path):
        """Directories without SKILL.md are ignored."""
        (tmp_path / "not_a_skill").mkdir()
        (tmp_path / "not_a_skill" / "readme.md").write_text("hello")

        mgr = SkillManager()
        mgr.scan([str(tmp_path)])
        assert mgr.list_skills() == []

    def test_nonexistent_directory_handled_gracefully(self, tmp_path):
        """Scanning a tier that doesn't exist does not raise."""
        mgr = SkillManager()
        mgr.scan(["/tmp/definitely_does_not_exist_42xyz"])
        assert mgr.list_skills() == []

    def test_empty_directory_handled_gracefully(self, tmp_path):
        """An empty tier directory results in no skills."""
        mgr = SkillManager()
        mgr.scan([str(tmp_path)])
        assert mgr.list_skills() == []

    def test_skill_location_points_to_skill_md(self, tmp_path):
        """The location field is the full path to SKILL.md."""
        skill_dir = tmp_path / "myskill"
        skill_dir.mkdir()
        _write_skill_md(skill_dir / "SKILL.md", "myskill", "Test")

        mgr = SkillManager()
        mgr.scan([str(tmp_path)])
        skill = mgr.get_skill("myskill")
        assert skill.location == str(skill_dir / "SKILL.md")

    def test_base_dir_is_skill_directory(self, tmp_path):
        """base_dir is the directory containing SKILL.md."""
        skill_dir = tmp_path / "myskill"
        skill_dir.mkdir()
        _write_skill_md(skill_dir / "SKILL.md", "myskill", "Test")

        mgr = SkillManager()
        mgr.scan([str(tmp_path)])
        skill = mgr.get_skill("myskill")
        assert skill.base_dir == str(skill_dir)

    def test_nested_skill_directories(self, tmp_path):
        """Skills one level deep are discovered; deeper nesting is not recursed."""
        skill_dir = tmp_path / "myskill"
        skill_dir.mkdir()
        _write_skill_md(skill_dir / "SKILL.md", "myskill", "Test")

        # Nested directory inside skill — should NOT be discovered as separate skill
        nested = skill_dir / "subskill"
        nested.mkdir()
        _write_skill_md(nested / "SKILL.md", "subskill", "Nested")

        mgr = SkillManager()
        mgr.scan([str(tmp_path)])
        assert mgr.list_skills() == ["myskill"]


# ---------------------------------------------------------------------------
# 3-tier override
# ---------------------------------------------------------------------------

class TestTierOverride:
    def test_later_tier_overrides_earlier(self, tmp_path):
        """Same-named skill in a later tier replaces the earlier one."""
        tier1 = tmp_path / "tier1"
        tier2 = tmp_path / "tier2"
        (tier1 / "myskill").mkdir(parents=True)
        (tier2 / "myskill").mkdir(parents=True)
        _write_skill_md(tier1 / "myskill" / "SKILL.md", "myskill", "Bundled")
        _write_skill_md(tier2 / "myskill" / "SKILL.md", "myskill", "User override")

        mgr = SkillManager()
        mgr.scan([str(tier1), str(tier2)])
        assert mgr.get_skill("myskill").description == "User override"
        assert mgr.get_skill("myskill").location == str(
            tier2 / "myskill" / "SKILL.md"
        )

    def test_three_tier_override(self, tmp_path):
        """Third tier overrides second, which overrides first."""
        t1, t2, t3 = tmp_path / "t1", tmp_path / "t2", tmp_path / "t3"
        for t, desc in [(t1, "bundled"), (t2, "user"), (t3, "project")]:
            (t / "myskill").mkdir(parents=True)
            _write_skill_md(t / "myskill" / "SKILL.md", "myskill", desc)

        mgr = SkillManager()
        mgr.scan([str(t1), str(t2), str(t3)])
        assert mgr.get_skill("myskill").description == "project"

    def test_unique_skills_accumulate_across_tiers(self, tmp_path):
        """Skills unique to each tier all appear in results."""
        t1, t2 = tmp_path / "t1", tmp_path / "t2"
        (t1 / "alpha").mkdir(parents=True)
        (t2 / "beta").mkdir(parents=True)
        _write_skill_md(t1 / "alpha" / "SKILL.md", "alpha", "From t1")
        _write_skill_md(t2 / "beta" / "SKILL.md", "beta", "From t2")

        mgr = SkillManager()
        mgr.scan([str(t1), str(t2)])
        assert sorted(mgr.list_skills()) == ["alpha", "beta"]


# ---------------------------------------------------------------------------
# Enable / disable
# ---------------------------------------------------------------------------

class TestEnableDisable:
    def test_disabled_skill_excluded_from_list(self, tmp_path):
        """Disabled skills don't appear in list_skills()."""
        skill_dir = tmp_path / "myskill"
        skill_dir.mkdir()
        _write_skill_md(skill_dir / "SKILL.md", "myskill", "Test")

        mgr = SkillManager()
        mgr.scan([str(tmp_path)], enabled={"myskill": False})
        assert mgr.list_skills() == []

    def test_disabled_skill_not_in_catalog(self, tmp_path):
        """Disabled skills don't appear in XML catalog."""
        skill_dir = tmp_path / "myskill"
        skill_dir.mkdir()
        _write_skill_md(skill_dir / "SKILL.md", "myskill", "Test")

        mgr = SkillManager()
        mgr.scan([str(tmp_path)], enabled={"myskill": False})
        assert "myskill" not in mgr.get_catalog_xml()

    def test_enabled_skill_appears(self, tmp_path):
        """Explicitly enabled skills DO appear."""
        skill_dir = tmp_path / "myskill"
        skill_dir.mkdir()
        _write_skill_md(skill_dir / "SKILL.md", "myskill", "Test")

        mgr = SkillManager()
        mgr.scan([str(tmp_path)], enabled={"myskill": True})
        assert "myskill" in mgr.list_skills()

    def test_skill_not_in_enabled_dict_defaults_to_enabled(self, tmp_path):
        """Skills absent from the enabled dict are enabled by default."""
        skill_dir = tmp_path / "myskill"
        skill_dir.mkdir()
        _write_skill_md(skill_dir / "SKILL.md", "myskill", "Test")

        mgr = SkillManager()
        mgr.scan([str(tmp_path)], enabled={"other_skill": False})
        assert mgr.list_skills() == ["myskill"]

    def test_empty_enabled_dict_allows_all(self, tmp_path):
        """Passing None or empty dict means all skills are enabled."""
        skill_dir = tmp_path / "myskill"
        skill_dir.mkdir()
        _write_skill_md(skill_dir / "SKILL.md", "myskill", "Test")

        mgr = SkillManager()
        mgr.scan([str(tmp_path)], enabled=None)
        assert mgr.list_skills() == ["myskill"]

        mgr.reset()
        mgr.scan([str(tmp_path)], enabled={})
        assert mgr.list_skills() == ["myskill"]

    def test_disabled_skill_still_accessible_by_get_skill(self, tmp_path):
        """get_skill() returns disabled skills; only list/catalog excludes them."""
        skill_dir = tmp_path / "myskill"
        skill_dir.mkdir()
        _write_skill_md(skill_dir / "SKILL.md", "myskill", "Test")

        mgr = SkillManager()
        mgr.scan([str(tmp_path)], enabled={"myskill": False})
        assert mgr.get_skill("myskill") is not None
        assert mgr.get_skill("myskill").description == "Test"


# ---------------------------------------------------------------------------
# XML catalog
# ---------------------------------------------------------------------------

class TestCatalogXml:
    def test_empty_catalog(self):
        """No skills means an empty root element."""
        mgr = SkillManager()
        mgr.scan([])
        xml = mgr.get_catalog_xml()
        assert "<available_skills" in xml
        assert "</available_skills>" in xml

    def test_single_skill_in_catalog(self, tmp_path):
        """A single skill appears in the XML."""
        skill_dir = tmp_path / "myskill"
        skill_dir.mkdir()
        _write_skill_md(skill_dir / "SKILL.md", "myskill", "A test skill")

        mgr = SkillManager()
        mgr.scan([str(tmp_path)])
        xml = mgr.get_catalog_xml()
        assert "<name>myskill</name>" in xml
        assert "<description>A test skill</description>" in xml
        assert "<location>" in xml

    def test_multiple_skills_in_catalog(self, tmp_path):
        """All enabled skills appear in the XML."""
        for name in ["alpha", "beta"]:
            d = tmp_path / name
            d.mkdir()
            _write_skill_md(d / "SKILL.md", name, f"Skill {name}")

        mgr = SkillManager()
        mgr.scan([str(tmp_path)])
        xml = mgr.get_catalog_xml()
        assert "<name>alpha</name>" in xml
        assert "<name>beta</name>" in xml

    def test_catalog_excludes_disabled(self, tmp_path):
        """Disabled skills don't appear in the XML."""
        (tmp_path / "alpha").mkdir()
        (tmp_path / "beta").mkdir()
        _write_skill_md(tmp_path / "alpha" / "SKILL.md", "alpha", "Alpha")
        _write_skill_md(tmp_path / "beta" / "SKILL.md", "beta", "Beta")

        mgr = SkillManager()
        mgr.scan([str(tmp_path)], enabled={"beta": False})
        xml = mgr.get_catalog_xml()
        assert "<name>alpha</name>" in xml
        assert "<name>beta</name>" not in xml

    def test_catalog_escapes_special_chars(self, tmp_path):
        """Skill names/descriptions with XML special chars are escaped."""
        skill_dir = tmp_path / "myskill"
        skill_dir.mkdir()
        _write_skill_md(skill_dir / "SKILL.md", "a&b", "Use <code> & such")

        mgr = SkillManager()
        mgr.scan([str(tmp_path)])
        xml = mgr.get_catalog_xml()
        assert "&amp;" in xml
        assert "&lt;" in xml
        # Raw chars should NOT appear
        assert "<code>" not in xml


# ---------------------------------------------------------------------------
# Scan method (no implicit re-discovery)
# ---------------------------------------------------------------------------

class TestScanBehavior:
    def test_scan_rebuilds_from_scratch(self, tmp_path):
        """Subsequent scan() calls replace all skills."""
        d1 = tmp_path / "d1"
        d2 = tmp_path / "d2"
        (d1 / "first").mkdir(parents=True)
        (d2 / "second").mkdir(parents=True)
        _write_skill_md(d1 / "first" / "SKILL.md", "first", "First")
        _write_skill_md(d2 / "second" / "SKILL.md", "second", "Second")

        mgr = SkillManager()
        mgr.scan([str(d1)])
        assert mgr.list_skills() == ["first"]
        # Re-scan with different paths
        mgr.scan([str(d2)])
        assert mgr.list_skills() == ["second"]

    def test_stale_data_does_not_auto_refresh(self, tmp_path):
        """After scanning, changing files on disk does NOT change results until scan() is called again."""
        skill_dir = tmp_path / "myskill"
        skill_dir.mkdir()
        _write_skill_md(skill_dir / "SKILL.md", "myskill", "Original")

        mgr = SkillManager()
        mgr.scan([str(tmp_path)])
        assert mgr.get_skill("myskill").description == "Original"

        # Mutate the file on disk
        _write_skill_md(skill_dir / "SKILL.md", "myskill", "Updated")

        # Without calling scan(), the old data is still there
        assert mgr.get_skill("myskill").description == "Original"

        # After scan(), the new data appears
        mgr.scan([str(tmp_path)])
        assert mgr.get_skill("myskill").description == "Updated"

    def test_scan_clears_previous_disabled_state(self, tmp_path):
        """Re-scanning with different enabled settings applies the new ones."""
        skill_dir = tmp_path / "myskill"
        skill_dir.mkdir()
        _write_skill_md(skill_dir / "SKILL.md", "myskill", "Test")

        mgr = SkillManager()
        mgr.scan([str(tmp_path)], enabled={"myskill": False})
        assert mgr.list_skills() == []

        # Re-scan without disabling
        mgr.scan([str(tmp_path)], enabled=None)
        assert mgr.list_skills() == ["myskill"]


# ---------------------------------------------------------------------------
# Helper methods
# ---------------------------------------------------------------------------

class TestHelpers:
    def test_get_skill_dirs(self, tmp_path):
        """Returns (name, base_dir) pairs for enabled skills."""
        (tmp_path / "alpha").mkdir()
        (tmp_path / "beta").mkdir()
        _write_skill_md(tmp_path / "alpha" / "SKILL.md", "alpha", "A")
        _write_skill_md(tmp_path / "beta" / "SKILL.md", "beta", "B")

        mgr = SkillManager()
        mgr.scan([str(tmp_path)])
        dirs = mgr.get_skill_dirs()
        assert len(dirs) == 2
        names = {name for name, _ in dirs}
        assert names == {"alpha", "beta"}
        for name, base_dir in dirs:
            assert base_dir.endswith(name)

    def test_get_skill_cmd_dirs(self, tmp_path):
        """Returns cmd/ directories for skills that have them."""
        (tmp_path / "alpha").mkdir()
        (tmp_path / "alpha" / "cmd").mkdir()
        (tmp_path / "beta").mkdir()
        _write_skill_md(tmp_path / "alpha" / "SKILL.md", "alpha", "A")
        _write_skill_md(tmp_path / "beta" / "SKILL.md", "beta", "B")

        mgr = SkillManager()
        mgr.scan([str(tmp_path)])
        cmd_dirs = mgr.get_skill_cmd_dirs()
        assert len(cmd_dirs) == 1
        assert cmd_dirs[0].endswith("alpha/cmd")

    def test_get_skill_tools_dirs(self, tmp_path):
        """Returns tools/ directories for skills that have them."""
        (tmp_path / "alpha").mkdir()
        (tmp_path / "alpha" / "tools").mkdir()
        (tmp_path / "beta").mkdir()
        _write_skill_md(tmp_path / "alpha" / "SKILL.md", "alpha", "A")
        _write_skill_md(tmp_path / "beta" / "SKILL.md", "beta", "B")

        mgr = SkillManager()
        mgr.scan([str(tmp_path)])
        tools_dirs = mgr.get_skill_tools_dirs()
        assert len(tools_dirs) == 1
        assert tools_dirs[0].endswith("alpha/tools")

    def test_get_skill_body(self, tmp_path):
        """get_skill_body returns the markdown body."""
        skill_dir = tmp_path / "myskill"
        skill_dir.mkdir()
        _write_skill_md(skill_dir / "SKILL.md", "myskill", "Test", body="# Instructions\nDo stuff.")

        mgr = SkillManager()
        mgr.scan([str(tmp_path)])
        assert mgr.get_skill_body("myskill") == "# Instructions\nDo stuff."

    def test_get_skill_body_missing_returns_none(self, tmp_path):
        """get_skill_body for unknown skill returns None."""
        mgr = SkillManager()
        mgr.scan([str(tmp_path)])
        assert mgr.get_skill_body("nonexistent") is None

    def test_get_skill_missing_returns_none(self, tmp_path):
        """get_skill for unknown skill returns None."""
        mgr = SkillManager()
        mgr.scan([str(tmp_path)])
        assert mgr.get_skill("nonexistent") is None


# ---------------------------------------------------------------------------
# Singleton behavior
# ---------------------------------------------------------------------------

class TestSingleton:
    def test_multiple_instances_share_a_catalog(self, tmp_path):
        """SkillManager behaves like a singleton — separate instances can scan independently
        but this is a design choice.  The implementation may use a class-level cache or
        per-instance state.  This test documents the expected behavior: each instance
        manages its own state."""
        skill_dir = tmp_path / "myskill"
        skill_dir.mkdir()
        _write_skill_md(skill_dir / "SKILL.md", "myskill", "Test")

        mgr1 = SkillManager()
        mgr2 = SkillManager()
        mgr1.scan([str(tmp_path)])
        assert mgr1.list_skills() == ["myskill"]
        # mgr2 was not scanned — should be empty
        assert mgr2.list_skills() == []

    def test_module_level_instance(self):
        """There is a convenience instance at module level."""
        from core import skills
        assert isinstance(skills.skill_manager, SkillManager)


# ---------------------------------------------------------------------------
# reset
# ---------------------------------------------------------------------------

class TestReset:
    def test_reset_clears_skills(self, tmp_path):
        """reset() empties the skill catalog."""
        skill_dir = tmp_path / "myskill"
        skill_dir.mkdir()
        _write_skill_md(skill_dir / "SKILL.md", "myskill", "Test")

        mgr = SkillManager()
        mgr.scan([str(tmp_path)])
        assert mgr.list_skills() == ["myskill"]
        mgr.reset()
        assert mgr.list_skills() == []


# ---------------------------------------------------------------------------
# Skill components dirs
# ---------------------------------------------------------------------------


class TestComponentsDirs:
    def test_get_components_dirs_returns_paths(self, tmp_path):
        """Skills with a components/ directory are discovered."""
        skill_dir = tmp_path / "myskill"
        skill_dir.mkdir()
        _write_skill_md(skill_dir / "SKILL.md", "myskill", "Test")
        comp_dir = skill_dir / "components"
        comp_dir.mkdir()
        (comp_dir / "panel.py").write_text("# panel")

        mgr = SkillManager()
        mgr.scan([str(tmp_path)])
        dirs = mgr.get_skill_components_dirs()
        assert len(dirs) == 1
        assert dirs[0].endswith("components")

    def test_get_components_dirs_skips_skills_without_components(self, tmp_path):
        """Skills without a components/ directory are skipped."""
        skill_dir = tmp_path / "noskills"
        skill_dir.mkdir()
        _write_skill_md(skill_dir / "SKILL.md", "noskills", "No components")

        mgr = SkillManager()
        mgr.scan([str(tmp_path)])
        assert mgr.get_skill_components_dirs() == []

    def test_get_components_dirs_excludes_disabled(self, tmp_path):
        """Disabled skills' components dirs are not returned."""
        skill_dir = tmp_path / "disabled"
        skill_dir.mkdir()
        _write_skill_md(skill_dir / "SKILL.md", "disabled", "Test")
        comp_dir = skill_dir / "components"
        comp_dir.mkdir()

        mgr = SkillManager()
        mgr.scan([str(tmp_path)], enabled={"disabled": False})
        assert mgr.get_skill_components_dirs() == []


# ---------------------------------------------------------------------------
# Skill __init__.py dirs (optional entry point for UI skills)
# ---------------------------------------------------------------------------


class TestInitDirs:
    def test_get_init_dirs_returns_paths_for_skills_with_init(self, tmp_path):
        """Skills with __init__.py are discovered by get_skill_init_dirs()."""
        skill_dir = tmp_path / "myskill"
        skill_dir.mkdir()
        _write_skill_md(skill_dir / "SKILL.md", "myskill", "Test")
        (skill_dir / "__init__.py").write_text("# init")

        mgr = SkillManager()
        mgr.scan([str(tmp_path)])
        dirs = mgr.get_skill_init_dirs()
        assert len(dirs) == 1
        assert dirs[0].endswith("myskill")

    def test_get_init_dirs_skills_skills_without_init(self, tmp_path):
        """Skills without __init__.py are not returned by get_skill_init_dirs()."""
        skill_dir = tmp_path / "plain_skill"
        skill_dir.mkdir()
        _write_skill_md(skill_dir / "SKILL.md", "plain_skill", "No init")

        mgr = SkillManager()
        mgr.scan([str(tmp_path)])
        assert mgr.get_skill_init_dirs() == []

    def test_get_init_dirs_excludes_disabled(self, tmp_path):
        """Disabled skills' init dirs are not returned."""
        skill_dir = tmp_path / "disabled"
        skill_dir.mkdir()
        _write_skill_md(skill_dir / "SKILL.md", "disabled", "Test")
        (skill_dir / "__init__.py").write_text("# init")

        mgr = SkillManager()
        mgr.scan([str(tmp_path)], enabled={"disabled": False})
        assert mgr.get_skill_init_dirs() == []

    def test_ecosystem_skill_without_init_still_discovered(self, tmp_path):
        """A pure ecosystem skill (no __init__.py) is still discoverable and its
        body is available for agent activation."""
        skill_dir = tmp_path / "ecosystem"
        skill_dir.mkdir()
        _write_skill_md(
            skill_dir / "SKILL.md",
            "ecosystem",
            "An Anthropic-style skill",
            body="# Instructions\nYou are an expert in Python.",
        )
        # No __init__.py — this is an ecosystem skill

        mgr = SkillManager()
        mgr.scan([str(tmp_path)])
        assert mgr.list_skills() == ["ecosystem"]
        assert mgr.get_skill_body("ecosystem") == "# Instructions\nYou are an expert in Python."
        assert mgr.get_skill_init_dirs() == []


# ---------------------------------------------------------------------------
# SKILL_SERVICES convention
# ---------------------------------------------------------------------------


class TestSkillServices:
    def test_skill_services_returns_empty_before_loading(self, tmp_path):
        """get_skill_services() returns empty dict before bootstrap loads skills."""
        skill_dir = tmp_path / "myskill"
        skill_dir.mkdir()
        _write_skill_md(skill_dir / "SKILL.md", "myskill", "Test")

        mgr = SkillManager()
        mgr.scan([str(tmp_path)])
        assert mgr.get_skill_services() == {}

    def test_set_skill_services_stores_and_returns(self, tmp_path):
        """set_skill_services() stores services that get_skill_services() returns."""
        mgr = SkillManager()
        factories = {"my_service": lambda cfg, v: "service_instance"}
        mgr.set_skill_services(factories)
        services = mgr.get_skill_services()
        assert "my_service" in services
        assert services["my_service"](None, None) == "service_instance"

    def test_skill_without_init_has_no_services(self, tmp_path):
        """A skill without __init__.py has no services."""
        skill_dir = tmp_path / "plain"
        skill_dir.mkdir()
        _write_skill_md(skill_dir / "SKILL.md", "plain", "Plain skill")

        mgr = SkillManager()
        mgr.scan([str(tmp_path)])
        assert mgr.get_skill_services() == {}

    def test_reset_clears_services(self, tmp_path):
        """reset() clears stored services."""
        mgr = SkillManager()
        mgr.set_skill_services({"svc": lambda cfg, v: "x"})
        assert mgr.get_skill_services() != {}
        mgr.reset()
        assert mgr.get_skill_services() == {}

    def test_disabled_skill_services_excluded(self, tmp_path):
        """Disabled skills' services should not be loaded (bootstrap responsibility).

        SkillManager just stores whatever bootstrap gives it.  Bootstrap
        only loads enabled skills, so disabled skills won't contribute services."""
        # This is testing the contract: SkillManager stores, bootstrap filters.
        mgr = SkillManager()
        # Bootstrap would only pass services from enabled skills
        mgr.set_skill_services({"enabled_svc": lambda cfg, v: "result"})
        services = mgr.get_skill_services()
        assert "enabled_svc" in services

    def test_later_tier_skill_services_override_earlier(self, tmp_path):
        """Later-tier skill services override earlier-tier (bootstrap responsibility).

        SkillManager just stores the merged dict.  Bootstrap processes
        tiers in order so later tiers overwrite."""
        mgr = SkillManager()
        # Bootstrap would process tier1 then tier2, overwriting t1 with t2
        factories = {"svc": lambda cfg, v: "t2_service"}
        mgr.set_skill_services(factories)
        services = mgr.get_skill_services()
        assert services["svc"](None, None) == "t2_service"


# ---------------------------------------------------------------------------
# Autouse fixture — reset before every test
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_skill_manager():
    from core.skills import skill_manager
    skill_manager.reset()
